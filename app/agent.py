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
from typing import Any, Dict, List

from playwright_stealth import Stealth

_stealth = Stealth()

from openai import AsyncOpenAI
from playwright.async_api import async_playwright

from app.config import settings
from app.models import BrowserState, Task, User
from app.shared import hitl_data, hitl_events, hitl_responses, ws_queues
from app.tools import TOOLS, PlaywrightToolExecutor

log = logging.getLogger(__name__)

# Global semaphore — limits simultaneous Playwright instances across all tasks.
_browser_semaphore = asyncio.Semaphore(settings.max_concurrent_browsers)

_SYSTEM_PROMPT = """\
You are a headless-browser automation agent. Use the provided tools to \
complete the user's task step-by-step.

Guidelines:
- Always call get_page_content after navigating to understand the page.
- Prefer CSS selectors with id or name attributes for reliability.
- If an action fails, read the error and try an alternative selector or approach.
- When you encounter a CAPTCHA, login wall, or need a human decision, call \
  request_human_assistance immediately.
- When the task is fully complete, respond with a plain text summary \
  (no tool call). That message ends the loop.
"""


class AgentRunner:
    """Runs the full agent loop for a single Task document."""

    def __init__(self, task: Task, user: User) -> None:
        self.task = task
        self.user = user
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._messages: List[Dict[str, Any]] = []
        self._page = None  # set inside run() for HITL screenshot access

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
        # Load persisted browser state (cookies / localStorage) if present
        browser_state_doc = await BrowserState.find_one(
            BrowserState.user_id == self.user.id
        )
        storage_state = browser_state_doc.state_json if browser_state_doc else None

        browser = await pw.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        ctx_kwargs: Dict[str, Any] = {
            "viewport": {"width": 1280, "height": 800},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
            "java_script_enabled": True,
        }
        if storage_state:
            ctx_kwargs["storage_state"] = storage_state

        context = await browser.new_context(**ctx_kwargs)
        page = await context.new_page()

        # Apply stealth patches — hides navigator.webdriver and other bot signals
        await _stealth.apply_stealth_async(page)

        self._page = page
        executor = PlaywrightToolExecutor(page)

        try:
            await self._set_status("running")
            await self._log("Agent started.")

            # Seed conversation
            self._messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self.task.prompt},
            ]

            # ---- Main loop ------------------------------------------------
            for iteration in range(1, settings.max_agent_iterations + 1):
                await self._log(f"[iter {iteration}] Calling LLM...")

                response = await self._client.chat.completions.create(
                    model=settings.openai_model,
                    messages=self._messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )
                msg = response.choices[0].message

                # Append assistant turn to history (serialised manually to
                # avoid Pydantic model serialisation edge-cases)
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

                # No tool calls → model decided the task is done
                if not msg.tool_calls:
                    summary = msg.content or "Task completed."
                    await self._log(f"Done: {summary}")
                    self.task.result_data = {"summary": summary}
                    await self._set_status("completed")
                    break

                # Execute each tool call and collect results
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    await self._log(f"Tool ▶ {name}({json.dumps(args)[:120]})")

                    tool_result = await self._dispatch_tool(
                        executor, tc.id, name, args
                    )
                    await self._log(f"Tool ◀ {tool_result[:200]}")

                    self._messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": tool_result,
                        }
                    )
            else:
                await self._set_status("failed")
                await self._log("Max iterations reached without completion.")

        except Exception as exc:
            log.exception("AgentRunner fatal error for task %s", self.task.task_id)
            await self._set_status("failed")
            await self._log(f"Fatal error: {exc}")

        finally:
            # Persist browser state back to MongoDB
            try:
                new_state = await context.storage_state()
                if browser_state_doc:
                    browser_state_doc.state_json = new_state
                    await browser_state_doc.save()
                else:
                    await BrowserState(
                        user_id=self.user.id, state_json=new_state
                    ).insert()
            except Exception:
                log.warning("Could not save browser state for user %s", self.user.id)

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

        method = getattr(executor, name, None)
        if method is None:
            return f"Error: unknown tool '{name}'"
        try:
            return await method(**args)
        except Exception as exc:
            return f"Error executing {name}: {exc}"

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
            return f"Human operator responded: {human_input}"
        except asyncio.TimeoutError:
            await self._set_status("running")
            await self._log("HITL timed out — continuing without human input.")
            return "Human assistance timed out. Proceeding without input."
        finally:
            hitl_events.pop(task_id, None)
            hitl_data.pop(task_id, None)

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
