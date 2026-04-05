# FlowOF

B2B SaaS dashboard for OnlyFans agencies.  
**Stack**: FastAPI + asyncpg (backend) · Next.js 16 + TypeScript (frontend) · Neon PostgreSQL

---

## Deploy

### Backend → Railway

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo → `vhvyvy/FlowOF`
2. Set **Root Directory** = `backend`
3. Add environment variables:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://neondb_owner:npg_yDrCmcTs50xv@ep-broad-forest-alh2ugau-pooler.c-3.eu-central-1.aws.neon.tech/neondb?sslmode=require` |
| `SECRET_KEY` | random 32-char string |
| `ADMIN_SECRET` | your admin password |
| `OPENAI_API_KEY` | sk-... |
| `FRONTEND_URL` | https://your-app.vercel.app |

4. Railway auto-detects Dockerfile and builds automatically

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → New Project → Import `vhvyvy/FlowOF`
2. Set **Root Directory** = `frontend`
3. Add environment variable:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | https://your-backend.railway.app |

---

## Local Development

### Backend
```bash
cd backend
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
cp .env.example .env    # Fill in values
uvicorn main:app --reload --port 8000
```
Swagger UI: http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
cp .env.local.example .env.local  # Set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```
App: http://localhost:3000

---

## Structure
```
FlowOF/
├── backend/          # FastAPI API server
│   ├── main.py
│   ├── database.py   # asyncpg + SQLAlchemy 2.0
│   ├── models.py     # 8 DB tables
│   ├── auth.py       # JWT + bcrypt
│   ├── routers/      # auth, overview, finance, chatters, kpi, events, plans, admin, ai
│   └── ...
├── frontend/         # Next.js 16 App Router
│   ├── app/
│   │   ├── login/    # Auth page
│   │   └── dashboard/ # Main dashboard (Overview, Finance, Chatters, KPI, AI)
│   ├── components/   # MetricCard, RevenueChart, WaterfallChart, Sidebar
│   └── lib/          # api.ts, auth.ts, hooks/
└── repo_temp/        # Old Streamlit app (to be deleted)
```
