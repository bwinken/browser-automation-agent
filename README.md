# Browser Automation as a Service (BaaS)

A minimal, robust browser automation API. Submit a natural language task — an AI agent executes it in a headless Chromium browser using pure OpenAI tool calling and native Playwright.

**No LangChain. No browser-use. No abstractions.**

---

## Features

- **Natural language tasks** → AI agent executes step-by-step in a real browser
- **Pure OpenAI SDK** tool-calling loop (gpt-4o)
- **Session persistence** — Playwright `storageState` saved to MongoDB, survives restarts
- **Human-in-the-Loop (HITL)** — agent pauses on CAPTCHAs/ambiguity, sends screenshot to frontend, resumes on operator response
- **Stealth mode** — `playwright-stealth` + realistic fingerprint to minimise bot detection
- **Live log streaming** via WebSocket
- **Multi-user isolation** via MongoDB Beanie ODM
- **Deployable to Zeabur** (Dockerfile included)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI |
| Database | MongoDB + Beanie (async ODM) |
| AI | OpenAI Python SDK (`gpt-4o`), pure tool calling |
| Browser | Playwright (async), playwright-stealth |
| Frontend | Plain HTML + CSS + Vanilla JS |
| Deploy | Docker → Zeabur |

---

## Quick Start

### Prerequisites
- Python 3.11+
- MongoDB Atlas account (free tier works)
- OpenAI API key

### Setup

```bash
git clone https://github.com/bwinken/browser-automation-agent.git
cd browser-automation-agent

# Create virtual environment
python -m venv .venv
.venv/Scripts/activate   # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env — fill in MONGODB_URL, OPENAI_API_KEY, DEMO_API_KEY
```

### Run (local dev)

```bash
python run.py
```

Open [http://localhost:8080](http://localhost:8080)

> **Windows note:** `run.py` sets `WindowsProactorEventLoopPolicy` before uvicorn starts — required for Playwright subprocess support.

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `MONGODB_URL` | MongoDB Atlas connection string | `mongodb://localhost:27017` |
| `DB_NAME` | Database name | `baas` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | Model to use | `gpt-4o` |
| `DEMO_API_KEY` | Pre-created user UUID for dev | — |
| `HEADLESS` | Run browser headlessly | `true` |
| `DEV_MODE` | Skip auth, use first user | `false` |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` | `INFO` |
| `MAX_CONCURRENT_BROWSERS` | Simultaneous Playwright instances | `2` |
| `MAX_AGENT_ITERATIONS` | Max LLM loop iterations per task | `20` |

---

## API

### Authentication
All task endpoints require `Authorization: Bearer <api_key>` header.
In `DEV_MODE=true`, auth is bypassed (uses first user in DB).

### Endpoints

```
POST /api/users/register   — Create account → returns api_key
POST /api/users/login      — Login → returns api_key

POST /api/task             — Submit task (202 + task_id)
GET  /api/task/{task_id}   — Poll task status + logs
GET  /api/task             — List all tasks for user

WS   /ws/task/{task_id}    — Live log stream + HITL channel
```

### Task Lifecycle

```
pending → running → completed
                 → paused (HITL) → running → completed
                 → failed
```

---

## Agent Tools

| Tool | Description |
|---|---|
| `navigate(url)` | Navigate to URL |
| `click(selector)` | Click element by CSS selector |
| `fill(selector, text)` | Type into input |
| `evaluate_javascript(script)` | Execute JS, return result |
| `get_page_content()` | Get LLM-friendly DOM snapshot |
| `request_human_assistance(reason)` | Pause + send screenshot to operator |

---

## Deployment (Zeabur)

1. Push to GitHub
2. Zeabur → New Project → Add Service → **Git** (select this repo)
3. Add Service → **MongoDB** from Marketplace (or use Atlas connection string)
4. Set environment variables in Zeabur Variables panel
5. Deploy — Zeabur builds from `Dockerfile` automatically

---

## Project Structure

```
app/
├── main.py          FastAPI app, lifespan (Beanie init), routes
├── config.py        pydantic-settings
├── models.py        Beanie: User, BrowserState, Task
├── auth.py          bcrypt hashing, HTTPBearer API-key guard
├── shared.py        In-process HITL state (asyncio Events/Queues)
├── tools.py         OpenAI tool schemas + PlaywrightToolExecutor
├── agent.py         AgentRunner — the core tool-calling while-loop
├── logging_config.py
├── api/
│   ├── users.py     Register / login
│   └── tasks.py     Submit / poll tasks
└── ws/
    └── hitl.py      WebSocket log stream + HITL handshake
static/
└── index.html       SPA frontend
run.py               Entry point (sets Windows event loop policy)
Dockerfile
```

