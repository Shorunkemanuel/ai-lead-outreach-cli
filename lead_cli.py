#!/usr/bin/env python3
"""AI Lead Outreach CLI — V1.

Local-first lead ingestion and qualification foundation. External messaging is
not implemented in this milestone.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME = "AI Lead Outreach CLI"
DEFAULT_DB = "outreach.db"
DEFAULT_CONFIG = "config.json"
DEFAULT_DAILY_LIMIT = 10
REQUIRED_CSV_COLUMNS = {"Company"}
ALLOWED_STATUSES = {
    "NEW", "QUALIFIED", "DRAFTED", "APPROVED", "CONTACTED", "REPLIED",
    "INTERESTED", "MEETING", "WON", "LOST", "DO_NOT_CONTACT",
}
PHONE_RE = re.compile(r"^\+?[0-9][0-9]{6,14}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Lead:
    company: str
    contact_name: str = ""
    job_title: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    industry: str = ""
    country: str = ""
    employees: str = ""
    painpoint: str = ""
    source: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: str = DEFAULT_CONFIG) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "ai": {"provider": "ollama", "base_url": "http://localhost:11434", "model": "qwen2.5:1.5b", "timeout_seconds": 60},
        "database": {"path": DEFAULT_DB},
        "outreach": {"daily_limit": DEFAULT_DAILY_LIMIT, "default_message_style": "professional", "dry_run": True},
        "messaging": {"provider": "disabled"},
    }
    config_path = Path(path)
    if not config_path.exists():
        return defaults
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    for section, values in defaults.items():
        if isinstance(values, dict):
            loaded.setdefault(section, {})
            for key, value in values.items():
                loaded[section].setdefault(key, value)
        else:
            loaded.setdefault(section, values)
    return loaded


def connect_db(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_db(connection)
    return connection


def initialize_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            contact_name TEXT DEFAULT '',
            job_title TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            website TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            country TEXT DEFAULT '',
            employees TEXT DEFAULT '',
            painpoint TEXT DEFAULT '',
            source TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'NEW',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_identity ON leads(company, phone, email);
        CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
        CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company);

        CREATE TABLE IF NOT EXISTS outreach (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            original_message TEXT DEFAULT '',
            channel TEXT NOT NULL DEFAULT 'whatsapp',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            generated_at TEXT NOT NULL,
            approved_at TEXT,
            sent_at TEXT,
            error TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach(lead_id);
        CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);

        CREATE TABLE IF NOT EXISTS daily_usage (
            usage_date TEXT PRIMARY KEY,
            messages_sent INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.commit()


def normalize_text(value: str | None) -> str:
    return " ".join((value or "").strip().split())


def normalize_phone(value: str | None) -> str:
    value = normalize_text(value)
    return re.sub(r"[\s().-]", "", value) if value else ""


def valid_phone(value: str) -> bool:
    return bool(PHONE_RE.fullmatch(value))


def valid_email(value: str) -> bool:
    return not value or bool(EMAIL_RE.fullmatch(value))


def validate_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    company = normalize_text(row.get("Company"))
    phone = normalize_phone(row.get("Phone"))
    email = normalize_text(row.get("Email"))
    if not company:
        errors.append("missing company")
    if phone and not valid_phone(phone):
        errors.append("invalid phone")
    if email and not valid_email(email):
        errors.append("invalid email")
    if not phone and not email:
        errors.append("no phone or email")
    return errors


def row_to_lead(row: dict[str, str]) -> Lead:
    return Lead(
        company=normalize_text(row.get("Company")),
        contact_name=normalize_text(row.get("Contact Name")),
        job_title=normalize_text(row.get("Job Title")),
        phone=normalize_phone(row.get("Phone")),
        email=normalize_text(row.get("Email")),
        website=normalize_text(row.get("Website")),
        industry=normalize_text(row.get("Industry")),
        country=normalize_text(row.get("Country")),
        employees=normalize_text(row.get("Employees")),
        painpoint=normalize_text(row.get("Painpoint")),
        source=normalize_text(row.get("Source")),
    )


def score_lead(lead: Lead) -> tuple[int, list[str]]:
    """Return a deterministic 0–100 data-completeness score for M1/M2 use."""
    score = 0
    reasons: list[str] = []
    checks = [
        (lead.phone, 20, "phone available"),
        (lead.email, 15, "email available"),
        (lead.job_title, 20, "contact role available"),
        (lead.website, 15, "website available"),
        (lead.painpoint, 15, "painpoint supplied"),
        (lead.industry, 5, "industry supplied"),
        (lead.employees, 5, "company size supplied"),
        (lead.company, 5, "company identified"),
    ]
    for present, points, reason in checks:
        if present:
            score += points
            reasons.append(reason)
    return min(score, 100), reasons


def import_csv(csv_path: str, connection: sqlite3.Connection) -> tuple[int, int, int]:
    imported = duplicates = invalid = 0
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = {normalize_text(column) for column in (reader.fieldnames or [])}
        missing = REQUIRED_CSV_COLUMNS - columns
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            row = {(key or "").strip(): (value or "") for key, value in row.items()}
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"⚠ Invalid: {row.get('Company') or '<unknown>'} — {', '.join(errors)}")
                continue
            lead = row_to_lead(row)
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO leads
                (company, contact_name, job_title, phone, email, website, industry,
                 country, employees, painpoint, source, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?)
                """,
                (lead.company, lead.contact_name, lead.job_title, lead.phone, lead.email, lead.website,
                 lead.industry, lead.country, lead.employees, lead.painpoint, lead.source, now, now),
            )
            if cursor.rowcount == 1:
                imported += 1
            else:
                duplicates += 1
    connection.commit()
    return imported, duplicates, invalid


def show_leads(connection: sqlite3.Connection, status: str | None = None) -> None:
    if status and status not in ALLOWED_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    if status:
        rows = connection.execute(
            "SELECT id, company, contact_name, phone, email, status FROM leads WHERE status=? ORDER BY id",
            (status,),
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT id, company, contact_name, phone, email, status FROM leads ORDER BY id"
        ).fetchall()
    if not rows:
        print("No leads found.")
        return
    print(f"\n{'ID':<5} {'Company':<28} {'Contact':<20} {'Phone':<17} {'Status'}")
    print("-" * 90)
    for row in rows:
        print(f"{row['id']:<5} {row['company'][:27]:<28} {row['contact_name'][:19]:<20} {row['phone'][:16]:<17} {row['status']}")


def show_stats(connection: sqlite3.Connection, daily_limit: int = DEFAULT_DAILY_LIMIT) -> None:
    lead_count = connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    status_rows = connection.execute("SELECT status, COUNT(*) AS count FROM leads GROUP BY status ORDER BY status").fetchall()
    outreach_counts = connection.execute("SELECT status, COUNT(*) AS count FROM outreach GROUP BY status").fetchall()
    today = datetime.now(timezone.utc).date().isoformat()
    usage_row = connection.execute("SELECT messages_sent FROM daily_usage WHERE usage_date=?", (today,)).fetchone()
    today_sent = usage_row[0] if usage_row else 0
    print(f"\n{APP_NAME}\n{'=' * len(APP_NAME)}")
    print(f"Total leads:       {lead_count}")
    for row in status_rows:
        print(f"{row['status'] + ':':<20}{row['count']}")
    print("\nOutreach")
    for row in outreach_counts:
        print(f"{row['status'] + ':':<20}{row['count']}")
    print(f"\nSent today:        {today_sent}/{daily_limit}")


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("command", nargs="?", choices=["import", "leads", "stats", "analyze", "review", "send", "run"])
    parser.add_argument("path", nargs="?", help="CSV path for import")
    parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), help="Filter leads by status")
    parser.add_argument("--dry-run", action="store_true", help="Never send external messages")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Configuration file")
    args = parser.parse_args()
    config = load_config(args.config)
    db_path = config.get("database", {}).get("path", DEFAULT_DB)
    daily_limit = int(config.get("outreach", {}).get("daily_limit", DEFAULT_DAILY_LIMIT))
    connection = connect_db(db_path)
    try:
        if args.command == "import":
            if not args.path:
                parser.error("import requires a CSV path")
            imported, duplicates, invalid = import_csv(args.path, connection)
            print(f"\nImport complete\n{'-' * 30}\nImported:    {imported}\nDuplicates:  {duplicates}\nInvalid:     {invalid}")
        elif args.command == "leads":
            show_leads(connection, args.status)
        elif args.command == "stats":
            show_stats(connection, daily_limit)
        elif args.command in {"analyze", "review", "send", "run"}:
            print(f"{args.command} workflow is scheduled for the next milestone.")
            if args.dry_run or args.command == "run":
                print("✓ No external messages will be sent by this Milestone 1 implementation.")
        else:
            print(f"{APP_NAME}\n\nV1 Milestone 1: lead ingestion + SQLite foundation ready.\n\nExamples:\n  python lead_cli.py import data/leads.example.csv\n  python lead_cli.py leads\n  python lead_cli.py stats")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
