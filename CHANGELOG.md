# Changelog

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

### [0.2.0] — Authentication & Reliability
> Target: 2026-04

- **Credential store** — detect when agent fills login forms; encrypt and
  persist credentials in MongoDB; auto-inject on subsequent tasks for the
  same domain (eliminates repeated manual logins)
- **Auth scenario skills** — pre-defined handling profiles for common auth
  flows (Google OAuth, email+OTP, cookie-based SSO) so the agent knows the
  correct sequence without trial-and-error
- **Retry + recovery** — on tool failure, agent retries with alternative
  selectors before escalating to HITL; structured error classification
  (element-not-found vs network vs auth-wall)
- **Reduce CAPTCHA exposure** — rotate User-Agent, randomise viewport sizes,
  add human-like mouse movement delays via `slow_mo`

---

### [0.3.0] — Structured HITL & Fully Automated Mode
> Target: 2026-04

- **Option-based HITL** — instead of free-text, agent can present the
  operator with structured choices (radio buttons / checkboxes in modal)
  for unambiguous decisions
- **Credential HITL** — when agent detects a login field it hasn't seen
  before, prompt user for credentials once → store encrypted in DB → reuse
  automatically on all future tasks for that domain
- **Fully automated mode** — `AUTO_MODE=true` flag; agent never pauses
  except for first-time credential collection; all subsequent runs use
  stored credentials silently

---

### [0.4.0] — Frontend Execution Flow Visualisation
> Target: 2026-05

- **Structured step view** — replace flat terminal log with a timeline of
  agent steps: each tool call shown as a card (tool name, args, result,
  screenshot thumbnail)
- **Screenshot history** — every `navigate` call saves a thumbnail; user
  can click to expand full screenshot at that point in time
- **Task replay** — browse the complete execution trace of any past task
- **Result panel** — final `result_data` rendered as structured output
  (tables, links) rather than raw JSON

---

### [0.5.0] — Task Continuation & Long-running Sessions
> Target: 2026-05

- **Continue task** — `POST /api/task/{id}/continue` resumes a `failed` or
  `paused` task from the last known browser state; preserves full message
  history so the LLM has full context
- **Checkpoint saves** — `BrowserState` written to MongoDB after every
  `navigate` call (not just at task end), enabling fine-grained recovery
- **Session browser** — UI shows all active browser sessions; operator can
  attach to a running session and watch live

---

### [0.6.0] — Parallel Task Execution (Optional)
> Target: 2026-06

- **Parallelism analyser** — before execution, LLM analyses the task and
  splits it into independent sub-tasks (e.g. scrape N URLs concurrently)
- **Sub-task orchestrator** — spawns multiple `AgentRunner` instances for
  independent branches; merges results before returning final output
- **Dependency graph** — tasks with data dependencies execute sequentially;
  independent tasks fan out across the semaphore pool

---

*Kane.Beh 4422*
