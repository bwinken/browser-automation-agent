"""
Core AI agent loop.

Uses the pure OpenAI Python SDK with function/tool calling.
No LangChain, no browser-use — only openai + playwright.

Control flow
------------
1. Build initial messages list (system prompt + user task).
2. Loop (up to MAX_AGENT_ITERATIONS):
   a. Call OpenAI chat completions with TOOLS.
   b. If the model returns text only  → task complete, break.
   c. For each tool_call in the response:
      - Execute the matching PlaywrightToolExecutor method.
      - If tool == request_human_assistance → pause loop, emit HITL event,
        wait for operator response via shared.hitl_events, then resume.
      - Append tool result as a "tool" role message.
3. Save playwright context storageState back to MongoDB.
"""
import asyncio
import base64
import json
import logging
import os
import random
from typing import Any, Dict, List

from playwright_stealth import Stealth

_stealth = Stealth()

# Realistic User-Agent pool — rotated per task to reduce fingerprinting
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_VIEWPORT = {"width": 1440, "height": 1200}

_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Los_Angeles",
    "Europe/London",
    "Asia/Tokyo",
]

from openai import AsyncOpenAI
from playwright.async_api import async_playwright

from app.config import settings
from app.models import Task, User
from app.shared import hitl_data, hitl_events, hitl_responses, ws_queues
from app.skills import build_skill_catalogue
from app.tools import TOOLS, PlaywrightToolExecutor

log = logging.getLogger(__name__)

# Global semaphore — limits simultaneous Playwright instances across all tasks.
_browser_semaphore = asyncio.Semaphore(settings.max_concurrent_browsers)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a browser automation agent. Today: {today}

## Loop: Reason → Act (→ auto-observe)
Every step: (1) Reason — briefly explain WHAT and WHY, note "[SKILL: name]" if applicable. \
(2) Act — call action tool(s).

Action tools (navigate, click, fill, press_key, select_option) automatically return a \
page brief: [Page: title | url | N buttons, N links, N inputs]. Use this to decide \
your next move WITHOUT calling a separate observe tool.

Only call get_page_content when you need full element details (selectors, hrefs, text). \
You may call multiple non-conflicting tools in one step to save iterations.

## Mandatory Screenshots (take_screenshot) at Key Decision Points
You MUST take_screenshot at these moments — do NOT skip:
- After navigating to a new site (verify you're on the right page)
- Before filling a form (verify the form fields are correct)
- After filling a form but BEFORE submitting (verify all values are correct)
- When encountering ANY unexpected content (error, CAPTCHA, popup, wrong page)
- Before collecting evidence / writing final summary

## Attitude
Act first, ask later. Use common sense — "明天一點" = PM 1:00, not AM. \
Pick reasonable defaults (tomorrow, 2 adults) and mention assumptions. \
Only call ask_user when you truly cannot decide (e.g. "which of these 3 to book?").

## Key Rules
- click/fill support CSS selectors, text content, and role-based fallbacks automatically.
- For date pickers: load_skill('Date Picker Handling') — never click calendar grids.
- For login pages: load_skill('Auth: Identify Login Type') first.
- For Google/bot-blocking sites: load_skill('Avoid Blocked Services').
- For image CAPTCHAs (驗證碼): take_screenshot → read the text → fill it in.
- press_key supports modifier combos (Control+a, Shift+Enter). Aliases auto-fixed (Ctrl→Control).
- evaluate_javascript is a last resort — prefer native tools (click, fill, select_option) first.
- Cookie banners are auto-dismissed after navigate. If one persists, handle manually.
- To dismiss ANY popup/modal/overlay: ALWAYS use press_key('Escape') first. \
  NEVER try click('X'), click('✕'), click('Close'), or click any close button — \
  those buttons are usually SVG icons with no text content, impossible to locate by text. \
  If Escape doesn't work, try: click('[aria-label=\"Close\"]') or click('button[class*=\"close\"]').
- If an action fails, read the [ERROR:...] tag and change approach. Never repeat the same failure.
- EVIDENCE FLOW (follow this order):
  1. CONFIRM data first: use get_page_content or evaluate_javascript to extract the key results \
     (names, prices, times, etc). Write them down in your reasoning.
  2. THEN screenshot: take_screenshot of the results page showing the data you extracted.
  3. REVIEW: call review_and_finalize with your draft summary. The review will compare \
     your summary against the screenshot pixel-by-pixel. Every number, name, date, and \
     count in your summary MUST exactly match the screenshot. If the review finds errors, \
     fix them and call review_and_finalize again with the corrected summary.
  4. Only write your final summary (no tool call) AFTER the review confirms "All verified".
"""

_skill_catalogue = build_skill_catalogue()


def _build_system_prompt() -> str:
    from datetime import date
    return _SYSTEM_PROMPT_TEMPLATE.format(today=date.today().isoformat()) + _skill_catalogue


class AgentRunner:
    """Runs the full agent loop for a single Task document."""

    _LOOP_THRESHOLD = 4   # same action N times in window → warning
    _LOOP_HARD_LIMIT = 6  # same action N times in window → force break

    def __init__(self, task: Task, user: User, follow_up: str = "") -> None:
        self.task = task
        self.user = user
        self._follow_up = follow_up  # new user message for continuation
        self._client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=120.0)
        self._messages: List[Dict[str, Any]] = []
        self._page = None  # set inside run() for HITL screenshot access
        self._recent_actions: List[str] = []  # track for loop detection
        self._evidence: List[str] = []  # collected screenshots (base64)
        self._evidence_hashes: set = set()  # dedup by size

    # ------------------------------------------------------------------
    # Public entry point (called as a FastAPI background task)
    # ------------------------------------------------------------------

    async def run(self) -> None:
        async with _browser_semaphore:
            async with async_playwright() as pw:
                await self._run_with_playwright(pw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_with_playwright(self, pw) -> None:
        # Ensure download directory exists
        download_path = os.path.abspath(settings.download_dir)
        os.makedirs(download_path, exist_ok=True)


        browser = await pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx_kwargs: Dict[str, Any] = {
            "viewport": _VIEWPORT,
            "user_agent": random.choice(_USER_AGENTS),
            "locale": "en-US",
            "timezone_id": random.choice(_TIMEZONES),
            "java_script_enabled": True,
            "accept_downloads": True,
        }
        log.info(
            "Browser context: UA=%s viewport=%s tz=%s",
            ctx_kwargs["user_agent"][-30:],
            ctx_kwargs["viewport"],
            ctx_kwargs["timezone_id"],
        )
        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()
        await _stealth.apply_stealth_async(page)

        self._page = page
        executor = PlaywrightToolExecutor(page, download_dir=download_path)

        try:
            # Restore or seed conversation
            if self.task.messages and self._follow_up:
                self._messages = [{"role": "system", "content": _build_system_prompt()}]
                self._messages.extend(self.task.messages)
                self._messages.append({"role": "user", "content": self._follow_up})
                await self._set_status("running")
                await self._log(f"Continuing task with: {self._follow_up[:100]}")
            else:
                self._messages = [
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user", "content": self.task.prompt},
                ]
                await self._set_status("running")
                await self._log("Agent started.")

            # ---- Main loop (Chat Completions API) -------------------------
            for iteration in range(1, settings.max_agent_iterations + 1):
                await self._log(f"[iter {iteration}] Calling LLM...")

                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=settings.openai_model,
                        messages=self._messages,
                        tools=TOOLS,
                        tool_choice="auto",
                    ),
                    timeout=150,
                )
                msg = response.choices[0].message

                # Track token usage
                if response.usage:
                    self.user.token_usage += response.usage.total_tokens
                    await self.user.save()

                # Append assistant turn
                assistant_turn: Dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content,
                }
                if msg.tool_calls:
                    assistant_turn["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                self._messages.append(assistant_turn)

                # Log assistant reasoning / skill activation
                if msg.content and msg.tool_calls:
                    await self._log(f"Agent: {msg.content[:200]}")

                # No tool calls → model decided the task is done
                if not msg.tool_calls:
                    raw_summary = msg.content or "Task completed."
                    await self._log(f"Done: {raw_summary}")
                    # Capture final screenshot + collect all evidence
                    final_b64 = await self._capture_evidence()
                    if final_b64:
                        self._add_evidence(final_b64)
                    self.task.result_data = {"summary": raw_summary, "complete": True}
                    if self._evidence:
                        self.task.result_data["screenshots"] = self._evidence
                    await self._set_status("completed")
                    break

                # Execute each tool call — EVERY call MUST get a response message
                # Collect deferred messages (screenshots) to append AFTER all tool results
                deferred_messages: List[Dict[str, Any]] = []

                for tc in msg.tool_calls:
                    tool_result = None
                    try:
                        name = tc.function.name
                        try:
                            args = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            args = {}

                        # ── Loop detection ──────────────────────────
                        action_key = f"{name}({json.dumps(args, sort_keys=True)})"
                        self._recent_actions.append(action_key)
                        if len(self._recent_actions) > 20:
                            self._recent_actions = self._recent_actions[-20:]

                        repeat_count = sum(
                            1 for a in self._recent_actions if a == action_key
                        )

                        if repeat_count >= self._LOOP_HARD_LIMIT:
                            await self._log(
                                f"LOOP DETECTED: '{name}' repeated {repeat_count} times."
                            )
                            tool_result = (
                                f"[ERROR:loop_detected] You have repeated '{name}' with "
                                f"the same arguments {repeat_count} times. STOP. "
                                f"Try a completely different strategy or request_human_assistance."
                            )
                        else:
                            if repeat_count >= self._LOOP_THRESHOLD:
                                await self._log(
                                    f"Loop warning: '{name}' repeated {repeat_count} times"
                                )

                            # ── Execute tool ────────────────────────────
                            if name in ("click", "fill", "navigate", "press_key", "select_option"):
                                await asyncio.sleep(random.uniform(0.3, 1.2))

                            await self._log(f"Tool ▶ {name}({json.dumps(args)[:120]})")

                            tool_result = await self._dispatch_tool(
                                executor, tc.id, name, args
                            )

                            if repeat_count >= self._LOOP_THRESHOLD:
                                tool_result += (
                                    f"\n\n⚠ WARNING: You have attempted this same action "
                                    f"{repeat_count} times. Try a different approach."
                                )

                            # Defer screenshot injection until after ALL tool results
                            if name == "take_screenshot":
                                b64 = getattr(executor, "_last_screenshot_b64", None)
                                if b64:
                                    deferred_messages.append({
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": "Here is the current browser screenshot:"},
                                            {"type": "image_url", "image_url": {
                                                "url": f"data:image/png;base64,{b64}",
                                                "detail": "auto",
                                            }},
                                        ],
                                    })
                                    executor._last_screenshot_b64 = None

                            # Only review_and_finalize screenshots go to evidence
                            if name == "review_and_finalize":
                                rb64 = getattr(executor, "_last_screenshot_b64", None)
                                if rb64:
                                    self._add_evidence(rb64)
                                    executor._last_screenshot_b64 = None

                    except Exception as exc:
                        log.warning("Tool dispatch error for %s: %s", tc.id, exc)
                        tool_result = f"[ERROR:internal] Tool execution failed: {exc}"

                    finally:
                        # GUARANTEE: every tool_call_id gets a response
                        await self._log(f"Tool ◀ {(tool_result or '')[:200]}")
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_result or "No result.",
                        })

                # NOW safe to inject deferred messages (after all tool results)
                self._messages.extend(deferred_messages)
            else:
                # Max iterations — request summary
                await self._log("Max iterations reached. Requesting summary...")
                self._messages.append({
                    "role": "user",
                    "content": (
                        "You have reached the maximum number of steps. "
                        "Summarise what you accomplished so far and what remains unfinished. "
                        "Respond with plain text only — no tool calls."
                    ),
                })
                try:
                    final = await self._client.chat.completions.create(
                        model=settings.openai_model,
                        messages=self._messages,
                    )
                    summary = final.choices[0].message.content or "Task incomplete."
                    if final.usage:
                        self.user.token_usage += final.usage.total_tokens
                        await self.user.save()
                except Exception:
                    summary = "Task incomplete — max iterations reached."
                final_b64 = await self._capture_evidence()
                if final_b64:
                    self._add_evidence(final_b64)
                result = {"summary": summary, "complete": False}
                if self._evidence:
                    result["screenshots"] = self._evidence
                self.task.result_data = result
                await self._log(f"Done (incomplete): {summary}")
                await self._set_status("completed")

        except Exception as exc:
            log.exception("AgentRunner fatal error for task %s", self.task.task_id)
            await self._set_status("failed")
            await self._log(f"Fatal error: {exc}")

        finally:
            # Persist conversation history for task continuation
            saved = []
            for m in self._messages:
                role = m.get("role") if isinstance(m, dict) else None
                if role not in ("user", "assistant"):
                    continue
                content = m.get("content") if isinstance(m, dict) else None
                if isinstance(content, str) and content.strip():
                    saved.append({"role": role, "content": content})
            # Always include original prompt even if nothing else saved
            if not saved:
                saved = [{"role": "user", "content": self.task.prompt}]
            self.task.messages = saved
            try:
                await self.task.save()
            except Exception:
                log.warning("Could not save conversation history for task %s", self.task.task_id)

            await browser.close()
            self._page = None

    async def _dispatch_tool(
        self,
        executor: PlaywrightToolExecutor,
        call_id: str,
        name: str,
        args: Dict[str, Any],
    ) -> str:
        if name == "request_human_assistance":
            return await self._handle_hitl(args.get("reason", "Help needed."))
        if name == "request_credentials":
            return await self._handle_credentials(
                args.get("reason", "Credentials needed."),
                args.get("fields", []),
            )
        if name == "ask_user":
            return await self._handle_ask_user(
                args.get("question", ""),
                args.get("mode", "text"),
                args.get("options"),
            )

        method = getattr(executor, name, None)
        if method is None:
            return f"[ERROR:unknown_tool] Unknown tool '{name}'. Check available tool names."
        try:
            return await method(**args)
        except Exception as exc:
            return self._classify_error(name, args, exc)

    @staticmethod
    def _classify_error(tool: str, args: Dict[str, Any], exc: Exception) -> str:
        """Return a structured error so the LLM can make better recovery decisions."""
        err = str(exc).lower()
        selector = args.get("selector", "")

        if "timeout" in err and ("waiting for" in err or "locator" in err):
            return (
                f"[ERROR:element_not_found] '{selector}' not found on page after retries. "
                f"Try: (1) call get_page_content to see current elements, "
                f"(2) use a different selector, (3) scroll down — element may be below fold."
            )
        if "timeout" in err and tool == "navigate":
            return (
                f"[ERROR:navigation_timeout] Page took too long to load. "
                f"Try: (1) retry once, (2) check if the URL is correct, "
                f"(3) load_skill('Navigation Error Recovery')."
            )
        if "net::" in err or "dns" in err:
            return (
                f"[ERROR:network] Network error: {exc}. "
                f"The URL may be unreachable or the domain may not exist."
            )
        if "frame was detached" in err or "execution context" in err:
            return (
                f"[ERROR:page_crashed] Page navigated away or crashed during action. "
                f"Call get_page_content to check current state."
            )
        if "not an htmlselectelement" in err or "not a select" in err:
            return (
                f"[ERROR:wrong_element] '{selector}' is not a <select> element. "
                f"Use click instead of select_option for non-select dropdowns."
            )
        # Generic fallback
        return f"[ERROR:tool_failed] {tool}({selector or ''}) failed: {exc}"

    # ------------------------------------------------------------------
    # Structured output
    # ------------------------------------------------------------------

    # Chat Completions structured output format
    def _add_evidence(self, b64: str) -> bool:
        """Add screenshot to evidence if it's not a duplicate. Returns True if added."""
        h = len(b64)  # simple size-based dedup
        if h in self._evidence_hashes:
            return False
        self._evidence_hashes.add(h)
        self._evidence.append(b64)
        return True

    async def _capture_evidence(self) -> str:
        """Take a final screenshot as verifiable evidence. Returns base64 or empty string."""
        if not self._page:
            return ""
        try:
            raw = await self._page.screenshot(type="png")
            b64 = base64.b64encode(raw).decode()
            # Also save to downloads
            evidence_path = os.path.join(
                os.path.abspath(settings.download_dir),
                f"evidence_{self.task.task_id[:8]}.png",
            )
            os.makedirs(os.path.dirname(evidence_path), exist_ok=True)
            with open(evidence_path, "wb") as f:
                f.write(raw)
            await self._log(f"Evidence screenshot saved: {evidence_path}")
            return b64
        except Exception as exc:
            log.warning("Could not capture evidence screenshot: %s", exc)
            return ""

    async def _handle_ask_user(
        self, question: str, mode: str = "text", options: List[str] | None = None
    ) -> str:
        """Lightweight pause — ask user a question, wait for reply, resume."""
        task_id = self.task.task_id
        await self._set_status("paused")
        await self._log(f"Question: {question}")

        if task_id in ws_queues:
            await ws_queues[task_id].put(
                {
                    "type": "ask_user",
                    "question": question,
                    "mode": mode,
                    "options": options,
                }
            )

        event = asyncio.Event()
        hitl_events[task_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
            answer = hitl_responses.pop(task_id, "")
            await self._set_status("running")
            await self._log(f"User answered: {answer[:100]}")
            # Return both question and answer so LLM keeps context
            return f"You asked: \"{question}\"\nUser answered: \"{answer}\"\nContinue the task using this answer."
        except asyncio.TimeoutError:
            await self._set_status("running")
            await self._log("User did not respond in time.")
            return "User did not respond. Make your best judgement and proceed."
        finally:
            hitl_events.pop(task_id, None)

    async def _handle_hitl(self, reason: str) -> str:
        """Pause the loop, push a HITL request via WebSocket, wait for response."""
        task_id = self.task.task_id
        await self._set_status("paused")
        await self._log(f"HITL requested: {reason}")

        # Take a screenshot to help the operator
        screenshot_b64 = ""
        if self._page:
            try:
                raw = await self._page.screenshot(type="png")
                screenshot_b64 = base64.b64encode(raw).decode()
            except Exception:
                pass

        hitl_data[task_id] = {"reason": reason, "screenshot_base64": screenshot_b64}

        # Signal the WS handler that a HITL request is ready
        if task_id in ws_queues:
            await ws_queues[task_id].put(
                {
                    "type": "hitl_request",
                    "reason": reason,
                    "screenshot_base64": screenshot_b64,
                }
            )

        # Wait for human response (5-minute timeout)
        event = asyncio.Event()
        hitl_events[task_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
            human_input = hitl_responses.pop(task_id, "No response provided.")
            await self._set_status("running")
            await self._log(f"Human responded: {human_input[:100]}")
            return f"You asked for help: \"{reason}\"\nHuman operator responded: \"{human_input}\"\nContinue the task using this response."
        except asyncio.TimeoutError:
            await self._set_status("running")
            await self._log("HITL timed out — continuing without human input.")
            return "Human assistance timed out. Proceeding without input."
        finally:
            hitl_events.pop(task_id, None)
            hitl_data.pop(task_id, None)

    async def _handle_credentials(self, reason: str, fields: List[Dict[str, str]]) -> str:
        """Push a structured credential form to the frontend and wait for response."""
        task_id = self.task.task_id
        await self._set_status("paused")
        await self._log(f"Credentials requested: {reason}")

        screenshot_b64 = ""
        if self._page:
            try:
                raw = await self._page.screenshot(type="png")
                screenshot_b64 = base64.b64encode(raw).decode()
            except Exception:
                pass

        # Push credential request to WebSocket
        if task_id in ws_queues:
            await ws_queues[task_id].put(
                {
                    "type": "credential_request",
                    "reason": reason,
                    "fields": fields,
                    "screenshot_base64": screenshot_b64,
                }
            )

        # Wait for response (5-minute timeout)
        event = asyncio.Event()
        hitl_events[task_id] = event
        try:
            await asyncio.wait_for(event.wait(), timeout=300)
            response_raw = hitl_responses.pop(task_id, "{}")
            await self._set_status("running")
            # Parse structured response
            try:
                creds = json.loads(response_raw) if isinstance(response_raw, str) else response_raw
            except (json.JSONDecodeError, TypeError):
                creds = {"raw": response_raw}
            field_names = [f["name"] for f in fields]
            await self._log(f"Credentials received for: {', '.join(field_names)}")
            return (
                f"You requested credentials for: \"{reason}\"\n"
                f"Fields requested: {', '.join(field_names)}\n"
                f"Operator provided: {json.dumps(creds)}\n"
                f"Now fill the form fields with these values and submit."
            )
        except asyncio.TimeoutError:
            await self._set_status("running")
            await self._log("Credential request timed out.")
            return "Credential request timed out. Use request_human_assistance as fallback."
        finally:
            hitl_events.pop(task_id, None)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _set_status(self, status: str) -> None:
        self.task.status = status
        await self.task.save()
        # Push status update to any connected WebSocket
        task_id = self.task.task_id
        if task_id in ws_queues:
            await ws_queues[task_id].put(
                {
                    "type": "status",
                    "status": status,
                    "logs": list(self.task.logs),
                }
            )

    async def _log(self, message: str) -> None:
        self.task.logs.append(message)
        await self.task.save()
        task_id = self.task.task_id
        if task_id in ws_queues:
            await ws_queues[task_id].put(
                {
                    "type": "log",
                    "message": message,
                    "status": self.task.status,
                    "logs": list(self.task.logs),
                }
            )
