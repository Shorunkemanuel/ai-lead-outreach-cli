"""Milestone 4: safe, provider-agnostic outreach execution.

No WhatsApp/browser automation is implemented here. The module provides the
queue, suppression, safety gates, audit trail, daily limit, and a MockProvider
for deterministic local testing. A real official provider can implement the
same interface later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from typing import Optional, Protocol

from messaging import get_provider, is_supported_provider

DEFAULT_DAILY_LIMIT = 10

DEFAULT_GLOBAL_DAILY_LIMIT = 30
DEFAULT_CHANNEL_LIMITS = {
    "email": 20,
    "whatsapp": 10,
}
DEFAULT_PROVIDER_LIMITS = {
    "mock_email": 20,
    "mock_whatsapp": 10,
}
DEFAULT_COOLDOWN_DAYS = 7
DEFAULT_DUPLICATE_PROTECTION = True


@dataclass(frozen=True)
class SafetyDecision:
    allowed: bool
    reason: str


def get_safety_config() -> dict:
    """Return the conservative application-level M7 safety configuration."""
    return {
        "global_daily_limit": DEFAULT_GLOBAL_DAILY_LIMIT,
        "channel_limits": dict(DEFAULT_CHANNEL_LIMITS),
        "provider_limits": dict(DEFAULT_PROVIDER_LIMITS),
        "cooldown_days": DEFAULT_COOLDOWN_DAYS,
        "duplicate_protection": DEFAULT_DUPLICATE_PROTECTION,
    }


def get_channel_limit(channel: str) -> int:
    channel = channel.strip().lower()
    return DEFAULT_CHANNEL_LIMITS.get(channel, 0)


def get_provider_limit(provider: str) -> int:
    provider = provider.strip().lower()
    return DEFAULT_PROVIDER_LIMITS.get(provider, 0)


def _sent_count_today(
    c: sqlite3.Connection,
    *,
    channel: str | None = None,
    provider: str | None = None,
) -> int:
    """Count successfully sent messages for today's safety accounting."""
    today = datetime.now(timezone.utc).date().isoformat()

    if channel is None and provider is None:
        row = c.execute(
            """
            SELECT messages_sent
            FROM daily_usage
            WHERE usage_date=?
            """,
            (today,),
        ).fetchone()
        return int(row[0]) if row else 0

    query = """
        SELECT COUNT(*)
        FROM outreach_queue
        WHERE status='SENT'
          AND substr(sent_at, 1, 10)=?
    """
    params: list[str] = [today]

    if channel is not None:
        query += " AND channel=?"
        params.append(channel)

    if provider is not None:
        query += " AND provider=?"
        params.append(provider)

    row = c.execute(query, params).fetchone()
    return int(row[0]) if row else 0


def check_duplicate_send(
    c: sqlite3.Connection,
    lead_id: int,
    destination: str,
) -> bool:
    """Return True when this lead/destination has already been successfully contacted."""
    row = c.execute(
        """
        SELECT 1
        FROM outreach_queue
        WHERE lead_id=?
          AND destination=?
          AND status='SENT'
        LIMIT 1
        """,
        (lead_id, destination.strip()),
    ).fetchone()
    return row is not None


def check_cooldown(
    c: sqlite3.Connection,
    lead_id: int,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> bool:
    """Return True when the lead is still inside the post-contact cooldown."""
    if cooldown_days <= 0:
        return False

    row = c.execute(
        """
        SELECT sent_at
        FROM outreach_queue
        WHERE lead_id=?
          AND status='SENT'
          AND sent_at IS NOT NULL
        ORDER BY sent_at DESC
        LIMIT 1
        """,
        (lead_id,),
    ).fetchone()


    if not row:
        return False

    last_sent = datetime.fromisoformat(str(row[0]))

    if last_sent.tzinfo is None:
        last_sent = last_sent.replace(tzinfo=timezone.utc)
    else:
        last_sent = last_sent.astimezone(timezone.utc)

    elapsed = datetime.now(timezone.utc) - last_sent
    return elapsed.total_seconds() < cooldown_days * 86400



def check_outreach_safety(
    c: sqlite3.Connection,
    *,
    lead_id: int,
    destination: str,
    channel: str,
    provider: str,
) -> SafetyDecision:
    """Evaluate M7 safety gates without sending anything."""
    config = get_safety_config()

    channel = channel.strip().lower()
    provider = provider.strip().lower()
    destination = destination.strip()

    if not destination:
        return SafetyDecision(False, "destination is required")

    if channel not in config["channel_limits"]:
        return SafetyDecision(False, f"unsupported channel: {channel}")

    if provider not in config["provider_limits"]:
        return SafetyDecision(False, f"unsupported provider: {provider}")

    if is_suppressed(c, destination):
        return SafetyDecision(False, "destination is suppressed")

    if config["duplicate_protection"] and check_duplicate_send(
        c, lead_id, destination
    ):
        return SafetyDecision(False, "duplicate send blocked")

    if check_cooldown(c, lead_id, config["cooldown_days"]):
        return SafetyDecision(False, "lead is inside cooldown period")

    global_count = _sent_count_today(c)
    if global_count >= config["global_daily_limit"]:
        return SafetyDecision(False, "global daily limit reached")

    channel_count = _sent_count_today(c, channel=channel)
    if channel_count >= config["channel_limits"][channel]:
        return SafetyDecision(False, f"{channel} daily limit reached")

    provider_count = _sent_count_today(c, provider=provider)
    if provider_count >= config["provider_limits"][provider]:
        return SafetyDecision(False, f"{provider} daily limit reached")

    return SafetyDecision(True, "outreach allowed")


class MessageProvider(Protocol):
    def send(self, destination: str, message: str) -> str: ...

class MockProvider:
    """Deterministic provider used by tests and dry-run development."""
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.sent: list[tuple[str, str]] = []
    def send(self, destination: str, message: str) -> str:
        if self.should_fail:
            raise RuntimeError("mock provider failure")
        self.sent.append((destination, message))
        return f"mock-{len(self.sent)}"

@dataclass(frozen=True)
class QueueResult:
    queued: bool
    reason: str
    queue_id: Optional[int] = None

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def initialize_m4(c: sqlite3.Connection) -> None:
    c.executescript("""
        CREATE TABLE IF NOT EXISTS daily_usage (usage_date TEXT PRIMARY KEY, messages_sent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS outreach_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL, draft_id INTEGER NOT NULL,
            destination TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'whatsapp',
            provider TEXT NOT NULL DEFAULT 'mock_whatsapp',
            status TEXT NOT NULL DEFAULT 'QUEUED',
            queued_at TEXT NOT NULL, sent_at TEXT, provider_message_id TEXT, error TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
            FOREIGN KEY (draft_id) REFERENCES outreach_drafts(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS suppression_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER, destination TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_draft ON outreach_queue(draft_id);
        CREATE INDEX IF NOT EXISTS idx_queue_status ON outreach_queue(status);
        CREATE INDEX IF NOT EXISTS idx_suppression_destination ON suppression_list(destination);
        CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL, draft_id INTEGER,
            queue_id INTEGER, event TEXT NOT NULL, detail TEXT DEFAULT '', created_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_events_lead ON outreach_events(lead_id);
    """)
    # Migrate databases created before M6.
    columns = {row["name"] for row in c.execute("PRAGMA table_info(outreach_queue)").fetchall()}
    if "provider" not in columns:
        c.execute(
            "ALTER TABLE outreach_queue ADD COLUMN provider TEXT NOT NULL DEFAULT 'mock_whatsapp'"
        )
    c.commit()

def _event(c: sqlite3.Connection, lead_id: int, event: str, detail: str = "", draft_id: int | None = None, queue_id: int | None = None) -> None:
    c.execute("INSERT INTO outreach_events(lead_id,draft_id,queue_id,event,detail,created_at) VALUES(?,?,?,?,?,?)", (lead_id, draft_id, queue_id, event, detail, utc_now()))

def suppress(c: sqlite3.Connection, destination: str, reason: str, lead_id: int | None = None) -> None:
    destination = destination.strip()
    if not destination:
        raise ValueError("destination is required")
    initialize_m4(c)
    c.execute("INSERT INTO suppression_list(lead_id,destination,reason,created_at) VALUES(?,?,?,?)", (lead_id, destination, reason.strip() or "unspecified", utc_now()))
    if lead_id is not None:
        c.execute("UPDATE leads SET status='DO_NOT_CONTACT', updated_at=? WHERE id=?", (utc_now(), lead_id))
        _event(c, lead_id, "SUPPRESSED", reason)
    c.commit()

def is_suppressed(c: sqlite3.Connection, destination: str) -> bool:
    return c.execute("SELECT 1 FROM suppression_list WHERE destination=? LIMIT 1", (destination.strip(),)).fetchone() is not None

def mark_draft_approved(c: sqlite3.Connection, draft_id: int) -> None:
    """Record human approval without sending or queueing the message."""
    initialize_m4(c)
    row = c.execute("SELECT lead_id,status FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        raise ValueError("draft not found")
    if row["status"] != "GENERATED":
        raise ValueError("only GENERATED drafts can be approved")
    now = utc_now()
    c.execute("UPDATE outreach_drafts SET status='APPROVED', reviewed_at=? WHERE id=?", (now, draft_id))
    _event(c, row["lead_id"], "APPROVED", "human approval recorded", draft_id)
    c.commit()

def approve_draft(c: sqlite3.Connection, draft_id: int) -> None:
    """Public approval transition: GENERATED -> APPROVED."""
    mark_draft_approved(c, draft_id)

def queue_draft(
    c: sqlite3.Connection,
    draft_id: int,
    channel: str = "whatsapp",
    provider: str = "mock_whatsapp",
) -> QueueResult:
    """Queue an approved draft for a specific channel/provider."""

    initialize_m4(c)

    channel = channel.strip().lower()
    provider = provider.strip().lower()

    if channel not in {"email", "whatsapp"}:
        return QueueResult(False, f"unsupported channel: {channel}")

    if not is_supported_provider(provider, channel=channel):
        raise ValueError(f"Unsupported messaging provider: {channel}/{provider}")

    draft = c.execute(
        """
        SELECT d.*, l.status AS lead_status, l.phone, l.email
        FROM outreach_drafts d
        JOIN leads l ON l.id=d.lead_id
        WHERE d.id=?
        """,
        (draft_id,),
    ).fetchone()

    if not draft:
        return QueueResult(False, "draft not found")

    if draft["status"] != "APPROVED":
        return QueueResult(False, "draft must be APPROVED before queueing")

    if draft["lead_status"] == "DO_NOT_CONTACT":
        return QueueResult(False, "lead is DO_NOT_CONTACT")

    if channel == "email":
        destination = (draft["email"] or "").strip()
    else:
        destination = (draft["phone"] or "").strip()

    if not destination:
        return QueueResult(False, f"no valid {channel} destination")

    if is_suppressed(c, destination):
        return QueueResult(False, "destination is suppressed")

    existing = c.execute(
        "SELECT id,status FROM outreach_queue WHERE draft_id=?",
        (draft_id,),
    ).fetchone()

    if existing:
        return QueueResult(
            False,
            "draft is already queued or processed",
            existing["id"],
        )

    now = utc_now()

    cur = c.execute(
        """
        INSERT INTO outreach_queue(
            lead_id, draft_id, destination, channel, provider,
            status, queued_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft["lead_id"],
            draft_id,
            destination,
            channel,
            provider,
            "QUEUED",
            now,
        ),
    )

    queue_id = cur.lastrowid

    c.execute(
        "UPDATE leads SET status='APPROVED', updated_at=? WHERE id=?",
        (now, draft["lead_id"]),
    )

    _event(
        c,
        draft["lead_id"],
        "QUEUED",
        f"approved draft queued via {channel}/{provider}",
        draft_id,
        queue_id,
    )

    c.commit()

    return QueueResult(True, "queued", queue_id)

def approve_and_queue(
    c: sqlite3.Connection,
    draft_id: int,
    channel: str = "whatsapp",
    provider: str = "mock_whatsapp",
) -> QueueResult:
    return queue_draft(c, draft_id, channel=channel, provider=provider)

def send_queued(c: sqlite3.Connection, provider: MessageProvider, daily_limit: int = DEFAULT_DAILY_LIMIT, dry_run: bool = False) -> dict[str, int]:
    """Process queued messages once. No automatic retry is performed."""
    initialize_m4(c)
    today = datetime.now(timezone.utc).date().isoformat()
    row = c.execute("SELECT messages_sent FROM daily_usage WHERE usage_date=?", (today,)).fetchone()
    sent_today = row[0] if row else 0
    remaining = max(0, daily_limit - sent_today)
    rows = c.execute("SELECT q.*, d.message FROM outreach_queue q JOIN outreach_drafts d ON d.id=q.draft_id WHERE q.status='QUEUED' ORDER BY q.id").fetchall()
    processed = sent = failed = blocked = 0
    for q in rows:
        if remaining <= 0:
            break
        processed += 1
        if is_suppressed(c, q["destination"]):
            c.execute("UPDATE outreach_queue SET status='BLOCKED',error=? WHERE id=?", ("destination is suppressed", q["id"]))
            _event(c, q["lead_id"], "BLOCKED", "suppressed destination", q["draft_id"], q["id"])
            blocked += 1
            continue
        if dry_run:
            _event(c, q["lead_id"], "DRY_RUN", "send skipped; no provider call", q["draft_id"], q["id"])
            continue
        try:
            provider_id = provider.send(q["destination"], q["message"])
        except Exception as exc:
            c.execute("UPDATE outreach_queue SET status='FAILED',error=? WHERE id=?", (str(exc), q["id"]))
            _event(c, q["lead_id"], "FAILED", str(exc), q["draft_id"], q["id"])
            failed += 1
            continue
        now = utc_now()
        c.execute("UPDATE outreach_queue SET status='SENT',sent_at=?,provider_message_id=? WHERE id=?", (now, provider_id, q["id"]))
        c.execute("UPDATE leads SET status='CONTACTED',updated_at=? WHERE id=?", (now, q["lead_id"]))
        c.execute("INSERT INTO daily_usage(usage_date,messages_sent) VALUES(?,1) ON CONFLICT(usage_date) DO UPDATE SET messages_sent=messages_sent+1", (today,))
        _event(c, q["lead_id"], "SENT", f"provider_message_id={provider_id}", q["draft_id"], q["id"])
        sent += 1
        remaining -= 1
    c.commit()
    return {"processed": processed, "sent": sent, "failed": failed, "blocked": blocked}

def execute_queue(c: sqlite3.Connection, provider: MessageProvider | None = None, daily_limit: int = DEFAULT_DAILY_LIMIT, dry_run: bool = False) -> dict[str, int]:
    """Public M4 execution entry point. Real sending requires an injected provider."""
    initialize_m4(c)
    if dry_run:
        class _NoSendProvider:
            def send(self, destination: str, message: str) -> str:
                raise AssertionError("dry_run must not call provider")
        provider = _NoSendProvider()
    if provider is None:
        raise ValueError("provider is required unless dry_run=True")
    return send_queued(c, provider, daily_limit=daily_limit, dry_run=dry_run)
