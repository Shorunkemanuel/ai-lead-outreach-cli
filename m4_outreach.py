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

DEFAULT_DAILY_LIMIT = 10


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
    """Create M4 tables without changing existing M1-M3 data."""
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS outreach_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            draft_id INTEGER NOT NULL,
            destination TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'whatsapp',
            status TEXT NOT NULL DEFAULT 'QUEUED',
            queued_at TEXT NOT NULL,
            sent_at TEXT,
            provider_message_id TEXT,
            error TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
            FOREIGN KEY (draft_id) REFERENCES outreach_drafts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS suppression_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            destination TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE SET NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_draft ON outreach_queue(draft_id);
        CREATE INDEX IF NOT EXISTS idx_queue_status ON outreach_queue(status);
        CREATE INDEX IF NOT EXISTS idx_suppression_destination ON suppression_list(destination);

        CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            draft_id INTEGER,
            queue_id INTEGER,
            event TEXT NOT NULL,
            detail TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_events_lead ON outreach_events(lead_id);
        """
    )
    c.commit()


def _event(c, lead_id: int, event: str, detail: str = "", draft_id: int | None = None, queue_id: int | None = None) -> None:
    c.execute(
        "INSERT INTO outreach_events(lead_id,draft_id,queue_id,event,detail,created_at) VALUES(?,?,?,?,?,?)",
        (lead_id, draft_id, queue_id, event, detail, utc_now()),
    )


def suppress(c: sqlite3.Connection, destination: str, reason: str, lead_id: int | None = None) -> None:
    destination = destination.strip()
    if not destination:
        raise ValueError("destination is required")
    c.execute(
        "INSERT INTO suppression_list(lead_id,destination,reason,created_at) VALUES(?,?,?,?)",
        (lead_id, destination, reason.strip() or "unspecified", utc_now()),
    )
    if lead_id is not None:
        c.execute("UPDATE leads SET status='DO_NOT_CONTACT', updated_at=? WHERE id=?", (utc_now(), lead_id))
        _event(c, lead_id, "SUPPRESSED", reason)
    c.commit()


def is_suppressed(c: sqlite3.Connection, destination: str) -> bool:
    return c.execute(
        "SELECT 1 FROM suppression_list WHERE destination=? LIMIT 1", (destination.strip(),)
    ).fetchone() is not None


def approve_and_queue(c: sqlite3.Connection, draft_id: int) -> QueueResult:
    """Approve an existing GENERATED draft and queue it, with safety gates."""
    draft = c.execute(
        "SELECT d.*, l.status AS lead_status, l.phone, l.email FROM outreach_drafts d JOIN leads l ON l.id=d.lead_id WHERE d.id=?",
        (draft_id,),
    ).fetchone()
    if not draft:
        return QueueResult(False, "draft not found")
    if draft["status"] != "APPROVED":
        return QueueResult(False, "draft must be APPROVED before queueing")
    if draft["lead_status"] not in {"QUALIFIED", "DRAFTED", "APPROVED"}:
        return QueueResult(False, f"lead status blocks outreach: {draft['lead_status']}")
    destination = (draft["phone"] or draft["email"] or "").strip()
    if not destination:
        return QueueResult(False, "no valid destination")
    if is_suppressed(c, destination):
        return QueueResult(False, "destination is suppressed")
    existing = c.execute("SELECT id,status FROM outreach_queue WHERE draft_id=?", (draft_id,)).fetchone()
    if existing:
        return QueueResult(False, "draft is already queued or processed", existing["id"])
    now = utc_now()
    cur = c.execute(
        "INSERT INTO outreach_queue(lead_id,draft_id,destination,channel,status,queued_at) VALUES(?,?,?,?,?,?)",
        (draft["lead_id"], draft_id, destination, "whatsapp", "QUEUED", now),
    )
    queue_id = cur.lastrowid
    c.execute("UPDATE leads SET status='APPROVED', updated_at=? WHERE id=?", (now, draft["lead_id"]))
    _event(c, draft["lead_id"], "QUEUED", "approved draft queued", draft_id, queue_id)
    c.commit()
    return QueueResult(True, "queued", queue_id)


def mark_draft_approved(c: sqlite3.Connection, draft_id: int) -> None:
    row = c.execute("SELECT lead_id,status FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        raise ValueError("draft not found")
    if row["status"] != "GENERATED":
        raise ValueError("only GENERATED drafts can be approved")
    now = utc_now()
    c.execute("UPDATE outreach_drafts SET status='APPROVED', reviewed_at=? WHERE id=?", (now, draft_id))
    _event(c, row["lead_id"], "APPROVED", "human approval recorded", draft_id)
    c.commit()


def send_queued(c: sqlite3.Connection, provider: MessageProvider, daily_limit: int = DEFAULT_DAILY_LIMIT, dry_run: bool = False) -> dict[str, int]:
    """Process queued messages once. No automatic retry is performed."""
    today = datetime.now(timezone.utc).date().isoformat()
    row = c.execute("SELECT messages_sent FROM daily_usage WHERE usage_date=?", (today,)).fetchone()
    sent_today = row[0] if row else 0
    remaining = max(0, daily_limit - sent_today)
    rows = c.execute(
        "SELECT q.*, d.message FROM outreach_queue q JOIN outreach_drafts d ON d.id=q.draft_id WHERE q.status='QUEUED' ORDER BY q.id"
    ).fetchall()
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
