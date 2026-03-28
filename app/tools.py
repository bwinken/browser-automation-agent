"""
OpenAI tool schemas and the Playwright-backed executor.

Each schema entry maps 1-to-1 with a method on PlaywrightToolExecutor.
No LangChain / browser-use abstractions — pure openai + playwright.
"""
import asyncio
import base64
import json
import logging
import random
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Navigate the browser to a URL and wait for the page to load.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Absolute URL to navigate to (include https://).",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": (
                "Click an element. Accepts CSS selector, text content, or button/link name. "
                "Auto-retries with fallbacks (CSS → text match → role match). "
                "Set hold_ms for 'press and hold' verification buttons (e.g. hold_ms=3000)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector, visible text, or button/link name.",
                    },
                    "hold_ms": {
                        "type": "integer",
                        "description": "Hold duration in ms for press-and-hold buttons. Default 0 (normal click). Use 2000-5000 for 'hold to verify' challenges.",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_position",
            "description": (
                "Click at exact x,y pixel coordinates on the page. "
                "Use this when CSS selectors don't work — for calendar grids, "
                "canvas elements, map pins, or custom widgets. "
                "Combine with take_screenshot to identify coordinates visually."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate in pixels from the left edge of the viewport.",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate in pixels from the top edge of the viewport.",
                    },
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Clear and type text into an input or textarea element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the input element.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to type into the element.",
                    },
                },
                "required": ["selector", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_javascript",
            "description": (
                "Advanced fallback: execute JavaScript in the browser. "
                "Prefer native tools first (click, fill, select_option). "
                "Use this only when native tools fail — e.g. setting date inputs, "
                "extracting complex data, or triggering JS-only actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": "JavaScript expression to evaluate (must be an expression, not a statement block).",
                    }
                },
                "required": ["script"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_content",
            "description": (
                "Return a concise, LLM-friendly snapshot of the current page: "
                "title, URL, and up to 80 interactive/heading elements with their "
                "labels, hrefs, and input names. Call this after navigating to "
                "understand page structure before interacting."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": (
                "Take a screenshot of the current browser viewport and return it as "
                "a base64-encoded PNG. Use this to visually verify page state, check "
                "what the page looks like, or debug layout issues. "
                "Set evidence=true to save this screenshot as verifiable evidence "
                "for the final report (use for data pages you extracted info from)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": "boolean",
                        "description": "If true, save this screenshot as evidence for the final report. Use when capturing data pages.",
                        "default": False,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for_element",
            "description": (
                "Wait for an element matching the CSS selector to appear in the DOM. "
                "Use this before interacting with elements on dynamically-loaded pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to wait for.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max wait time in milliseconds. Default 10000.",
                    },
                },
                "required": ["selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": (
                "Scroll the page up or down by a specified amount. "
                "Use 'down' to reveal content below the fold, 'up' to go back."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Scroll direction.",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Pixels to scroll. Default 600.",
                    },
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": (
                "Press a keyboard key or combo. Examples: 'Enter', 'Escape', 'Tab', "
                "'ArrowDown', 'Control+a', 'Shift+Enter'. "
                "Aliases auto-fixed: Ctrl→Control, Cmd→Meta, Return→Enter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Key to press (e.g. 'Enter', 'Escape', 'Tab', 'ArrowDown').",
                    },
                    "selector": {
                        "type": "string",
                        "description": "Optional CSS selector to focus before pressing. If omitted, key is pressed on the currently focused element.",
                    },
                },
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_option",
            "description": (
                "Select an option from a <select> dropdown element."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the <select> element.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Option value or visible label to select.",
                    },
                },
                "required": ["selector", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "download_file",
            "description": (
                "Download a file. Two modes: "
                "(1) Provide a 'url' to download directly (best for direct file links like .pdf, .csv). "
                "(2) Provide a 'selector' to click a download button/link and capture the download. "
                "Returns the saved file path, name, and size."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Direct file URL to download. Use this when the URL points directly to a file.",
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of a download link/button to click. Use when download is triggered by a button.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max wait time in milliseconds. Default 30000.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "load_skill",
            "description": (
                "Load a skill playbook by name. Call this when you recognise a "
                "trigger condition from the Available Skills list. Returns the "
                "step-by-step instructions to follow."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill name (e.g. 'Cookie Consent', 'CAPTCHA Handling', 'Search Pattern').",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solve_captcha",
            "description": (
                "Auto-detect and solve a CAPTCHA on the current page using a "
                "third-party solving service. Supports reCAPTCHA v2/v3, hCaptcha, "
                "and Cloudflare Turnstile. Call this BEFORE request_human_assistance "
                "when you encounter a CAPTCHA. Returns the result or an error."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user a follow-up question and wait for their reply. "
                "Use this when you need clarification to proceed. The task stays "
                "running — the agent resumes after the user responds. "
                "Set mode to control the input type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user.",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["text", "single_select", "multi_select"],
                        "description": "Input mode. 'text' for free-text, 'single_select' for pick one, 'multi_select' for pick many. Default: 'text'.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Choices for single_select / multi_select modes (e.g. ['Red', 'Blue', 'Green']).",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_credentials",
            "description": (
                "Pause execution and ask the operator to provide login credentials "
                "or other sensitive input via structured form fields. Use this when "
                "you detect a login form. Specify each field the operator needs to "
                "fill (email, password, OTP, etc). Returns the filled values as JSON."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why credentials are needed (e.g. 'Login required for accounts.google.com').",
                    },
                    "fields": {
                        "type": "array",
                        "description": "List of input fields the operator needs to fill.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "description": "Field key (e.g. 'email', 'password', 'otp').",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Display label (e.g. 'Email address', 'Password').",
                                },
                                "type": {
                                    "type": "string",
                                    "enum": ["text", "password", "email", "number"],
                                    "description": "Input type. Use 'password' for sensitive fields.",
                                },
                            },
                            "required": ["name", "label", "type"],
                        },
                    },
                },
                "required": ["reason", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_and_finalize",
            "description": (
                "REQUIRED before finishing any task. Takes a final screenshot, compares "
                "it with your planned summary, and returns whether they match. "
                "Call this AFTER collecting all results but BEFORE writing your final summary. "
                "If the review finds mismatches, fix them before concluding."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "planned_summary": {
                        "type": "string",
                        "description": "The summary you plan to give the user. The review will verify this matches the screenshot.",
                    },
                },
                "required": ["planned_summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_human_assistance",
            "description": (
                "Emergency escalation: pause and send screenshot + reason to operator. "
                "Use ONLY when you are truly stuck (unsolvable CAPTCHA, blocked page, "
                "critical error). For simple questions use ask_user. "
                "For credentials use request_credentials. Timeout: 5 minutes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Clear explanation of why human help is needed.",
                    }
                },
                "required": ["reason"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Playwright tool executor
# ---------------------------------------------------------------------------

_GET_PAGE_CONTENT_JS = """
() => {
    const trunc = (s, n) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, n);
    const title = document.title;
    const url   = location.href;

    const SELECTOR = [
        'a[href]', 'button', 'input:not([type="hidden"])',
        'select', 'textarea', 'h1', 'h2', 'h3', 'h4',
        '[role="button"]', '[role="link"]', '[role="textbox"]'
    ].join(',');

    const elements = [];
    document.querySelectorAll(SELECTOR).forEach((el, i) => {
        if (i >= 80) return;
        const item = { tag: el.tagName.toLowerCase() };
        if (el.id)          item.id          = el.id;
        if (el.name)        item.name        = el.name;
        if (el.type)        item.type        = el.type;
        if (el.href)        item.href        = trunc(el.href, 120);
        if (el.placeholder) item.placeholder = el.placeholder;
        const txt = trunc(el.innerText, 120);
        if (txt)            item.text        = txt;
        if (Object.keys(item).length > 1) elements.push(item);
    });

    return JSON.stringify({ title, url, elements }, null, 2);
}
"""


_PAGE_BRIEF_JS = """
() => {
    const title = document.title;
    const url = location.href;
    const buttons = document.querySelectorAll('button, [role="button"]').length;
    const links = document.querySelectorAll('a[href]').length;
    const inputs = document.querySelectorAll('input:not([type="hidden"]), select, textarea').length;
    const hasModal = !!document.querySelector('[class*="modal"][style*="display"], .overlay:not([style*="none"]), [role="dialog"]');
    return `[Page: ${title} | ${url} | ${buttons} buttons, ${links} links, ${inputs} inputs${hasModal ? ' | ⚠ MODAL/OVERLAY visible' : ''}]`;
}
"""


class PlaywrightToolExecutor:
    """Wraps a Playwright Page and exposes each tool as an async method."""

    def __init__(self, page: Page, download_dir: str = "downloads") -> None:
        self._page = page
        self._download_dir = download_dir

    # ── Page state helpers ────────────────────────────────────────────

    async def _page_brief(self) -> str:
        """Lightweight one-line page summary (URL, title, element counts)."""
        try:
            return await self._page.evaluate(_PAGE_BRIEF_JS)
        except Exception:
            return f"[Page: {self._page.url}]"

    async def _wait_for_stable(self, timeout: int = 2_000):
        """Wait for the page to settle after an action (navigation or AJAX)."""
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except PlaywrightTimeout:
            pass
        try:
            await self._page.wait_for_load_state("networkidle", timeout=800)
        except PlaywrightTimeout:
            pass

    async def _retry(self, coro_fn, retries=2, delay=1.0):
        """Retry an async callable with exponential backoff."""
        last_exc = None
        for attempt in range(retries + 1):
            try:
                return await coro_fn()
            except PlaywrightTimeout as exc:
                last_exc = exc
                if attempt < retries:
                    log.info("Retry %d/%d after timeout: %s", attempt + 1, retries, exc)
                    await asyncio.sleep(delay * (attempt + 1))
        raise last_exc

    async def _find_element(self, selector: str, timeout: int = 5_000):
        """Try the given selector; if it fails, try text-based and role-based fallbacks."""
        try:
            loc = self._page.locator(selector).first
            await loc.wait_for(state="visible", timeout=timeout)
            return loc
        except PlaywrightTimeout:
            pass

        text_loc = self._page.get_by_text(selector, exact=False).first
        try:
            await text_loc.wait_for(state="visible", timeout=1_500)
            log.info("Selector fallback: found by text '%s'", selector)
            return text_loc
        except PlaywrightTimeout:
            pass

        for role in ["button", "link"]:
            role_loc = self._page.get_by_role(role, name=selector).first
            try:
                await role_loc.wait_for(state="visible", timeout=1_000)
                log.info("Selector fallback: found by role=%s name='%s'", role, selector)
                return role_loc
            except PlaywrightTimeout:
                continue

        raise PlaywrightTimeout(f"Element not found: '{selector}' (tried CSS, text, and role fallbacks)")

    # ── Auto-dismiss overlays ─────────────────────────────────────────

    async def _try_dismiss_overlay(self) -> str:
        """Try to dismiss cookie banners and common overlays. Returns what was dismissed."""
        await asyncio.sleep(1)  # wait for overlays to render

        # Strategy 0: Press Escape first — closes most modals/popups instantly
        has_overlay = await self._page.evaluate("""
        () => !!document.querySelector(
            '[role="dialog"], [class*="modal"]:not([style*="none"]), ' +
            '[class*="overlay"]:not([style*="none"]), [class*="popup"]:not([style*="none"])'
        )
        """)
        if has_overlay:
            await self._page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
            still_overlay = await self._page.evaluate("""
            () => !!document.querySelector(
                '[role="dialog"], [class*="modal"]:not([style*="none"]), ' +
                '[class*="overlay"]:not([style*="none"]), [class*="popup"]:not([style*="none"])'
            )
            """)
            if not still_overlay:
                return "overlay dismissed via Escape"

        # JS: find and click common accept/close buttons
        dismissed = await self._page.evaluate("""
        () => {
            const dismissed = [];

            // Strategy 1: Cookie consent buttons (multilingual)
            const cookieTexts = [
                // English
                'accept all', 'accept cookies', 'i agree', 'agree',
                'got it', 'ok', 'allow all', 'allow cookies', 'consent',
                'accept', 'yes, i agree', 'agree and proceed', 'continue',
                // Chinese (Traditional + Simplified)
                '同意', '接受', '確定', '確認', '我同意', '全部接受',
                '同意並繼續', '接受所有', '允許', '了解', '知道了',
                '同意所有cookies', '接受cookie',
                // Japanese
                '同意する', 'すべて許可', '承諾',
                // Korean
                '동의', '모두 허용', '수락',
                // German / French / Spanish
                'akzeptieren', 'alle akzeptieren', 'zustimmen',
                'accepter', 'tout accepter', "j'accepte",
                'aceptar', 'aceptar todo',
            ];
            const allButtons = [...document.querySelectorAll('button, a[role="button"], [class*="btn"], [class*="cookie"] a, [class*="consent"] a')];
            for (const btn of allButtons) {
                const txt = (btn.innerText || '').trim().toLowerCase();
                if (cookieTexts.some(ct => txt === ct || txt.startsWith(ct))) {
                    try { btn.click(); dismissed.push('cookie: ' + txt); break; }
                    catch(e) {}
                }
            }

            // Strategy 2: Common cookie banner selectors
            if (!dismissed.length) {
                const selectors = [
                    '#onetrust-accept-btn-handler',
                    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                    '.cc-accept', '.cc-btn.cc-dismiss',
                    '[data-testid="cookie-accept"]',
                    '#cookie-accept', '#accept-cookies',
                    '.cookie-consent-accept', '.js-cookie-accept',
                    '#gdpr-accept', '.gdpr-accept',
                    '[aria-label="Accept cookies"]',
                    '[aria-label="Close"]'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.offsetParent !== null) {
                        try { el.click(); dismissed.push('cookie: ' + sel); break; }
                        catch(e) {}
                    }
                }
            }

            // Strategy 3: Notification / newsletter / push prompts
            const notifDismiss = document.querySelector(
                '[class*="notification"] [class*="close"], ' +
                '[class*="push-prompt"] [class*="close"], ' +
                '[class*="newsletter"] [class*="close"]'
            );
            if (notifDismiss && notifDismiss.offsetParent !== null) {
                try { notifDismiss.click(); dismissed.push('notification popup'); }
                catch(e) {}
            }

            // Strategy 4: Sign-in / login prompts & promo overlays
            const promoSelectors = [
                '[aria-label="Dismiss sign-in info."]',       // Booking.com specific
                '[class*="signin"] [class*="close"]',
                '[class*="sign-in"] [class*="close"]',
                '[class*="login-prompt"] [class*="close"]',
                '[class*="promo"] [class*="close"]',
                '[class*="modal"] [class*="dismiss"]',
                '[class*="popup"] [class*="close"]',
                '[data-testid="dismissButton"]',
                'button[aria-label="Close"]',
            ];
            for (const sel of promoSelectors) {
                const el = document.querySelector(sel);
                if (el && el.offsetParent !== null) {
                    try { el.click(); dismissed.push('promo/signin: ' + sel); break; }
                    catch(e) {}
                }
            }

            // Strategy 5: Generic visible modals/overlays — try close/X buttons
            if (!dismissed.length) {
                const modals = document.querySelectorAll('[role="dialog"], [class*="modal"], [class*="overlay"]');
                for (const modal of modals) {
                    if (!modal.offsetParent) continue;
                    const closeBtn = modal.querySelector(
                        'button[aria-label="Close"], [class*="close"], button:has(svg), ' +
                        'button:first-child, [class*="dismiss"]'
                    );
                    if (closeBtn) {
                        try { closeBtn.click(); dismissed.push('modal close button'); break; }
                        catch(e) {}
                    }
                }
            }

            return dismissed.join(', ');
        }
        """)
        return dismissed or ""

    # ── Core tools ────────────────────────────────────────────────────

    async def navigate(self, url: str) -> str:
        async def _go():
            resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            status = resp.status if resp else "unknown"
            return f"Navigated to {self._page.url} (HTTP {status})"
        result = await self._retry(_go)
        dismissed = await self._try_dismiss_overlay()
        if dismissed:
            result += f"\n(Auto-dismissed: {dismissed})"
        brief = await self._page_brief()
        return f"{result}\n{brief}"

    async def click(self, selector: str, hold_ms: int = 0) -> str:
        loc = await self._find_element(selector)

        if hold_ms > 0:
            # Human-like press-and-hold (for "hold to verify" challenges)
            box = await loc.bounding_box()
            if box:
                # Target: center with small random offset
                cx = box["x"] + box["width"] / 2 + random.uniform(-3, 3)
                cy = box["y"] + box["height"] / 2 + random.uniform(-2, 2)

                # Approach: move from a nearby point to the button (not teleport)
                start_x = cx + random.uniform(-80, 80)
                start_y = cy + random.uniform(-40, 40)
                await self._page.mouse.move(start_x, start_y)
                await asyncio.sleep(random.uniform(0.1, 0.3))

                # Curve toward button in 3-5 small steps
                steps = random.randint(3, 5)
                for i in range(1, steps + 1):
                    t = i / steps
                    mx = start_x + (cx - start_x) * t + random.uniform(-2, 2)
                    my = start_y + (cy - start_y) * t + random.uniform(-1, 1)
                    await self._page.mouse.move(mx, my)
                    await asyncio.sleep(random.uniform(0.02, 0.06))

                # Press, hold with slight jitter, release
                await self._page.mouse.down()
                hold_time = hold_ms / 1000 + random.uniform(-0.3, 0.5)
                # Tiny mouse movement during hold (humans can't hold perfectly still)
                elapsed = 0.0
                while elapsed < hold_time:
                    jitter_wait = random.uniform(0.3, 0.8)
                    await asyncio.sleep(min(jitter_wait, hold_time - elapsed))
                    elapsed += jitter_wait
                    await self._page.mouse.move(
                        cx + random.uniform(-1.5, 1.5),
                        cy + random.uniform(-1, 1),
                    )
                await self._page.mouse.up()
            else:
                await loc.click(delay=hold_ms, timeout=10_000)
        else:
            try:
                await self._retry(lambda: loc.click(timeout=5_000))
            except Exception as exc:
                if "intercepts pointer events" in str(exc):
                    err_msg = str(exc)
                    # Check if blocked by footer/header (not a popup)
                    is_footer = "footer" in err_msg.lower() or "header" in err_msg.lower() or "nav" in err_msg.lower()

                    if is_footer:
                        # Scroll element into center of viewport to avoid sticky footer/header
                        log.info("Click blocked by footer/header on '%s', scrolling into view", selector)
                        await loc.scroll_into_view_if_needed()
                        await self._page.evaluate("window.scrollBy(0, -200)")
                        await asyncio.sleep(0.3)
                        try:
                            await loc.click(timeout=3_000)
                        except Exception:
                            await loc.click(force=True, timeout=2_000)
                    else:
                        # Popup/overlay — try Escape → dismiss → force
                        log.info("Click intercepted on '%s', trying Escape first", selector)
                        await self._page.keyboard.press("Escape")
                        await asyncio.sleep(0.5)
                        try:
                            await loc.click(timeout=3_000)
                        except Exception:
                            log.info("Escape didn't help, running overlay dismissal")
                            await self._try_dismiss_overlay()
                            try:
                                await loc.click(timeout=3_000)
                            except Exception:
                                await loc.click(force=True, timeout=2_000)
                else:
                    raise

        await self._wait_for_stable()
        brief = await self._page_brief()
        return f"Clicked '{selector}'\n{brief}"

    async def click_position(self, x: int, y: int) -> str:
        await self._page.mouse.click(x, y)
        await self._wait_for_stable()
        brief = await self._page_brief()
        return f"Clicked at ({x}, {y})\n{brief}"

    async def fill(self, selector: str, text: str) -> str:
        loc = await self._find_element(selector)
        await self._retry(lambda: loc.fill(text, timeout=10_000))
        # Auto-handle autocomplete dropdown
        await asyncio.sleep(0.8)
        dropdown = await self._page.query_selector(
            "[role='listbox'], [class*='autocomplete'], [class*='suggestion'], "
            "[class*='dropdown'] ul, [class*='search-result'], [data-testid*='suggestion']"
        )
        if dropdown and await dropdown.is_visible():
            # Try to click the first suggestion
            first_option = await self._page.query_selector(
                "[role='listbox'] [role='option'], "
                "[class*='autocomplete'] li, [class*='suggestion'] li, "
                "[data-testid*='suggestion']"
            )
            if first_option and await first_option.is_visible():
                opt_text = (await first_option.inner_text()).strip()[:80]
                await first_option.click(timeout=3_000)
                await self._wait_for_stable()
                brief = await self._page_brief()
                return (
                    f"Filled '{selector}' with text. "
                    f"Auto-selected suggestion: '{opt_text}'. "
                    f"If wrong, clear and retry.\n{brief}"
                )
            else:
                await self._page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
                return (
                    f"Filled '{selector}' with text. "
                    f"Autocomplete appeared but no clickable option found. "
                    f"Pressed Escape to dismiss."
                )
        brief = await self._page_brief()
        return f"Filled '{selector}' with text\n{brief}"

    async def evaluate_javascript(self, script: str) -> str:
        result: Any = await self._page.evaluate(script)
        try:
            return json.dumps(result)
        except (TypeError, ValueError):
            return str(result)

    async def get_page_content(self) -> str:
        return await self._page.evaluate(_GET_PAGE_CONTENT_JS)


    async def take_screenshot(self, evidence: bool = False) -> str:
        raw = await self._page.screenshot(type="png")
        b64 = base64.b64encode(raw).decode()
        # Store for agent to inject as vision message
        self._last_screenshot_b64 = b64
        # Flag for agent loop to collect as evidence
        self._is_evidence_screenshot = evidence
        tag = " [EVIDENCE SAVED]" if evidence else ""
        return f"Screenshot captured ({len(raw)} bytes).{tag} Image is now visible to you — describe what you see."

    async def wait_for_element(self, selector: str, timeout: int = 10_000) -> str:
        await self._page.wait_for_selector(selector, timeout=timeout)
        return f"Element '{selector}' is now visible."

    async def scroll(self, direction: str, amount: int = 600) -> str:
        delta = amount if direction == "down" else -amount
        await self._page.evaluate(f"window.scrollBy(0, {delta})")
        scroll_y = await self._page.evaluate("window.scrollY")
        return f"Scrolled {direction} by {amount}px. Current scrollY: {scroll_y}"

    # Common key aliases that LLMs get wrong
    _KEY_ALIASES = {
        "Ctrl": "Control", "ctrl": "Control",
        "Cmd": "Meta", "cmd": "Meta", "Command": "Meta",
        "Return": "Enter", "return": "Enter",
        "Del": "Delete", "del": "Delete",
        "Esc": "Escape", "esc": "Escape",
        "Up": "ArrowUp", "Down": "ArrowDown",
        "Left": "ArrowLeft", "Right": "ArrowRight",
        "Space": " ", "space": " ",
    }

    async def press_key(self, key: str, selector: str | None = None) -> str:
        # Fix common LLM mistakes: "Ctrl+A" → "Control+a"
        parts = key.split("+")
        fixed = [self._KEY_ALIASES.get(p, p) for p in parts]
        key = "+".join(fixed)

        if selector:
            await self._page.focus(selector, timeout=5_000)
        await self._page.keyboard.press(key)
        await self._wait_for_stable()
        brief = await self._page_brief()
        return f"Pressed '{key}'" + (f" on '{selector}'" if selector else "") + f"\n{brief}"

    async def select_option(self, selector: str, value: str) -> str:
        selected = await self._page.select_option(selector, label=value, timeout=10_000)
        if not selected:
            selected = await self._page.select_option(selector, value=value, timeout=10_000)
        await self._wait_for_stable()
        brief = await self._page_brief()
        return f"Selected '{value}' in '{selector}'\n{brief}"

    async def download_file(
        self, url: str | None = None, selector: str | None = None, timeout: int = 30_000
    ) -> str:
        import os
        import urllib.parse

        if url:
            # Direct URL download — use httpx to fetch the file
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout / 1000) as client:
                resp = await client.get(url)
                resp.raise_for_status()
            # Derive filename from URL or Content-Disposition header
            cd = resp.headers.get("content-disposition", "")
            if "filename=" in cd:
                filename = cd.split("filename=")[-1].strip('" ')
            else:
                filename = os.path.basename(urllib.parse.urlparse(url).path) or "download"
            save_path = os.path.join(self._download_dir, filename)
            with open(save_path, "wb") as f:
                f.write(resp.content)
        elif selector:
            # Click-triggered download — use Playwright expect_download
            async with self._page.expect_download(timeout=timeout) as download_info:
                await self._page.click(selector, timeout=10_000)
            download = await download_info.value
            filename = download.suggested_filename or "download"
            save_path = os.path.join(self._download_dir, filename)
            await download.save_as(save_path)
        else:
            return "Error: provide either 'url' or 'selector' parameter."

        size = os.path.getsize(save_path)
        size_str = f"{size / 1024:.1f} KB" if size < 1_048_576 else f"{size / 1_048_576:.1f} MB"
        download_url = f"/downloads/{filename}"
        return (
            f"Downloaded: {filename} ({size_str})\n"
            f"Download URL: {download_url}\n"
            f"IMPORTANT: Include this download link in your final summary so the user can access the file. "
            f"Never expose internal file paths to the user."
        )

    async def review_and_finalize(self, planned_summary: str) -> str:
        """Take screenshot, return it for LLM vision review against planned summary."""
        raw = await self._page.screenshot(type="png")
        b64 = base64.b64encode(raw).decode()
        self._last_screenshot_b64 = b64
        # Store separately for evidence collection (not cleared by take_screenshot deferred logic)
        self._review_screenshot_b64 = b64
        # Also get page text for cross-check
        try:
            page_data = await self._page.evaluate(_GET_PAGE_CONTENT_JS)
        except Exception:
            page_data = ""
        return (
            f"REVIEW: Screenshot captured. The image is now visible to you.\n"
            f"Your planned summary:\n---\n{planned_summary}\n---\n"
            f"Page content snapshot:\n{page_data[:1500]}\n\n"
            f"STRICT VERIFICATION — check EACH item:\n"
            f"1. NUMBERS: every price, temperature, percentage, count in your summary must EXACTLY "
            f"match the screenshot/page content. If wrong, fix it.\n"
            f"2. NAMES: every company, product, paper title must match spelling from the source.\n"
            f"3. COUNT: if the task asked for N results, confirm you have exactly N.\n"
            f"4. RELEVANCE: each item must actually match the search query. If the user searched "
            f"for 'AirPods Pro 2', a phone case is NOT a valid result — remove it.\n"
            f"5. DATES/YEARS: if you cited a year, citation count, or date, verify it matches exactly.\n"
            f"6. COVERAGE: does your screenshot show ALL items mentioned in the summary? "
            f"If some items are off-screen, note which ones lack visual evidence.\n\n"
            f"If ANY mismatch: state what's wrong, correct it, output REVISED summary.\n"
            f"If all correct: confirm 'All verified' and output the final summary."
        )

    async def load_skill(self, name: str) -> str:
        from app.skills import get_skill
        result = get_skill(name)
        if result:
            return result
        return f"Skill '{name}' not found. Check the Available Skills list for valid names."

    async def solve_captcha(self) -> str:
        from app.captcha import solve
        # API key is optional — strategies 1 & 2 (wait + click) work without it
        result = await solve(self._page, settings.twocaptcha_api_key)
        return result
