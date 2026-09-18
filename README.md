# AI Operations Automation Hub

Full-stack MVP for business-case ingestion, AI classification, operational analytics, chat, workflow automation and email drafting.

## Stack
- Next.js 14 + React 18 + TypeScript + Tailwind
- FastAPI + Python 3.12
- SQLite
- Groq API
- Pandas / openpyxl / pypdf

## Local setup on Windows

### 1. Backend
Open PowerShell:

```powershell
cd C:\path\to\AI-Operations-Automation-Hub-Corrected\backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Open `backend/.env` and put your real key:

```env
GROQ_API_KEY=your_real_key
GROQ_MODEL=openai/gpt-oss-20b
DATABASE_URL=sqlite:///./operations.db
```

Then:

```powershell
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend
Open a second PowerShell:

```powershell
cd C:\path\to\AI-Operations-Automation-Hub-Corrected\frontend
npm install
npm run dev
```

Open http://localhost:3000

## Test
Go to **Documents** and upload `data/sample_cases.csv`.

Expected result:
- 20 cases processed
- Dashboard totals update
- Cases appear in Cases tab
- Each case has AI summary, recommendation and email draft
- Drag/drop and click-to-browse both work

The frontend uses a Next.js rewrite, so browser requests to `/api/*` are proxied to FastAPI at `127.0.0.1:8000`.
