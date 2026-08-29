#!/usr/bin/env python3
"""AI Lead Outreach CLI — V1 foundation.

Single-script, local-first outreach workflow.

V1 defaults to dry-run and human approval. Real messaging providers are
intentionally not implemented in this foundation commit.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME = "AI Lead Outreach CLI"
DEFAULT_DB = "outreach.db"
DEFAULT_CONFIG = "config.json"
DEFAULT_DAILY_LIMIT = 10

REQUIRED_CSV_COLUMNS = {"Company"}
PHONE_RE = re.compile(r"^\+?[0-9][0-9 .()\-]{6,}$")
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
        "ai": {
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5:1.5b",
            "timeout_seconds": 60,
        },
        "database": {"path": DEFAULT_DB},
        "outreach": {
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "default_message_style": "professional",
            "dry_run": True,
        },
        "messaging": {"provider": "disabled"},
    }
    config_path = Path(path)
    if not config_path.exists():
        return defaults
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    for section, values in defaults.items():
        if isinstance(values, dict):
            loaded.setdefault(section, {}).update(
                {k: v for k, v in values.items() if k not in loaded.get(section, {})}
            )
        else:
            loaded.setdefault(section, values)
    return loaded


def connect_db(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
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
            updated_at TEXT NOT NULL,
            UNIQUE(company, phone, email)
        );

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
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );

        CREATE TABLE IF NOT EXISTS daily_usage (
            usage_date TEXT PRIMARY KEY,
            messages_sent INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    connection.commit()


def normalize_phone(value: str) -> str:
    return re.sub(r"[\s().-]", "", value.strip())


def valid_phone(value: str) -> bool:
    return bool(PHONE_RE.fullmatch(value))


def valid_email(value: str) -> bool:
    return not value or bool(EMAIL_RE.fullmatch(value.strip()))


def validate_row(row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    company = (row.get("Company") or "").strip()
    phone = normalize_phone(row.get("Phone") or "")
    email = (row.get("Email") or "").strip()
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
        company=(row.get("Company") or "").strip(),
        contact_name=(row.get("Contact Name") or "").strip(),
        job_title=(row.get("Job Title") or "").strip(),
        phone=normalize_phone(row.get("Phone") or ""),
        email=(row.get("Email") or "").strip(),
        website=(row.get("Website") or "").strip(),
        industry=(row.get("Industry") or "").strip(),
        country=(row.get("Country") or "").strip(),
        employees=(row.get("Employees") or "").strip(),
        painpoint=(row.get("Painpoint") or "").strip(),
        source=(row.get("Source") or "").strip(),
    )


def score_lead(lead: Lead) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if lead.phone:
        score += 20
        reasons.append("phone available")
    if lead.email:
        score += 15
        reasons.append("email available")
    if lead.job_title:
        score += 20
        reasons.append("contact role available")
    if lead.website:
        score += 15
        reasons.append("website available")
    if lead.painpoint:
        score += 15
        reasons.append("painpoint supplied")
    if lead.industry:
        score += 5
        reasons.append("industry supplied")
    if lead.employees:
        score += 5
        reasons.append("company size supplied")
    if lead.company:
        score += 5
        reasons.append("company identified")
    return min(score, 100), reasons


def import_csv(csv_path: str, connection: sqlite3.Connection) -> tuple[int, int]:
    imported = 0
    skipped = 0
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or [])
        missing = REQUIRED_CSV_COLUMNS - columns
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            errors = validate_row(row)
            if errors:
                skipped += 1
                print(f"⚠ Skipped {row.get('Company') or '<unknown>'}: {', '.join(errors)}")
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
                (
                    lead.company, lead.contact_name, lead.job_title, lead.phone,
                    lead.email, lead.website, lead.industry, lead.country,
                    lead.employees, lead.painpoint, lead.source, now, now,
                ),
            )
            if cursor.rowcount:
                imported += 1
            else:
                skipped += 1
    connection.commit()
    return imported, skipped


def show_stats(connection: sqlite3.Connection) -> None:
    lead_count = connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    draft_count = connection.execute("SELECT COUNT(*) FROM outreach WHERE status='DRAFT'").fetchone()[0]
    approved_count = connection.execute("SELECT COUNT(*) FROM outreach WHERE status='APPROVED'").fetchone()[0]
    sent_count = connection.execute("SELECT COUNT(*) FROM outreach WHERE status='SENT'").fetchone()[0]
    failed_count = connection.execute("SELECT COUNT(*) FROM outreach WHERE status='FAILED'").fetchone()[0]
    today = date.today().isoformat()
    today_sent = connection.execute(
        "SELECT COALESCE(messages_sent, 0) FROM daily_usage WHERE usage_date=?", (today,)
    ).fetchone()[0]
    print(f"\n{APP_NAME}\n")
    print(f"Leads:             {lead_count}")
    print(f"Drafts:            {draft_count}")
    print(f"Approved:          {approved_count}")
    print(f"Sent:              {sent_count}")
    print(f"Failed:            {failed_count}")
    print(f"Sent today:        {today_sent}/{DEFAULT_DAILY_LIMIT}")


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("command", nargs="?", choices=["import", "analyze", "review", "stats", "send", "run"])
    parser.add_argument("path", nargs="?", help="CSV path for import")
    parser.add_argument("--dry-run", action="store_true", help="Never send external messages")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Configuration file")
    args = parser.parse_args()

    config = load_config(args.config)
    db_path = config.get("database", {}).get("path", DEFAULT_DB)
    connection = connect_db(db_path)

    try:
        if args.command == "import":
            if not args.path:
                parser.error("import requires a CSV path")
            imported, skipped = import_csv(args.path, connection)
            print(f"✓ Imported: {imported}")
            print(f"⚠ Skipped/duplicate: {skipped}")
        elif args.command == "stats":
            show_stats(connection)
        elif args.command in {"analyze", "review", "send", "run"}:
            print(f"{args.command} workflow is scaffolded for the next implementation milestone.")
            if args.command == "run" and args.dry_run:
                print("✓ Dry-run enforced: no external delivery will occur.")
        else:
            print(f"{APP_NAME}\n")
            print("V1 foundation ready.")
            print("Use: python lead_cli.py import data/leads.csv")
            print("     python lead_cli.py stats")
            print("     python lead_cli.py run --dry-run")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
