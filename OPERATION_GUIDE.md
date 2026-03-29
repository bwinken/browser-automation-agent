# BaaS — Operation Guide

> **Browser Automation as a Service**
> Live: [https://bwinken-baas.zeabur.app](https://bwinken-baas.zeabur.app)

---

## Quick Start

### 1. Login

Open the app URL. You will see the login page:

![Login Page](docs/01_login.png)

Use the credentials provided to you to login. If you have an **invite code**, click "Register with invite code" to create a new account.

### 2. Main Interface

After login, you'll see the 3-panel interface:

![Main Interface](docs/02_main.png)

| Panel | Description |
|-------|-------------|
| **Left — History** | Past tasks with status badges. Click to view. `+ New` starts a fresh task. |
| **Center — Chat** | Type a task in natural language, or click a verified example. |
| **Right — Tool Execution** | Real-time agent activity grouped by iteration. |

### 3. Run a Task

**Option A: Type your own task**
Type any browser automation task in natural language:
```
Search Google Scholar for papers about LLM agents since 2024.
List the top 3 results with title, authors, year, and citation count.
```

**Option B: Click a verified example**
At the bottom of the chat, you'll see pre-tested examples. Click one to run it immediately.

### 4. Watch the Agent Work

Once submitted:
- The **status badge** (top center) changes to `running`
- A red **Stop** button appears to cancel if needed
- The **Tool Execution** panel shows each iteration:
  - `#1 [load_skill]` — agent loading a skill
  - `#2 [navigate] [take_screenshot]` — browsing to a site
  - `#3 [evaluate_javascript]` — extracting data from the page
  - `#7 [review_and_finalize]` — verifying results
- Click any iteration to expand/collapse its details

### 5. View Results

When the task completes:
- The agent's response appears in the chat with **markdown formatting** (tables, lists, etc.)
- **Evidence screenshots** are shown below the response (click to enlarge)
- **Download links** (if the task involved file downloads) appear as green buttons at the top of the response

### 6. Follow-up Questions

After a task completes, type another message in the same chat to continue:
```
How about JPY/TWD rate?
```
The agent resumes with full conversation context. Previous results are preserved.

---

## Features

### Guide
Click the **Guide** button in the header to see:
- Usage instructions
- All verified example tasks (click to run)
- REST API documentation with curl examples
- WebSocket real-time protocol
- Quota information

![Guide](docs/03_guide.png)

### Settings
Click **Settings** to:
- View your **API key** (for programmatic access)
- Check your **usage** (spent / remaining credit)
- Add your own **OpenAI API key** (when free credit runs out)

### Task Management
- **+ New** — start a fresh conversation
- **Stop** — cancel a running task (generates partial summary)
- **Delete** — hover over a task in history, click `×`
- **Pagination** — navigate pages at the bottom of history

---

## REST API

All endpoints require `Authorization: Bearer YOUR_API_KEY` header.
Find your API key in **Settings**.

### Create a Task
```bash
curl -X POST https://bwinken-baas.zeabur.app/api/task \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"prompt": "Search for Python jobs on 104.com.tw in Taipei"}'
```
Response: `{"task_id": "uuid"}`

### Check Task Status
```bash
curl https://bwinken-baas.zeabur.app/api/task/TASK_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Continue a Task (Follow-up)
```bash
curl -X POST https://bwinken-baas.zeabur.app/api/task/TASK_ID/continue \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "Now search for backend jobs in Hsinchu"}'
```

### Cancel a Running Task
```bash
curl -X POST https://bwinken-baas.zeabur.app/api/task/TASK_ID/cancel \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### List Tasks
```bash
curl "https://bwinken-baas.zeabur.app/api/task?skip=0&limit=10" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Delete a Task
```bash
curl -X DELETE https://bwinken-baas.zeabur.app/api/task/TASK_ID \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### WebSocket (Real-time Updates)
```
wss://bwinken-baas.zeabur.app/ws/task/TASK_ID?token=YOUR_API_KEY
```

---

## What the Agent Can Do

### Simple Queries
- Weather forecasts (CWA)
- Job search (104.com.tw)
- Price comparison (PCHome, Momo)
- Stock market data (TWSE)
- Academic papers (Google Scholar)
- Exchange rates (Bank of Taiwan)

### Complex Operations
- Train schedules (TRA, THSR) with form filling
- Hotel search (Booking.com)
- Company registration lookup (findbiz.nat.gov.tw)
- Multi-site data comparison

### Downloads
- CSV/PDF file downloads from any website
- arXiv paper downloads
- TWSE trading reports

### Self-Healing
- Auto-dismisses cookie banners and popups
- Falls back between CSS/text/role selectors
- Detects and breaks out of loops
- Handles CAPTCHAs (image recognition + 2Captcha)
- Generates partial summary on timeout/cancel

---

## Quota

Each account gets **$10.00 USD** in free credit. Usage is calculated per LLM call based on token consumption (input + output).

When your credit runs out, you can add your own OpenAI API key in **Settings** to continue using the service with no quota limit.

---

## Technical Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.11, FastAPI |
| Browser | Playwright (headless Chromium) |
| AI Model | OpenAI GPT-5.4 (configurable) |
| Database | MongoDB (Beanie ODM) |
| Auth | Invite code + API key |
| Deployment | Docker on Zeabur |

---

*Built by Kane Beh — behwinken@gmail.com*
