# Changelog

---

## [0.5.0] — 2026-03-28

### Task cancel, timeouts, and Phase 3 testing complete

**Task Cancel / Terminate**
- Stop button in frontend to cancel running tasks
- `POST /api/task/{id}/cancel` REST endpoint
- WebSocket cancel signal support
- Agent generates partial summary before stopping

**Timeouts**
- Per-tool timeout (60s) — individual tool executions timeout to prevent hangs on unresponsive pages
- Task timeout (300s) — overall task timeout with partial summary generation on expiry

**Enhanced Loop Detection**
- Same-tool-name tracking: 10 consecutive uses of the same tool within a 20-action window triggers force break
- Complements existing exact-match repeated-action detection

**Evidence Screenshot Flag**
- `take_screenshot(evidence=true)` saves screenshot as verifiable evidence for the final report
- Enables multi-site tasks to capture separate evidence screenshots per source page

**Phase 3 Testing — Downloads & Multi-step Operations (5/5 passed)**
- TWSE CSV download — click download button, file saved
- arXiv PDF download — search + PDF link + `download_file(url=)`
- THSR + TRA cross-site comparison — times/price from both sites extracted
- 104 job detail extraction — all fields + evidence screenshot
- TWSE investors + download — API data + summary verified

---

## [0.4.0] — 2026-03-28

### Invite code auth system + login page

**Authentication**
- Invite code system: only users with valid invite codes can register
- `InviteCode` model: code, used status, used_by, timestamps
- `User.is_admin` field for admin-only operations
- Register endpoint requires `invite_code` parameter
- Password minimum 6 characters enforced
- Admin endpoints: `POST /api/users/admin/invite`, `GET /api/users/admin/invites`

**Startup Seeding**
- `ADMIN_USERNAME` + `ADMIN_PASSWORD` in `.env` auto-creates admin user on first run
- `INITIAL_INVITE_CODES` (default 3) auto-generates invite codes if none exist
- Invite codes logged to console for distribution

**Frontend**
- Full login/register page (dark theme, centered card)
- Register form: invite code + username + password
- Login form: username + password
- API key persisted in `localStorage` (survives page refresh)
- Logout button in header clears session
- Auth page blocks all access until authenticated

---

## [0.3.0] — 2026-03-28

### Field-tested skills, strict verification, and stability fixes

**New Skills (27 → 35)**
- E-commerce / Price Comparison — PCHome JSON API, Momo URL search patterns
- Government / Bank Public Data — 台銀匯率 direct URL, CSV download, table extraction
- Financial Market Data — TWSE JSON API endpoints, Big5 encoding warning
- Job Search Sites — 104 URL patterns, area codes, virtual DOM extraction
- Real Estate / Rental — 591 URL patterns, Vue SPA hashed class workaround
- Academic Research — Google Scholar (no login!), arXiv PDF download
- Weather Forecast — CWA direct county URLs (CID codes), table extraction

**Strict Verification System**
- `review_and_finalize` now requires item-by-item cross-check: every number,
  name, date, count must exactly match the evidence screenshot
- `test_verify.py` — automated post-task QA using GPT vision to compare
  summary against screenshots (score 0-100, pass/fail)
- Test results: Google Scholar improved 60→100 after strict review

**Stability Fixes**
- Upgraded openai SDK 1.35→2.x (fixed httpx proxies incompatibility)
- LLM API timeout: 120s SDK + 150s asyncio safety net
- Reduced tool timeouts: `_wait_for_stable` 2s+0.8s, `_find_element` 5s+1.5s+1s
- Loop detection: window 20, threshold 4, hard limit 6
- `fill()` auto-clicks first autocomplete suggestion
- CAPTCHA: checkbox before API for Turnstile/hCaptcha (faster + free)
- Click intercept: Escape → dismiss overlay → scroll (footer) → force click
- Press-and-hold: human-like mouse curve + jitter simulation
- Every tool_call guaranteed a response (try/finally)
- Deferred screenshot injection (after all tool results)
- WebSocket auto-reconnect (5 attempts, linear backoff)

**Infrastructure**
- `/downloads/` endpoint with auth protection + path traversal prevention
- `download_file` returns download URL for frontend access
- Viewport fixed at 1440x1200 for better result visibility
- Removed BrowserState, CDP, persistent profile (simplified)
- Task continuation: conversation history always saved (fallback to prompt)

**Frontend**
- Evidence screenshots in chat (click to enlarge, numbered)
- Result poll fallback for task continuation
- Mandatory screenshots at key decision points

---

## [0.2.0] — 2026-03-28

### Major upgrade — intelligent agent with vision, skills, and self-healing

**Agent Intelligence**
- ReAct execution loop: Reason → Act → Observe on every step
- 27 progressive skill playbooks loaded on-demand via `load_skill()` tool
- Vision support: agent sees screenshots via GPT-4o vision (CAPTCHA reading, coordinate clicking, result verification)
- `review_and_finalize` tool: cross-checks summary against actual page before delivering results
- Loop detection: warns at 4 repeats, force-breaks at 6 to prevent infinite loops
- Structured error classification: `[ERROR:element_not_found]`, `[ERROR:loop_detected]`, etc.
- Smart defaults: "明天一點" → PM 1:00, missing dates → tomorrow

**New Tools (17 total)**
- `click_position(x, y)` — pixel-coordinate clicking for calendar grids, canvas elements
- `take_screenshot()` — captured image visible to LLM via vision
- `scroll(direction, amount)` — page scrolling for lazy-loaded content
- `press_key(key, hold_ms)` — keyboard with alias auto-fix + press-and-hold with human-like mouse simulation
- `wait_for_element(selector)` — wait for dynamic elements
- `select_option(selector, value)` — `<select>` dropdown handling
- `download_file(url?, selector?)` — file download by URL or click trigger
- `solve_captcha()` — multi-strategy: checkbox click → 2Captcha API → vision → HITL
- `ask_user(question, mode, options)` — inline questions (text / single-select / multi-select)
- `request_credentials(reason, fields)` — structured credential forms
- `review_and_finalize(planned_summary)` — evidence verification before delivery
- `load_skill(name)` — progressive skill loading

**Skills System**
- Cookie Consent, Popup/Overlay Dismissal, Autocomplete Handling
- 8 authentication skills: Standard, Multi-Step, OAuth, SSO, Magic Link, Phone OTP, 2FA
- CAPTCHA Handling, Image CAPTCHA / Verification Code
- Date Picker Handling, Travel / Hotel Booking, Transportation / Ticket Booking
- Search Filtering, Data Extraction, Evidence Collection, Self-Healing / Error Recovery
- Avoid Blocked Services (Google workarounds)

**Browser Reliability**
- Auto-dismiss: cookie banners, login promos, notification popups (7 languages)
- Selector fallbacks: CSS → text match → role match (automatic)
- Click intercept handling: Escape → overlay dismiss → scroll (footer) → force click
- `_wait_for_stable`: page stabilization after every action (domcontentloaded + networkidle)
- Stealth: randomized UA + timezone, human-like delays, press-and-hold mouse simulation
- 2Captcha integration for reCAPTCHA v2/v3, hCaptcha, Turnstile
- LLM API timeout (120s SDK + 150s safety net)

**Frontend — Chat Interface**
- Three-panel layout: History | Chat | Tool Execution
- Inline `ask_user` with single-select, multi-select, free-text modes
- Credential modal with dynamic form fields
- HITL modal with screenshot
- Evidence screenshots in chat results (click to enlarge)
- WebSocket auto-reconnect (5 attempts, linear backoff)
- Task continuation: follow-up messages in same task preserve conversation history

**API**
- `POST /api/task/{id}/continue` — resume completed/failed tasks with follow-up
- Task list: paginated, sorted newest first, includes `has_history` flag
- Token usage tracking per user

---

## [0.1.0] — 2026-03-26

### Initial release — core platform working end-to-end

**Infrastructure**
- FastAPI + Beanie (MongoDB ODM) foundation
- Dockerfile (`python:3.11-slim` + `playwright install --with-deps chromium`)
- `docker-compose.yml` for local dev; production uses MongoDB Atlas
- `run.py` entry point — sets `WindowsProactorEventLoopPolicy` before uvicorn
  starts so Playwright subprocess works on Windows

**Data Models**
- `User` — username, bcrypt password, UUID api_key, token_usage
- `BrowserState` — persists Playwright `storageState` to MongoDB (cookies +
  localStorage survive container restarts on Zeabur)
- `Task` — status lifecycle, append-only logs list, result_data

**AI Agent Loop**
- Pure OpenAI SDK tool-calling `while` loop — no LangChain, no browser-use
- 6 tools: `navigate`, `click`, `fill`, `evaluate_javascript`,
  `get_page_content`, `request_human_assistance`
- `asyncio.Semaphore` caps concurrent Playwright instances
- `playwright-stealth` + realistic User-Agent / locale / timezone to reduce
  bot detection and CAPTCHA triggers

**API**
- `POST /api/users/register` / `POST /api/users/login`
- `POST /api/task` (202 + task_id, runs agent as background task)
- `GET /api/task/{id}` / `GET /api/task`
- `WS /ws/task/{task_id}` — live log streaming + HITL pause/resume

**Human-in-the-Loop (HITL)**
- Agent calls `request_human_assistance` → takes screenshot → pauses
- WebSocket pushes screenshot + reason to frontend modal
- Operator types response → agent resumes with input as tool result
- 5-minute timeout before auto-continue

**Frontend**
- Single-page: task prompt input, live terminal log, HITL screenshot modal
- Colour-coded log lines (tool calls, results, errors)
- Auto-loads demo API key in `DEV_MODE`
- Status badge: `idle → pending → running → paused → completed / failed`

**Dev Quality**
- `DEV_MODE=true` bypasses auth (uses first user in DB)
- `LOG_LEVEL` env var controls verbosity
- Global exception handler returns JSON with full traceback logged

---

## Roadmap

### Next — Frontend Execution Flow Visualisation

- **Structured step view** — replace flat terminal log with a timeline of
  agent steps: each tool call shown as a card (tool name, args, result,
  screenshot thumbnail)
- **Screenshot history** — every `navigate` call saves a thumbnail; user
  can click to expand full screenshot at that point in time
- **Task replay** — browse the complete execution trace of any past task
- **Result panel** — final `result_data` rendered as structured output
  (tables, links) rather than raw JSON

---

### Future — Parallel Task Execution

- **Parallelism analyser** — before execution, LLM analyses the task and
  splits it into independent sub-tasks (e.g. scrape N URLs concurrently)
- **Sub-task orchestrator** — spawns multiple `AgentRunner` instances for
  independent branches; merges results before returning final output
- **Dependency graph** — tasks with data dependencies execute sequentially;
  independent tasks fan out across the semaphore pool

