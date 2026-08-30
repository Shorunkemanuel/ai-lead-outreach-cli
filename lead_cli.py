#!/usr/bin/env python3
"""AI Lead Outreach CLI — V1 milestones 1-3."""
from __future__ import annotations
import argparse,csv,json,re,sqlite3,urllib.request,urllib.error
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from typing import Any

APP_NAME="AI Lead Outreach CLI"
DEFAULT_DB="outreach.db"
DEFAULT_CONFIG="config.json"
DEFAULT_DAILY_LIMIT=10
DEFAULT_OLLAMA_URL="http://localhost:11434/api/generate"
DEFAULT_AI_MODEL="qwen2.5:0.5b-instruct-q4_K_M"
ALLOWED_STATUSES={"NEW","QUALIFIED","DRAFTED","APPROVED","CONTACTED","REPLIED","INTERESTED","MEETING","WON","LOST","DO_NOT_CONTACT"}
DRAFT_STATUSES={"GENERATED","APPROVED","REJECTED"}
PHONE_RE=re.compile(r"^\+?[0-9][0-9]{6,14}$")
EMAIL_RE=re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLACEHOLDER_RE=re.compile(r"(?:\{[^{}]+\}|\[[^\[\]]+\]|<[^<>]+>)")

@dataclass
class Lead:
    company:str; contact_name:str=""; job_title:str=""; phone:str=""; email:str=""; website:str=""; industry:str=""; country:str=""; employees:str=""; painpoint:str=""; source:str=""

@dataclass(frozen=True)
class QualificationResult:
    score:int; priority:str; reasons:tuple[str,...]; gaps:tuple[str,...]

def utc_now(): return datetime.now(timezone.utc).isoformat()

def load_config(path=DEFAULT_CONFIG):
    defaults={"database":{"path":DEFAULT_DB},"outreach":{"daily_limit":10,"dry_run":True},"messaging":{"provider":"disabled"},"ai":{"ollama_url":DEFAULT_OLLAMA_URL,"model":DEFAULT_AI_MODEL,"timeout":60},"qualification":{"weights":{"decision_maker":20,"service_fit":20,"painpoint":20,"contactability":15,"company_fit":10,"digital_opportunity":10,"data_quality":5}}}
    p=Path(path)
    if not p.exists(): return defaults
    with p.open(encoding="utf-8") as f: loaded=json.load(f)
    for section,vals in defaults.items():
        loaded.setdefault(section,{})
        for key,val in vals.items():
            if isinstance(val,dict):
                loaded[section].setdefault(key,{})
                for k,v in val.items(): loaded[section][key].setdefault(k,v)
            else: loaded[section].setdefault(key,val)
    return loaded

def connect_db(path):
    c=sqlite3.connect(path);c.row_factory=sqlite3.Row;c.execute("PRAGMA foreign_keys=ON");initialize_db(c);return c

def initialize_db(c):
    c.executescript("""CREATE TABLE IF NOT EXISTS leads(id INTEGER PRIMARY KEY AUTOINCREMENT,company TEXT NOT NULL,contact_name TEXT DEFAULT '',job_title TEXT DEFAULT '',phone TEXT DEFAULT '',email TEXT DEFAULT '',website TEXT DEFAULT '',industry TEXT DEFAULT '',country TEXT DEFAULT '',employees TEXT DEFAULT '',painpoint TEXT DEFAULT '',source TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'NEW',qualification_score INTEGER,qualification_priority TEXT,qualification_reasons TEXT DEFAULT '[]',qualification_gaps TEXT DEFAULT '[]',qualified_at TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_identity ON leads(company,phone,email); CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status); CREATE INDEX IF NOT EXISTS idx_leads_company ON leads(company); CREATE TABLE IF NOT EXISTS outreach(id INTEGER PRIMARY KEY AUTOINCREMENT,lead_id INTEGER NOT NULL,message TEXT NOT NULL,original_message TEXT DEFAULT '',channel TEXT NOT NULL DEFAULT 'whatsapp',status TEXT NOT NULL DEFAULT 'DRAFT',generated_at TEXT NOT NULL,approved_at TEXT,sent_at TEXT,error TEXT,FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE); CREATE TABLE IF NOT EXISTS daily_usage(usage_date TEXT PRIMARY KEY,messages_sent INTEGER NOT NULL DEFAULT 0); CREATE TABLE IF NOT EXISTS outreach_drafts(id INTEGER PRIMARY KEY AUTOINCREMENT,lead_id INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'GENERATED',message TEXT NOT NULL,model TEXT NOT NULL,prompt TEXT NOT NULL,validation_error TEXT DEFAULT '',created_at TEXT NOT NULL,reviewed_at TEXT,FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE);""")
    cols={r[1] for r in c.execute("PRAGMA table_info(leads)")};migrations={"qualification_score":"INTEGER","qualification_priority":"TEXT","qualification_reasons":"TEXT DEFAULT '[]'","qualification_gaps":"TEXT DEFAULT '[]'","qualified_at":"TEXT"}
    for col,definition in migrations.items():
        if col not in cols:c.execute(f"ALTER TABLE leads ADD COLUMN {col} {definition}")
    c.execute("CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads(qualification_priority)");c.execute("CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(qualification_score DESC)");c.execute("CREATE INDEX IF NOT EXISTS idx_drafts_lead ON outreach_drafts(lead_id)");c.execute("CREATE INDEX IF NOT EXISTS idx_drafts_status ON outreach_drafts(status)");c.commit()

def normalize_text(v): return " ".join((v or "").strip().split())
def normalize_phone(v): return re.sub(r"[\s().-]","",normalize_text(v))
def valid_phone(v): return bool(PHONE_RE.fullmatch(v))
def valid_email(v): return not v or bool(EMAIL_RE.fullmatch(v))

def validate_row(row):
    e=[];company=normalize_text(row.get("Company"));phone=normalize_phone(row.get("Phone"));email=normalize_text(row.get("Email"))
    if not company:e.append("missing company")
    if phone and not valid_phone(phone):e.append("invalid phone")
    if email and not valid_email(email):e.append("invalid email")
    if not phone and not email:e.append("no phone or email")
    return e

def row_to_lead(row): return Lead(company=normalize_text(row.get("Company")),contact_name=normalize_text(row.get("Contact Name")),job_title=normalize_text(row.get("Job Title")),phone=normalize_phone(row.get("Phone")),email=normalize_text(row.get("Email")),website=normalize_text(row.get("Website")),industry=normalize_text(row.get("Industry")),country=normalize_text(row.get("Country")),employees=normalize_text(row.get("Employees")),painpoint=normalize_text(row.get("Painpoint")),source=normalize_text(row.get("Source")))
def _employee_count(v):
    m=re.search(r"\d+",normalize_text(v).lower().replace(",",""));return int(m.group()) if m else None
def _is_decision_maker(t): return any(p in t.lower() for p in ("ceo","founder","co-founder","owner","president","managing director","director","partner","chief"))
def _service_fit(l): return any(k in f"{l.industry} {l.painpoint} {l.website}".lower() for k in ("website","web","ux","ui","mobile","automation","ai","lead","sales","software","ecommerce","shopify","digital"))
def _strong_painpoint(p): return len(p.lower())>=25 and any(w in p.lower() for w in ("poor","missing","manual","slow","low","weak","problem","issue","abandon","outdated","lack","no "))

def qualify_lead(l,weights=None):
    w=weights or {"decision_maker":20,"service_fit":20,"painpoint":20,"contactability":15,"company_fit":10,"digital_opportunity":10,"data_quality":5};s=0;reasons=[];gaps=[]
    if _is_decision_maker(l.job_title):s+=w["decision_maker"];reasons.append("decision maker identified")
    elif l.job_title:s+=w["decision_maker"]//2;reasons.append("contact role identified")
    else:gaps.append("decision maker role unknown")
    if _service_fit(l):s+=w["service_fit"];reasons.append("strong service fit")
    else:gaps.append("service fit unclear")
    if _strong_painpoint(l.painpoint):s+=w["painpoint"];reasons.append("clear actionable painpoint")
    elif l.painpoint:s+=w["painpoint"]//2;reasons.append("painpoint supplied")
    else:gaps.append("painpoint missing")
    if l.phone and l.email:s+=w["contactability"];reasons.extend(["phone available","email available"])
    elif l.phone:s+=w["contactability"]//2;reasons.append("phone available")
    elif l.email:s+=w["contactability"]//2;reasons.append("email available")
    else:gaps.append("no direct contact method")
    n=_employee_count(l.employees)
    if n is not None and 2<=n<=500:s+=w["company_fit"];reasons.append("target-sized company")
    elif n is not None:s+=w["company_fit"]//2;reasons.append("company size supplied")
    else:gaps.append("company size unknown")
    if l.website and l.painpoint:s+=w["digital_opportunity"];reasons.append("digital opportunity identified")
    elif l.website:s+=w["digital_opportunity"]//2;reasons.append("website available")
    else:gaps.append("website unknown")
    points=sum(bool(v) for v in (l.company,l.contact_name,l.industry,l.country,l.source))
    if points>=4:s+=w["data_quality"];reasons.append("lead data is well populated")
    elif points>=2:s+=w["data_quality"]//2;reasons.append("basic lead data supplied")
    else:gaps.append("lead data incomplete")
    s=min(max(s,0),100);p="HIGH" if s>=80 else "MEDIUM" if s>=60 else "LOW" if s>=40 else "SKIP";return QualificationResult(s,p,tuple(reasons),tuple(gaps))

def score_lead(l): r=qualify_lead(l);return r.score,list(r.reasons)

def import_csv(path,c):
    imported=duplicates=invalid=0
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f);cols={normalize_text(x) for x in (reader.fieldnames or [])}
        if "Company" not in cols:raise ValueError("Missing required CSV columns: Company")
        for row in reader:
            row={(k or "").strip():(v or "") for k,v in row.items()};errors=validate_row(row)
            if errors:invalid+=1;print(f"⚠ Invalid: {row.get('Company') or '<unknown>'} — {', '.join(errors)}");continue
            l=row_to_lead(row);now=utc_now();cur=c.execute("INSERT OR IGNORE INTO leads(company,contact_name,job_title,phone,email,website,industry,country,employees,painpoint,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,'NEW',?,?)",(l.company,l.contact_name,l.job_title,l.phone,l.email,l.website,l.industry,l.country,l.employees,l.painpoint,l.source,now,now));imported+=cur.rowcount==1;duplicates+=cur.rowcount!=1
    c.commit();return imported,duplicates,invalid

def qualify_all(c,config):
    w=config.get("qualification",{}).get("weights",{});rows=c.execute("SELECT * FROM leads ORDER BY id").fetchall()
    for r in rows:
        l=Lead(r["company"],r["contact_name"],r["job_title"],r["phone"],r["email"],r["website"],r["industry"],r["country"],r["employees"],r["painpoint"],r["source"]);q=qualify_lead(l,w);now=utc_now();status="QUALIFIED" if q.priority in {"HIGH","MEDIUM"} else r["status"]
        c.execute("UPDATE leads SET qualification_score=?,qualification_priority=?,qualification_reasons=?,qualification_gaps=?,qualified_at=?,status=?,updated_at=? WHERE id=?",(q.score,q.priority,json.dumps(q.reasons),json.dumps(q.gaps),now,status,now,r["id"]))
    c.commit();return len(rows)

def show_qualified(c,priority=None):
    q="SELECT id,company,contact_name,qualification_score,qualification_priority,status,qualification_reasons,qualification_gaps FROM leads";params=()
    if priority:q+=" WHERE qualification_priority=?";params=(priority.upper(),)
    rows=c.execute(q+" ORDER BY COALESCE(qualification_score,-1) DESC,id",params).fetchall()
    if not rows:print("No qualified leads found. Run: python3 lead_cli.py qualify");return
    print(f"\n{'RANK':<6} {'COMPANY':<28} {'SCORE':<7} {'PRIORITY':<10} STATUS\n"+"-"*75)
    for rank,r in enumerate(rows,1):print(f"{rank:<6} {r['company'][:27]:<28} {str(r['qualification_score'] or 0):<7} {r['qualification_priority'] or 'UNRATED':<10} {r['status']}")
    for r in rows:
        print(f"#{r['id']} {r['company']} — {r['qualification_score']}/100 ({r['qualification_priority']})");reasons=json.loads(r["qualification_reasons"] or "[]");gaps=json.loads(r["qualification_gaps"] or "[]")
        if reasons:print("  Why: "+"; ".join(reasons))
        if gaps:print("  Gaps: "+"; ".join(gaps))

def show_leads(c,status=None):
    if status and status not in ALLOWED_STATUSES:raise ValueError(f"Unknown status: {status}")
    rows=c.execute("SELECT id,company,contact_name,phone,email,status FROM leads"+(" WHERE status=?" if status else "")+" ORDER BY id",(status,) if status else ()).fetchall()
    if not rows:print("No leads found.");return
    print(f"\n{'ID':<5} {'Company':<28} {'Contact':<20} {'Phone':<17} Status\n"+"-"*90)
    for r in rows:print(f"{r['id']:<5} {r['company'][:27]:<28} {r['contact_name'][:19]:<20} {r['phone'][:16]:<17} {r['status']}")

def show_stats(c,limit=10):
    total=c.execute("SELECT COUNT(*) FROM leads").fetchone()[0];statuses=c.execute("SELECT status,COUNT(*) count FROM leads GROUP BY status ORDER BY status").fetchall();today=datetime.now(timezone.utc).date().isoformat();u=c.execute("SELECT messages_sent FROM daily_usage WHERE usage_date=?",(today,)).fetchone();sent=u[0] if u else 0
    print(f"\n{APP_NAME}\n{'='*len(APP_NAME)}\nTotal leads:       {total}");[print(f"{r['status']+':':<20}{r['count']}") for r in statuses];print(f"\nOutreach\n\nSent today:        {sent}/{limit}")

def lead_from_row(r): return Lead(r["company"],r["contact_name"],r["job_title"],r["phone"],r["email"],r["website"],r["industry"],r["country"],r["employees"],r["painpoint"],r["source"])

def build_prompt(l,q):
    return f"""You write concise, respectful B2B outreach for a UX, web design, lead generation and AI automation consultant.\nLead company: {l.company}\nContact: {l.contact_name or 'the decision maker'}\nRole: {l.job_title or 'unknown'}\nIndustry: {l.industry or 'unknown'}\nPain point: {l.painpoint or 'not supplied'}\nWebsite: {l.website or 'not supplied'}\nQualification score: {q.score}/100 ({q.priority})\nQualification reasons: {', '.join(q.reasons) or 'none'}\nQualification gaps: {', '.join(q.gaps) or 'none'}\n\nWrite exactly 2 or 3 sentences. Mention the specific business problem, briefly state a relevant solution, and finish with a low-pressure call to action. Do not invent facts. Do not use placeholders, greetings, filler, hype, or claims of guaranteed results. Return only the message."""

def call_ollama(prompt,model=DEFAULT_AI_MODEL,ollama_url=DEFAULT_OLLAMA_URL,timeout=60):
    payload=json.dumps({"model":model,"prompt":prompt,"stream":False}).encode("utf-8");req=urllib.request.Request(ollama_url,data=payload,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:data=json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError) as exc:raise RuntimeError(f"Ollama unavailable: {exc}") from exc
    text=normalize_text(data.get("response",""))
    if not text:raise RuntimeError("Ollama returned an empty response")
    return text

def validate_draft(text):
    text=normalize_text(text)
    if not text:return False,"empty message"
    if PLACEHOLDER_RE.search(text):return False,"unresolved placeholder"
    sentences=[x for x in re.split(r"(?<=[.!?])\s+",text) if x.strip()]
    if len(sentences)>3:return False,"more than 3 sentences"
    if len(sentences)<2:return False,"fewer than 2 sentences"
    return True,""

def generate_draft(c,lead_id,config):
    row=c.execute("SELECT * FROM leads WHERE id=?",(lead_id,)).fetchone()
    if not row:raise ValueError(f"Lead {lead_id} not found")
    if row["qualification_priority"] not in {"HIGH","MEDIUM"} and row["status"]!="QUALIFIED":raise ValueError("Lead must be qualified before generating a draft")
    q=QualificationResult(int(row["qualification_score"] or 0),row["qualification_priority"] or "SKIP",tuple(json.loads(row["qualification_reasons"] or "[]")),tuple(json.loads(row["qualification_gaps"] or "[]")))
    l=lead_from_row(row);ai=config.get("ai",{});model=ai.get("model",DEFAULT_AI_MODEL);url=ai.get("ollama_url",DEFAULT_OLLAMA_URL);timeout=int(ai.get("timeout",60));prompt=build_prompt(l,q);message=call_ollama(prompt,model,url,timeout);valid,reason=validate_draft(message)
    if not valid:raise ValueError(f"Invalid AI draft: {reason}")
    now=utc_now();cur=c.execute("INSERT INTO outreach_drafts(lead_id,status,message,model,prompt,validation_error,created_at) VALUES(?,?,?, ?,?, '',?)",(lead_id,"GENERATED",message,model,prompt,now));c.execute("UPDATE leads SET status='DRAFTED',updated_at=? WHERE id=? AND status IN ('QUALIFIED','DRAFTED')",(now,lead_id));c.commit();return cur.lastrowid

def review_draft(c,draft_id,status):
    status=status.upper()
    if status not in {"APPROVED","REJECTED"}:raise ValueError("Review status must be APPROVED or REJECTED")
    row=c.execute("SELECT id,status FROM outreach_drafts WHERE id=?",(draft_id,)).fetchone()
    if not row:raise ValueError(f"Draft {draft_id} not found")
    if row["status"]!="GENERATED":raise ValueError("Only GENERATED drafts can be reviewed")
    now=utc_now();c.execute("UPDATE outreach_drafts SET status=?,reviewed_at=? WHERE id=?",(status,now,draft_id));c.commit()

def show_drafts(c,status=None):
    q="SELECT d.id,d.lead_id,l.company,l.contact_name,d.status,d.model,d.message,d.created_at FROM outreach_drafts d JOIN leads l ON l.id=d.lead_id";params=()
    if status:q+=" WHERE d.status=?";params=(status.upper(),)
    rows=c.execute(q+" ORDER BY d.id DESC",params).fetchall()
    if not rows:print("No outreach drafts found.");return
    print(f"\n{'ID':<5} {'COMPANY':<28} {'STATUS':<10} MODEL\n"+"-"*80)
    for r in rows:print(f"{r['id']:<5} {r['company'][:27]:<28} {r['status']:<10} {r['model']}")

def show_draft(c,draft_id):
    r=c.execute("SELECT d.*,l.company,l.contact_name,l.job_title FROM outreach_drafts d JOIN leads l ON l.id=d.lead_id WHERE d.id=?",(draft_id,)).fetchone()
    if not r:raise ValueError(f"Draft {draft_id} not found")
    print(f"\nDraft #{r['id']} — {r['company']}")
    print(f"Contact: {r['contact_name'] or 'Unknown'} | Status: {r['status']} | Model: {r['model']}")
    print("\nMessage:\n---\n"+r["message"]+"\n---")

def main():
    p=argparse.ArgumentParser(description=APP_NAME);p.add_argument("command",nargs="?",choices=["import","leads","stats","qualify","generate","drafts","draft","approve","reject","analyze","review","send","run"]);p.add_argument("path",nargs="?");p.add_argument("--status",choices=sorted(ALLOWED_STATUSES|DRAFT_STATUSES));p.add_argument("--priority",choices=["high","medium","low","skip"]);p.add_argument("--config",default=DEFAULT_CONFIG);a=p.parse_args();cfg=load_config(a.config);c=connect_db(cfg.get("database",{}).get("path",DEFAULT_DB))
    try:
        if a.command=="import":
            if not a.path:p.error("import requires a CSV path")
            x,y,z=import_csv(a.path,c);print(f"\nImport complete\n{'-'*30}\nImported:    {x}\nDuplicates:  {y}\nInvalid:     {z}")
        elif a.command=="leads":show_leads(c,a.status if a.status in ALLOWED_STATUSES else None)
        elif a.command=="stats":show_stats(c,int(cfg.get("outreach",{}).get("daily_limit",10)))
        elif a.command=="qualify":n=qualify_all(c,cfg);print(f"\nQualification complete: {n} lead(s) scored.");show_qualified(c,a.priority)
        elif a.command=="generate":
            priority=a.priority.upper() if a.priority else None;q="SELECT id,company FROM leads WHERE qualification_priority IN ('HIGH','MEDIUM')";params=()
            if priority:q+=" AND qualification_priority=?";params=(priority,)
            rows=c.execute(q+" ORDER BY qualification_score DESC,id",params).fetchall();generated=0
            for r in rows:
                try:did=generate_draft(c,r["id"],cfg);generated+=1;print(f"✓ Draft #{did} generated for {r['company']}")
                except (RuntimeError,ValueError) as exc:print(f"⚠ {r['company']}: {exc}")
            print(f"\nGenerated: {generated}")
        elif a.command=="drafts":show_drafts(c,a.status if a.status in DRAFT_STATUSES else None)
        elif a.command=="draft":
            if not a.path:p.error("draft requires an ID")
            show_draft(c,int(a.path))
        elif a.command in {"approve","reject"}:
            if not a.path:p.error(f"{a.command} requires an ID")
            review_draft(c,int(a.path),"APPROVED" if a.command=="approve" else "REJECTED");print(f"✓ Draft #{a.path} marked {('APPROVED' if a.command=='approve' else 'REJECTED')}. No message was sent.")
        elif a.command in {"analyze","review","send","run"}:print(f"{a.command} workflow is scheduled for a later milestone.\n✓ No external messages will be sent by the current implementation.")
        else:print(f"{APP_NAME}\n\nV1: lead ingestion + SQLite + deterministic qualification + local AI drafts.\n\nExamples:\n  python3 lead_cli.py import data/leads.example.csv\n  python3 lead_cli.py qualify\n  python3 lead_cli.py generate\n  python3 lead_cli.py drafts\n  python3 lead_cli.py draft 1\n  python3 lead_cli.py approve 1\n  python3 lead_cli.py stats")
    finally:c.close()
if __name__=="__main__":main()
