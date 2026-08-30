#!/usr/bin/env python3
"""AI Lead Outreach CLI — V1.

Local-first lead ingestion, deterministic qualification, and outreach foundation.
External messaging is intentionally disabled in this milestone.
"""
from __future__ import annotations
import argparse, csv, json, re, sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME="AI Lead Outreach CLI"
DEFAULT_DB="outreach.db"
DEFAULT_CONFIG="config.json"
DEFAULT_DAILY_LIMIT=10
REQUIRED_CSV_COLUMNS={"Company"}
ALLOWED_STATUSES={"NEW","QUALIFIED","DRAFTED","APPROVED","CONTACTED","REPLIED","INTERESTED","MEETING","WON","LOST","DO_NOT_CONTACT"}
PHONE_RE=re.compile(r"^\+?[0-9][0-9]{6,14}$")
EMAIL_RE=re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@dataclass
class Lead:
    company:str
    contact_name:str=""
    job_title:str=""
    phone:str=""
    email:str=""
    website:str=""
    industry:str=""
    country:str=""
    employees:str=""
    painpoint:str=""
    source:str=""

@dataclass(frozen=True)
class QualificationResult:
    score:int
    priority:str
    reasons:tuple[str,...]
    gaps:tuple[str,...]

def utc_now()->str:
    return datetime.now(timezone.utc).isoformat()

def load_config(path:str=DEFAULT_CONFIG)->dict[str,Any]:
    defaults={"ai":{"provider":"ollama","base_url":"http://localhost:11434","model":"qwen2.5:1.5b","timeout_seconds":60},"database":{"path":DEFAULT_DB},"outreach":{"daily_limit":DEFAULT_DAILY_LIMIT,"default_message_style":"professional","dry_run":True},"messaging":{"provider":"disabled"},"qualification":{"weights":{"decision_maker":20,"service_fit":20,"painpoint":20,"contactability":15,"company_fit":10,"digital_opportunity":10,"data_quality":5}}}
    p=Path(path)
    if not p.exists(): return defaults
    with p.open("r",encoding="utf-8") as f: loaded=json.load(f)
    for section,values in defaults.items():
        if isinstance(values,dict):
            loaded.setdefault(section,{})
            for key,value in values.items():
                if isinstance(value,dict):
                    loaded[section].setdefault(key,{})
                    for ck,cv in value.items(): loaded[section][key].setdefault(ck,cv)
                else: loaded[section].setdefault(key,value)
        else: loaded.setdefault(section,values)
    return loaded

def connect_db(path:str)->sqlite3.Connection:
    c=sqlite3.connect(path); c.row_factory=sqlite3.Row; c.execute("PRAGMA foreign_keys = ON"); initialize_db(c); return c

def initialize_db(connection:sqlite3.Connection)->None:
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, contact_name TEXT DEFAULT '', job_title TEXT DEFAULT '',
        phone TEXT DEFAULT '', email TEXT DEFAULT '', website TEXT DEFAULT '', industry TEXT DEFAULT '', country TEXT DEFAULT '',
        employees TEXT DEFAULT '', painpoint TEXT DEFAULT '', source TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'NEW',
        qualification_score INTEGER, qualification_priority TEXT, qualification_reasons TEXT DEFAULT '[]',
        qualification_gaps TEXT DEFAULT '[]', qualified_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_identity ON leads(company, phone, email);
    CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
    CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company);
    CREATE TABLE IF NOT EXISTS outreach (
        id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id INTEGER NOT NULL, message TEXT NOT NULL, original_message TEXT DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'whatsapp', status TEXT NOT NULL DEFAULT 'DRAFT', generated_at TEXT NOT NULL,
        approved_at TEXT, sent_at TEXT, error TEXT, FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_outreach_lead ON outreach(lead_id);
    CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
    CREATE TABLE IF NOT EXISTS daily_usage (usage_date TEXT PRIMARY KEY, messages_sent INTEGER NOT NULL DEFAULT 0);
    """)
    columns={row[1] for row in connection.execute("PRAGMA table_info(leads)").fetchall()}
    migrations={"qualification_score":"INTEGER","qualification_priority":"TEXT","qualification_reasons":"TEXT DEFAULT '[]'","qualification_gaps":"TEXT DEFAULT '[]'","qualified_at":"TEXT"}
    for column,definition in migrations.items():
        if column not in columns: connection.execute(f"ALTER TABLE leads ADD COLUMN {column} {definition}")
    # These indexes must be created only after the M1->M2 columns exist.
    connection.execute("CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(qualification_priority)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(qualification_score DESC)")
    connection.commit()

def normalize_text(value:str|None)->str: return " ".join((value or "").strip().split())
def normalize_phone(value:str|None)->str:
    value=normalize_text(value); return re.sub(r"[\s().-]","",value) if value else ""
def valid_phone(value:str)->bool: return bool(PHONE_RE.fullmatch(value))
def valid_email(value:str)->bool: return not value or bool(EMAIL_RE.fullmatch(value))

def validate_row(row:dict[str,str])->list[str]:
    errors=[]; company=normalize_text(row.get("Company")); phone=normalize_phone(row.get("Phone")); email=normalize_text(row.get("Email"))
    if not company: errors.append("missing company")
    if phone and not valid_phone(phone): errors.append("invalid phone")
    if email and not valid_email(email): errors.append("invalid email")
    if not phone and not email: errors.append("no phone or email")
    return errors

def row_to_lead(row:dict[str,str])->Lead:
    return Lead(company=normalize_text(row.get("Company")),contact_name=normalize_text(row.get("Contact Name")),job_title=normalize_text(row.get("Job Title")),phone=normalize_phone(row.get("Phone")),email=normalize_text(row.get("Email")),website=normalize_text(row.get("Website")),industry=normalize_text(row.get("Industry")),country=normalize_text(row.get("Country")),employees=normalize_text(row.get("Employees")),painpoint=normalize_text(row.get("Painpoint")),source=normalize_text(row.get("Source")))

def _employee_count(value:str)->int|None:
    value=normalize_text(value).lower().replace(",","")
    if not value:return None
    m=re.search(r"\d+",value); return int(m.group()) if m else None

def _is_decision_maker(title:str)->bool:
    title=title.lower(); return any(p in title for p in ("ceo","founder","co-founder","owner","president","managing director","director","partner","chief"))

def _service_fit(lead:Lead)->bool:
    text=f"{lead.industry} {lead.painpoint} {lead.website}".lower(); return any(k in text for k in ("website","web","ux","ui","mobile","automation","ai","lead","sales","software","ecommerce","shopify","digital"))

def _strong_painpoint(painpoint:str)->bool:
    text=painpoint.lower(); return len(text)>=25 and any(w in text for w in ("poor","missing","manual","slow","low","weak","problem","issue","abandon","outdated","lack","no "))

def qualify_lead(lead:Lead,weights:dict[str,int]|None=None)->QualificationResult:
    weights=weights or {"decision_maker":20,"service_fit":20,"painpoint":20,"contactability":15,"company_fit":10,"digital_opportunity":10,"data_quality":5}
    score=0; reasons=[]; gaps=[]
    if _is_decision_maker(lead.job_title): score+=weights["decision_maker"]; reasons.append("decision maker identified")
    elif lead.job_title: score+=weights["decision_maker"]//2; reasons.append("contact role identified")
    else: gaps.append("decision maker role unknown")
    if _service_fit(lead): score+=weights["service_fit"]; reasons.append("strong service fit")
    else: gaps.append("service fit unclear")
    if _strong_painpoint(lead.painpoint): score+=weights["painpoint"]; reasons.append("clear actionable painpoint")
    elif lead.painpoint: score+=weights["painpoint"]//2; reasons.append("painpoint supplied")
    else: gaps.append("painpoint missing")
    if lead.phone and lead.email: score+=weights["contactability"]; reasons.append("phone and email available")
    elif lead.phone or lead.email: score+=weights["contactability"]//2; reasons.append("one direct contact method available")
    else: gaps.append("no direct contact method")
    employees=_employee_count(lead.employees)
    if employees is not None and 2<=employees<=500: score+=weights["company_fit"]; reasons.append("target-sized company")
    elif employees is not None: score+=weights["company_fit"]//2; reasons.append("company size supplied")
    else: gaps.append("company size unknown")
    if lead.website and lead.painpoint: score+=weights["digital_opportunity"]; reasons.append("digital opportunity identified")
    elif lead.website: score+=weights["digital_opportunity"]//2; reasons.append("website available")
    else: gaps.append("website unknown")
    data_points=sum(bool(v) for v in (lead.company,lead.contact_name,lead.industry,lead.country,lead.source))
    if data_points>=4: score+=weights["data_quality"]; reasons.append("lead data is well populated")
    elif data_points>=2: score+=weights["data_quality"]//2; reasons.append("basic lead data supplied")
    else: gaps.append("lead data incomplete")
    score=min(max(score,0),100); priority="HIGH" if score>=80 else "MEDIUM" if score>=60 else "LOW" if score>=40 else "SKIP"
    return QualificationResult(score,priority,tuple(reasons),tuple(gaps))

def score_lead(lead:Lead)->tuple[int,list[str]]:
    r=qualify_lead(lead); return r.score,list(r.reasons)

def import_csv(csv_path:str,connection:sqlite3.Connection)->tuple[int,int,int]:
    imported=duplicates=invalid=0
    with Path(csv_path).open("r",encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle); columns={normalize_text(c) for c in (reader.fieldnames or [])}; missing=REQUIRED_CSV_COLUMNS-columns
        if missing: raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")
        for row in reader:
            row={(k or "").strip():(v or "") for k,v in row.items()}; errors=validate_row(row)
            if errors:
                invalid+=1; print(f"⚠ Invalid: {row.get('Company') or '<unknown>'} — {', '.join(errors)}"); continue
            lead=row_to_lead(row); now=utc_now()
            cursor=connection.execute("""INSERT OR IGNORE INTO leads
            (company,contact_name,job_title,phone,email,website,industry,country,employees,painpoint,source,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'NEW',?,?)""",(lead.company,lead.contact_name,lead.job_title,lead.phone,lead.email,lead.website,lead.industry,lead.country,lead.employees,lead.painpoint,lead.source,now,now))
            if cursor.rowcount==1: imported+=1
            else: duplicates+=1
    connection.commit(); return imported,duplicates,invalid

def qualify_all(connection:sqlite3.Connection,config:dict[str,Any])->int:
    weights=config.get("qualification",{}).get("weights",{}); rows=connection.execute("SELECT * FROM leads ORDER BY id").fetchall()
    for row in rows:
        lead=Lead(company=row["company"],contact_name=row["contact_name"],job_title=row["job_title"],phone=row["phone"],email=row["email"],website=row["website"],industry=row["industry"],country=row["country"],employees=row["employees"],painpoint=row["painpoint"],source=row["source"])
        result=qualify_lead(lead,weights); now=utc_now(); status="QUALIFIED" if result.priority in {"HIGH","MEDIUM"} else row["status"]
        connection.execute("""UPDATE leads SET qualification_score=?,qualification_priority=?,qualification_reasons=?,qualification_gaps=?,qualified_at=?,status=?,updated_at=? WHERE id=?""",(result.score,result.priority,json.dumps(result.reasons),json.dumps(result.gaps),now,status,now,row["id"]))
    connection.commit(); return len(rows)

def show_qualified(connection:sqlite3.Connection,priority:str|None=None)->None:
    query="SELECT id,company,contact_name,qualification_score,qualification_priority,status FROM leads"; params=()
    if priority: query+=" WHERE qualification_priority=?"; params=(priority.upper(),)
    query+=" ORDER BY COALESCE(qualification_score,-1) DESC,id"; rows=connection.execute(query,params).fetchall()
    if not rows: print("No qualified leads found. Run: python3 lead_cli.py qualify"); return
    print(f"\n{'RANK':<6} {'COMPANY':<28} {'SCORE':<7} {'PRIORITY':<10} {'STATUS'}\n"+"-"*75)
    for rank,row in enumerate(rows,1): print(f"{rank:<6} {row['company'][:27]:<28} {str(row['qualification_score'] or 0):<7} {row['qualification_priority'] or 'UNRATED':<10} {row['status']}")
    print()
    for row in rows:
        reasons=json.loads(row["qualification_reasons"] or "[]"); gaps=json.loads(row["qualification_gaps"] or "[]")
        print(f"#{row['id']} {row['company']} — {row['qualification_score']}/100 ({row['qualification_priority']})")
        if reasons: print("  Why: "+"; ".join(reasons))
        if gaps: print("  Gaps: "+"; ".join(gaps))

def show_leads(connection:sqlite3.Connection,status:str|None=None)->None:
    if status and status not in ALLOWED_STATUSES: raise ValueError(f"Unknown status: {status}")
    rows=connection.execute("SELECT id,company,contact_name,phone,email,status FROM leads"+(" WHERE status=?" if status else "")+" ORDER BY id",(status,) if status else ()).fetchall()
    if not rows: print("No leads found."); return
    print(f"\n{'ID':<5} {'Company':<28} {'Contact':<20} {'Phone':<17} {'Status}\n"+"-"*90)
    for row in rows: print(f"{row['id']:<5} {row['company'][:27]:<28} {row['contact_name'][:19]:<20} {row['phone'][:16]:<17} {row['status']}")

def show_stats(connection:sqlite3.Connection,daily_limit:int=DEFAULT_DAILY_LIMIT)->None:
    lead_count=connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]; status_rows=connection.execute("SELECT status,COUNT(*) AS count FROM leads GROUP BY status ORDER BY status").fetchall(); outreach_counts=connection.execute("SELECT status,COUNT(*) AS count FROM outreach GROUP BY status").fetchall(); today=datetime.now(timezone.utc).date().isoformat(); usage=connection.execute("SELECT messages_sent FROM daily_usage WHERE usage_date=?",(today,)).fetchone(); today_sent=usage[0] if usage else 0
    print(f"\n{APP_NAME}\n{'='*len(APP_NAME)}\nTotal leads:       {lead_count}")
    for row in status_rows: print(f"{row['status']+':':<20}{row['count']}")
    print("\nOutreach")
    for row in outreach_counts: print(f"{row['status']+':':<20}{row['count']}")
    print(f"\nSent today:        {today_sent}/{daily_limit}")

def main()->None:
    parser=argparse.ArgumentParser(description=APP_NAME); parser.add_argument("command",nargs="?",choices=["import","leads","stats","qualify","analyze","review","send","run"]); parser.add_argument("path",nargs="?"); parser.add_argument("--status",choices=sorted(ALLOWED_STATUSES)); parser.add_argument("--priority",choices=["high","medium","low","skip"]); parser.add_argument("--dry-run",action="store_true"); parser.add_argument("--config",default=DEFAULT_CONFIG); args=parser.parse_args(); config=load_config(args.config); db_path=config.get("database",{}).get("path",DEFAULT_DB); daily_limit=int(config.get("outreach",{}).get("daily_limit",DEFAULT_DAILY_LIMIT)); connection=connect_db(db_path)
    try:
        if args.command=="import":
            if not args.path: parser.error("import requires a CSV path")
            imported,duplicates,invalid=import_csv(args.path,connection); print(f"\nImport complete\n{'-'*30}\nImported:    {imported}\nDuplicates:  {duplicates}\nInvalid:     {invalid}")
        elif args.command=="leads": show_leads(connection,args.status)
        elif args.command=="stats": show_stats(connection,daily_limit)
        elif args.command=="qualify":
            count=qualify_all(connection,config); print(f"\nQualification complete: {count} lead(s) scored."); show_qualified(connection,args.priority)
        elif args.command in {"analyze","review","send","run"}: print(f"{args.command} workflow is scheduled for a later milestone.\n✓ No external messages will be sent by the current implementation.")
        else: print(f"{APP_NAME}\n\nV1: lead ingestion + SQLite + deterministic qualification.\n\nExamples:\n  python lead_cli.py import data/leads.example.csv\n  python lead_cli.py leads\n  python lead_cli.py qualify\n  python lead_cli.py qualify --priority high\n  python lead_cli.py stats")
    finally: connection.close()

if __name__=="__main__": main()
