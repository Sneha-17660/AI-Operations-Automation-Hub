import json
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
API_KEY = os.getenv("GROQ_API_KEY", "").strip()


def _client():
    if not API_KEY:
        return None
    from groq import Groq
    return Groq(api_key=API_KEY)


def _clean_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def _deterministic(case: dict) -> dict:
    issue = str(case.get("issue", "")).lower()
    status = str(case.get("status", "")).lower()
    existing_category = str(case.get("category", "")).strip()
    existing_priority = str(case.get("priority", "")).strip()

    if existing_category:
        category = existing_category
    elif any(k in issue for k in ["invoice", "payment", "refund", "charge", "purchase order"]):
        category = "Payment"
    elif any(k in issue for k in ["delivery", "shipment", "tracking", "received only", "late"]):
        category = "Delivery"
    elif any(k in issue for k in ["login", "export", "api", "portal", "system", "error"]):
        category = "Technical"
    elif any(k in issue for k in ["complaint", "claim", "response"]):
        category = "Claims"
    else:
        category = "Other"

    if existing_priority:
        priority = existing_priority
    elif any(k in issue for k in ["fraud", "duplicate", "wrong charge", "payment", "invoice mismatch", "api", "login"]):
        priority = "High"
    elif any(k in issue for k in ["delay", "delayed", "partial", "complaint", "tracking"]):
        priority = "Medium"
    else:
        priority = "Low"

    resolved = status == "resolved" or any(k in issue for k in ["successfully processed", "resolved"])
    if resolved:
        recommendation = "Confirm resolution with the customer and close the case."
    elif category == "Payment":
        recommendation = "Verify the transaction and supporting records, then coordinate with the finance team to resolve the issue."
    elif category == "Delivery":
        recommendation = "Check shipment status with the carrier and provide the customer with a clear resolution timeline."
    elif category == "Technical":
        recommendation = "Reproduce the issue, review system logs, and assign it to the technical support team for resolution."
    else:
        recommendation = "Review the case details, assign the appropriate owner, and provide the customer with a timely update."

    return {
        "category": category,
        "priority": priority,
        "summary": str(case.get("issue", "")).strip() or "No issue description provided.",
        "recommendation": recommendation,
    }


def analyze_cases_batch(cases: list[dict]) -> list[dict]:
    if not cases:
        return []
    client = _client()
    if client is None:
        return [_deterministic(c) for c in cases]

    payload = [{
        "case_id": c.get("case_id"),
        "customer": c.get("customer"),
        "issue": c.get("issue"),
        "status": c.get("status"),
        "category": c.get("category"),
        "priority": c.get("priority"),
    } for c in cases]

    prompt = f"""You are an operations analyst. Analyze every case below.
Return ONLY a JSON array with exactly one object per input case, in the same order.
Each object must contain: category, priority, summary, recommendation.
Allowed priority values: High, Medium, Low.
Keep summaries concise and recommendations actionable. Do not invent facts.

Cases:
{json.dumps(payload, ensure_ascii=False)}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0.1,
            max_tokens=1800,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _clean_json(response.choices[0].message.content or "[]")
        if not isinstance(parsed, list) or len(parsed) != len(cases):
            raise ValueError("AI returned an invalid number of results")
        return [
            {
                "category": str(x.get("category", "Other")),
                "priority": str(x.get("priority", "Medium")),
                "summary": str(x.get("summary", "")),
                "recommendation": str(x.get("recommendation", "Review and resolve the case.")),
            }
            for x in parsed
        ]
    except Exception:
        return [_deterministic(c) for c in cases]


def chat_answer(question: str, cases: list[dict]) -> str:
    if not cases:
        return "No cases are currently loaded. Upload a CSV or XLSX file first."

    client = _client()
    if client is None:
        q = question.lower()
        unresolved = [c for c in cases if str(c.get("status", "")).lower() != "resolved"]
        high = [c for c in cases if str(c.get("priority", "")).lower() == "high"]
        if "unresolved" in q:
            return "Unresolved cases: " + ", ".join(f"{c.get('case_id')} — {c.get('customer')}" for c in unresolved)
        if "high" in q and "payment" in q:
            matches = [c for c in high if str(c.get("category", "")).lower() == "payment"]
            return "High-priority payment cases: " + (", ".join(c.get("case_id", "") for c in matches) or "None")
        return f"There are {len(cases)} cases, {len(unresolved)} unresolved and {len(high)} high-priority."

    context = json.dumps(cases[:50], ensure_ascii=False)
    prompt = f"Answer the user's operations question using only this case data. Be concise and mention case IDs when useful.\n\nQuestion: {question}\n\nData:\n{context}"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            temperature=0.2,
            max_tokens=900,
            messages=[
                {"role": "system", "content": "You are an operations intelligence assistant. Do not invent facts."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or "No answer returned."
    except Exception as exc:
        return f"AI request could not be completed: {exc}"
