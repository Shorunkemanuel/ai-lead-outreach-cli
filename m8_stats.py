#!/usr/bin/env python3
"""Milestone 8: read-only statistics and CLI reporting.

This module deliberately does not mutate outreach state. It reads the existing
M1-M7 SQLite schema and presents a compact operational report, with an optional
JSON representation for scripting.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

APP_NAME = "AI Lead Outreach CLI"
M8_VERSION = "M8"
DEFAULT_DB = "outreach.db"
DEFAULT_DAILY_LIMIT = 10


def _rows_to_counts(rows: list[sqlite3.Row], key: str) -> dict[str, int]:
    return {str(row[key]): int(row["count"]) for row in rows}


def collect_stats(c: sqlite3.Connection, daily_limit: int = DEFAULT_DAILY_LIMIT) -> dict[str, Any]:
    """Collect deterministic, read-only M8 statistics from the current DB."""
    c.row_factory = sqlite3.Row
    today = datetime.now(timezone.utc).date().isoformat()

    total_leads = int(c.execute("SELECT COUNT(*) FROM leads").fetchone()[0])
    status_rows = c.execute(
        "SELECT status, COUNT(*) AS count FROM leads GROUP BY status ORDER BY status"
    ).fetchall()
    priority_rows = c.execute(
        """
        SELECT COALESCE(qualification_priority, 'UNRATED') AS priority,
               COUNT(*) AS count
        FROM leads
        GROUP BY COALESCE(qualification_priority, 'UNRATED')
        ORDER BY priority
        """
    ).fetchall()
    score_row = c.execute(
        "SELECT COUNT(qualification_score) AS scored, AVG(qualification_score) AS average_score FROM leads"
    ).fetchone()
    draft_rows = c.execute(
        "SELECT status, COUNT(*) AS count FROM outreach_drafts GROUP BY status ORDER BY status"
    ).fetchall()

    queue_rows: list[sqlite3.Row] = []
    try:
        queue_rows = c.execute(
            "SELECT status, COUNT(*) AS count FROM outreach_queue GROUP BY status ORDER BY status"
        ).fetchall()
    except sqlite3.OperationalError:
        pass

    channel_rows: list[sqlite3.Row] = []
    provider_rows: list[sqlite3.Row] = []
    sent_today_queue = 0
    try:
        channel_rows = c.execute(
            "SELECT channel, COUNT(*) AS count FROM outreach_queue WHERE status='SENT' GROUP BY channel ORDER BY channel"
        ).fetchall()
        provider_rows = c.execute(
            "SELECT provider, COUNT(*) AS count FROM outreach_queue WHERE status='SENT' GROUP BY provider ORDER BY provider"
        ).fetchall()
        sent_today_queue = int(c.execute(
            """
            SELECT COUNT(*)
            FROM outreach_queue
            WHERE status='SENT' AND sent_at IS NOT NULL
              AND substr(sent_at, 1, 10)=?
            """,
            (today,),
        ).fetchone()[0])
    except sqlite3.OperationalError:
        pass

    usage_row = c.execute(
        "SELECT messages_sent FROM daily_usage WHERE usage_date=?", (today,)
    ).fetchone()
    daily_usage_sent = int(usage_row[0]) if usage_row else 0

    return {
        "version": M8_VERSION,
        "date_utc": today,
        "leads": {
            "total": total_leads,
            "by_status": _rows_to_counts(status_rows, "status"),
            "qualification": {
                "by_priority": _rows_to_counts(priority_rows, "priority"),
                "scored": int(score_row["scored"]),
                "average_score": round(float(score_row["average_score"]), 2)
                if score_row["average_score"] is not None else None,
            },
        },
        "drafts": {"by_status": _rows_to_counts(draft_rows, "status")},
        "outreach": {
            "daily_limit": int(daily_limit),
            "sent_today": daily_usage_sent,
            "remaining_today": max(0, int(daily_limit) - daily_usage_sent),
            "queue_by_status": _rows_to_counts(queue_rows, "status"),
            "sent_today_by_channel": _rows_to_counts(channel_rows, "channel"),
            "sent_today_by_provider": _rows_to_counts(provider_rows, "provider"),
            "queue_sent_today": sent_today_queue,
        },
    }



def build_stats(c, daily_limit=DEFAULT_DAILY_LIMIT):
    """Stable M9 V1 statistics API."""
    return collect_stats(c, daily_limit=daily_limit)


def _print_section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def print_stats(stats: dict[str, Any], section: str = "all") -> None:
    """Render human-readable M8 statistics without changing database state."""
    section = section.lower()
    if section not in {"all", "leads", "drafts", "outreach"}:
        raise ValueError(f"Unknown stats section: {section}")

    print(f"{APP_NAME} — {stats['version']}\nUTC date: {stats['date_utc']}")

    if section in {"all", "leads"}:
        _print_section("Leads")
        print(f"Total: {stats['leads']['total']}")
        for name, count in stats["leads"]["by_status"].items():
            print(f"{name:<18} {count}")
        q = stats["leads"]["qualification"]
        print(f"Scored: {q['scored']}")
        print(f"Average score: {q['average_score'] if q['average_score'] is not None else 'n/a'}")
        if q["by_priority"]:
            print("Priority:")
            for name, count in q["by_priority"].items():
                print(f"  {name:<16} {count}")

    if section in {"all", "drafts"}:
        _print_section("Drafts")
        counts = stats["drafts"]["by_status"]
        if counts:
            for name, count in counts.items():
                print(f"{name:<18} {count}")
        else:
            print("No drafts")

    if section in {"all", "outreach"}:
        _print_section("Outreach")
        o = stats["outreach"]
        print(f"Sent today: {o['sent_today']}/{o['daily_limit']}")
        print(f"Remaining today: {o['remaining_today']}")
        print(f"Queue sent today: {o['queue_sent_today']}")
        if o["queue_by_status"]:
            print("Queue:")
            for name, count in o["queue_by_status"].items():
                print(f"  {name:<16} {count}")
        if o["sent_today_by_channel"]:
            print("Sent by channel:")
            for name, count in o["sent_today_by_channel"].items():
                print(f"  {name:<16} {count}")
        if o["sent_today_by_provider"]:
            print("Sent by provider:")
            for name, count in o["sent_today_by_provider"].items():
                print(f"  {name:<16} {count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="m8_stats.py",
        description="Read-only M8 statistics and CLI reporting for AI Lead Outreach CLI.",
    )
    parser.add_argument("--db", default=DEFAULT_DB, help="SQLite database path (default: outreach.db)")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_DAILY_LIMIT,
        help="Daily outreach limit shown in the report (default: 10)",
    )
    parser.add_argument(
        "--section", choices=["all", "leads", "drafts", "outreach"], default="all",
        help="Show one report section or the full report",
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="Print machine-readable JSON")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {M8_VERSION}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    try:
        c = sqlite3.connect(args.db)
    except sqlite3.Error as exc:
        raise SystemExit(f"Could not open database: {exc}") from exc
    try:
        stats = collect_stats(c, args.limit)
    finally:
        c.close()

    if args.as_json:
        print(json.dumps(stats, indent=2, sort_keys=True))
    else:
        print_stats(stats, args.section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
