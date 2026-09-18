import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pypdf import PdfReader

from .ai import API_KEY, MODEL, analyze_cases_batch, chat_answer

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "operations.db"

app = FastAPI(title="AI Operations Automation Hub API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT UNIQUE,
            customer TEXT,
            issue TEXT,
            category TEXT DEFAULT '',
            priority TEXT DEFAULT '',
            status TEXT DEFAULT 'Unresolved',
            created_at TEXT,
            summary TEXT DEFAULT '',
            recommendation TEXT DEFAULT '',
            email_draft TEXT DEFAULT ''
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content TEXT,
            created_at TEXT
        )""")


init_db()


def norm(v):
    if pd.isna(v):
        return ""
    return str(v).strip()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        key = str(col).strip().lower().replace(" ", "_").replace("-", "_")
        mapping[col] = key
    df = df.rename(columns=mapping)

    aliases = {
        "case": "case_id",
        "caseid": "case_id",
        "customer_name": "customer",
        "client": "customer",
        "problem": "issue",
        "description": "issue",
        "resolution_status": "status",
        "created": "date",
    }
    df = df.rename(columns={k: v for k, v in aliases.items() if k in df.columns})
    return df


def read_structured(content: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    from io import BytesIO
    if suffix == ".csv":
        try:
            return pd.read_csv(BytesIO(content))
        except UnicodeDecodeError:
            return pd.read_csv(BytesIO(content), encoding="latin-1")
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(BytesIO(content))
    raise ValueError("Unsupported structured file")


def df_to_cases(df: pd.DataFrame) -> list[dict]:
    df = normalize_columns(df)
    if "issue" not in df.columns:
        raise ValueError("Your file needs an 'issue' or 'description' column.")
    if "customer" not in df.columns:
        df["customer"] = "Unknown customer"
    if "case_id" not in df.columns:
        df["case_id"] = [f"CASE-{i:03d}" for i in range(1, len(df) + 1)]
    if "status" not in df.columns:
        df["status"] = "Unresolved"
    for col in ["category", "priority"]:
        if col not in df.columns:
            df[col] = ""

    result = []
    for _, row in df.iterrows():
        issue = norm(row.get("issue"))
        if not issue:
            continue
        result.append({
            "case_id": norm(row.get("case_id")),
            "customer": norm(row.get("customer")) or "Unknown customer",
            "issue": issue,
            "category": norm(row.get("category")),
            "priority": norm(row.get("priority")),
            "status": norm(row.get("status")) or "Unresolved",
        })
    return result


def upsert_cases(cases: list[dict]):
    now = datetime.now().isoformat()
    with conn() as c:
        for case in cases:
            c.execute("""INSERT INTO cases(case_id,customer,issue,category,priority,status,created_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(case_id) DO UPDATE SET
                customer=excluded.customer, issue=excluded.issue,
                category=excluded.category, priority=excluded.priority,
                status=excluded.status""", (
                case["case_id"], case["customer"], case["issue"],
                case.get("category", ""), case.get("priority", ""), case.get("status", "Unresolved"), now
            ))


def get_cases() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM cases ORDER BY id DESC").fetchall()]


def update_ai_results(results: list[dict]):
    with conn() as c:
        for x in results:
            case_id = x["case_id"]
            rec = x["recommendation"]
            email = (
                f"Subject: Follow-up required — {case_id}\n\n"
                f"Hi Team,\n\nPlease review case {case_id}.\n\n"
                f"Recommended action: {rec}\n\nRegards,\nOperations Team"
            )
            c.execute("""UPDATE cases SET category=?, priority=?, summary=?, recommendation=?, email_draft=? WHERE case_id=?""", (
                x["category"], x["priority"], x["summary"], rec, email, case_id
            ))


class ChatRequest(BaseModel):
    question: str


@app.get("/api/health")
def health():
    return {"status": "ok", "ai_provider": "Groq", "ai_configured": bool(API_KEY), "model": MODEL}


@app.get("/api/cases")
def cases():
    return get_cases()


@app.get("/api/dashboard")
def dashboard():
    rows = get_cases()
    categories = {}
    for r in rows:
        categories[r.get("category") or "Uncategorized"] = categories.get(r.get("category") or "Uncategorized", 0) + 1
    return {
        "total": len(rows),
        "high_priority": sum(r.get("priority") == "High" for r in rows),
        "unresolved": sum(str(r.get("status", "")).lower() != "resolved" for r in rows),
        "resolved": sum(str(r.get("status", "")).lower() == "resolved" for r in rows),
        "categories": [{"name": k, "count": v} for k, v in sorted(categories.items(), key=lambda x: -x[1])],
    }


@app.post("/api/chat")
def chat(req: ChatRequest):
    return {"answer": chat_answer(req.question, get_cases())}


@app.post("/api/workflow/run")
def workflow():
    rows = get_cases()
    if not rows:
        return {"processed": 0, "message": "No cases loaded."}

    total = 0
    for i in range(0, len(rows), 5):
        batch = rows[i:i + 5]
        results = analyze_cases_batch(batch)
        update_ai_results([
            {**r, "case_id": batch[j]["case_id"]}
            for j, r in enumerate(results)
        ])
        total += len(results)
    return {"processed": total, "message": f"Processed {total} cases."}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    filename = file.filename or "upload"
    content = await file.read()
    suffix = Path(filename).suffix.lower()

    if suffix == ".pdf":
        try:
            from io import BytesIO
            reader = PdfReader(BytesIO(content))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except Exception as exc:
            raise HTTPException(400, f"Could not read PDF: {exc}")
        with conn() as c:
            c.execute("INSERT INTO documents(filename,content,created_at) VALUES(?,?,?)", (filename, text, datetime.now().isoformat()))
        return {"message": f"Indexed PDF {filename} ({len(reader.pages)} pages).", "processed": 0, "type": "pdf"}

    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(400, "Supported files: CSV, XLSX, XLS and PDF.")

    try:
        df = read_structured(content, filename)
        cases = df_to_cases(df)
    except Exception as exc:
        raise HTTPException(400, f"Could not process {filename}: {exc}")

    if not cases:
        raise HTTPException(400, "No usable cases found. Make sure the file has an issue/description column with data.")

    upsert_cases(cases)

    total = 0
    for i in range(0, len(cases), 5):
        batch = cases[i:i + 5]
        results = analyze_cases_batch(batch)
        update_ai_results([
            {**r, "case_id": batch[j]["case_id"]}
            for j, r in enumerate(results)
        ])
        total += len(results)

    return {"message": f"Processed {total} cases from {filename}", "processed": total, "type": "structured"}
