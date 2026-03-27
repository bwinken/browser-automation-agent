"""
Multi-strategy CAPTCHA solver.

Strategy chain (tried in order):
1. Wait & check    — Cloudflare challenges sometimes auto-resolve after a few seconds
2. Click checkbox  — reCAPTCHA v2 / Turnstile checkbox click (often enough with stealth)
3. 2Captcha API    — token-based solving via third-party service
4. Submit form     — after token injection, find and click the submit button
5. Page reload     — some sites accept the token only after navigation

If all strategies fail, returns a detailed error so the agent can fall back to HITL.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

_API_BASE = "https://api.2captcha.com"

# ---------------------------------------------------------------------------
# Detection — expanded to catch more CAPTCHA types
# ---------------------------------------------------------------------------

_DETECT_JS = """
() => {
    const result = { type: null, sitekey: null, details: [] };

    // Cloudflare challenge page (full-page interstitial, no sitekey)
    if (document.title.includes('Just a moment') ||
        document.querySelector('#challenge-running, #challenge-stage, .cf-browser-verification')) {
        result.type = 'cloudflare_challenge';
        result.details.push('Cloudflare interstitial page detected');
        return result;
    }

    // Cloudflare Turnstile widget
    const turnstile = document.querySelector('.cf-turnstile, [data-turnstile-sitekey]');
    if (turnstile) {
        result.type = 'turnstile';
        result.sitekey = turnstile.getAttribute('data-sitekey') || turnstile.getAttribute('data-turnstile-sitekey');
        return result;
    }
    // Turnstile iframe
    const tsIframe = document.querySelector('iframe[src*="challenges.cloudflare.com"]');
    if (tsIframe) {
        result.type = 'turnstile';
        const m = tsIframe.src.match(/[?&]k=([^&]+)/);
        if (m) result.sitekey = m[1];
        result.details.push('Detected via iframe');
        return result;
    }

    // reCAPTCHA v2 / v3
    const recap = document.querySelector('.g-recaptcha, [data-sitekey]');
    if (recap) {
        result.sitekey = recap.getAttribute('data-sitekey');
        const isV3 = recap.getAttribute('data-size') === 'invisible'
                   || !!document.querySelector('script[src*="recaptcha/api.js?render="]');
        result.type = isV3 ? 'recaptchav3' : 'recaptchav2';
        return result;
    }
    const recapIframe = document.querySelector('iframe[src*="recaptcha"]');
    if (recapIframe) {
        result.type = 'recaptchav2';
        const m = recapIframe.src.match(/[?&]k=([^&]+)/);
        if (m) result.sitekey = m[1];
        result.details.push('Detected via iframe');
        return result;
    }

    // hCaptcha
    const hcap = document.querySelector('.h-captcha, [data-hcaptcha-sitekey]');
    if (hcap) {
        result.type = 'hcaptcha';
        result.sitekey = hcap.getAttribute('data-sitekey') || hcap.getAttribute('data-hcaptcha-sitekey');
        return result;
    }
    const hcapIframe = document.querySelector('iframe[src*="hcaptcha"]');
    if (hcapIframe) {
        result.type = 'hcaptcha';
        const m = hcapIframe.src.match(/sitekey=([^&]+)/);
        if (m) result.sitekey = m[1];
        return result;
    }

    // Generic bot detection pages
    if (document.body?.innerText.match(/verify you are human|are you a robot|access denied|blocked/i)) {
        result.type = 'generic_block';
        result.details.push('Bot detection text found: ' + document.title);
        return result;
    }

    return null;
}
"""

# 2Captcha task type mapping
_TASK_TYPE_MAP = {
    "recaptchav2": "RecaptchaV2TaskProxyless",
    "recaptchav3": "RecaptchaV3TaskProxyless",
    "hcaptcha":    "HCaptchaTaskProxyless",
    "turnstile":   "TurnstileTaskProxyless",
}


async def detect(page: Page) -> Optional[Dict[str, Any]]:
    """Detect CAPTCHA type, sitekey, and details."""
    try:
        return await page.evaluate(_DETECT_JS)
    except Exception as exc:
        log.debug("CAPTCHA detection error: %s", exc)
        return None


async def solve(page: Page, api_key: str) -> str:
    """
    Multi-strategy CAPTCHA solver. Returns a status message.
    Tries strategies in order until one works.
    """
    info = await detect(page)
    if not info or not info.get("type"):
        return "No CAPTCHA detected on this page."

    captcha_type = info["type"]
    sitekey = info.get("sitekey")
    strategies_tried: List[str] = []

    log.info("CAPTCHA detected: type=%s sitekey=%s url=%s", captcha_type, sitekey, page.url)

    # ── Strategy 1: Wait for auto-resolve (Cloudflare challenges) ────
    if captcha_type in ("cloudflare_challenge", "turnstile"):
        strategies_tried.append("wait_auto_resolve")
        resolved = await _strategy_wait(page)
        if resolved:
            return f"CAPTCHA ({captcha_type}) auto-resolved after waiting. Strategy: wait."

    # ── Strategy 2: Click checkbox (fast + free — Turnstile/hCaptcha) ─
    # For Turnstile/hCaptcha, checkbox click with stealth often works instantly.
    # For reCAPTCHA v2, SKIP — clicking opens image puzzle.
    if captcha_type in ("turnstile", "hcaptcha"):
        strategies_tried.append("click_checkbox")
        clicked = await _strategy_click_checkbox(page, captcha_type)
        if clicked:
            await asyncio.sleep(3)
            still_captcha = await detect(page)
            if not still_captcha or not still_captcha.get("type"):
                return f"CAPTCHA ({captcha_type}) solved by clicking checkbox. Strategy: click."

    # ── Strategy 3: 2Captcha API token injection (slow + paid) ────────
    # For reCAPTCHA v2: this MUST run without clicking checkbox first.
    # For others: fallback if checkbox didn't work.
    if api_key and sitekey and captcha_type in _TASK_TYPE_MAP:
        strategies_tried.append("2captcha_api")
        token = await _strategy_api_solve(api_key, captcha_type, sitekey, page.url)
        if token:
            await _inject_token(page, captcha_type, token)
            await _try_submit_form(page)
            await asyncio.sleep(3)
            still_captcha = await detect(page)
            if not still_captcha or not still_captcha.get("type"):
                return f"CAPTCHA ({captcha_type}) solved via 2Captcha API. Strategy: api."
            strategies_tried.append("reload_after_inject")
            await page.reload(wait_until="domcontentloaded", timeout=15_000)
            await asyncio.sleep(2)
            still_captcha = await detect(page)
            if not still_captcha or not still_captcha.get("type"):
                return f"CAPTCHA ({captcha_type}) solved via 2Captcha API + reload. Strategy: api+reload."

    # ── Strategy 4: For generic blocks — wait and reload ─────────────
    if captcha_type == "generic_block":
        strategies_tried.append("wait_and_reload")
        await asyncio.sleep(5)
        await page.reload(wait_until="domcontentloaded", timeout=15_000)
        await asyncio.sleep(3)
        still_captcha = await detect(page)
        if not still_captcha or not still_captcha.get("type"):
            return "Bot detection page resolved after wait + reload."

    # ── All strategies failed ────────────────────────────────────────
    return (
        f"[CAPTCHA_UNSOLVED] type={captcha_type}, "
        f"strategies_tried=[{', '.join(strategies_tried)}]. "
        f"All auto-solve strategies failed. Use request_human_assistance — "
        f"the operator needs to solve this manually in the browser."
    )


# ---------------------------------------------------------------------------
# Strategy implementations
# ---------------------------------------------------------------------------

async def _strategy_wait(page: Page, max_wait: int = 10) -> bool:
    """Wait for Cloudflare challenge to auto-resolve."""
    log.info("Strategy: waiting up to %ds for auto-resolve...", max_wait)
    for _ in range(max_wait):
        await asyncio.sleep(1)
        title = await page.title()
        # Cloudflare challenge page title changes when resolved
        if "just a moment" not in title.lower():
            log.info("Auto-resolve: page title changed to '%s'", title)
            return True
        # Check if challenge element disappeared
        still_challenge = await page.query_selector("#challenge-running, #challenge-stage")
        if not still_challenge:
            return True
    return False


async def _strategy_click_checkbox(page: Page, captcha_type: str) -> bool:
    """Try to click the CAPTCHA checkbox/widget."""
    log.info("Strategy: attempting checkbox click for %s", captcha_type)
    selectors = []
    if captcha_type == "recaptchav2":
        selectors = [
            "iframe[src*='recaptcha'] >> nth=0",  # recaptcha iframe
            ".recaptcha-checkbox-border",
            "#recaptcha-anchor",
        ]
    elif captcha_type == "turnstile":
        selectors = [
            "iframe[src*='challenges.cloudflare.com'] >> nth=0",
            ".cf-turnstile input[type='checkbox']",
        ]
    elif captcha_type == "hcaptcha":
        selectors = [
            "iframe[src*='hcaptcha'] >> nth=0",
            "#checkbox",
        ]

    for sel in selectors:
        try:
            # For iframes, we need to click inside the frame
            if "iframe" in sel and ">>" not in sel:
                frame_el = await page.query_selector(sel)
                if frame_el:
                    frame = await frame_el.content_frame()
                    if frame:
                        checkbox = await frame.query_selector(
                            ".recaptcha-checkbox-border, #checkbox, input[type='checkbox']"
                        )
                        if checkbox:
                            await checkbox.click(timeout=5_000)
                            log.info("Clicked checkbox inside iframe: %s", sel)
                            return True
            else:
                await page.click(sel, timeout=3_000)
                log.info("Clicked: %s", sel)
                return True
        except (PlaywrightTimeout, Exception) as exc:
            log.debug("Click failed for %s: %s", sel, exc)
            continue
    return False


async def _strategy_api_solve(
    api_key: str, captcha_type: str, sitekey: str, page_url: str
) -> Optional[str]:
    """Solve via 2Captcha API. Returns token or None."""
    task_type = _TASK_TYPE_MAP.get(captcha_type)
    if not task_type:
        return None

    task_payload: Dict[str, Any] = {
        "type": task_type,
        "websiteURL": page_url,
        "websiteKey": sitekey,
    }
    if captcha_type == "recaptchav3":
        task_payload["pageAction"] = "verify"
        task_payload["minScore"] = 0.7

    log.info("Strategy: calling 2Captcha API (task type: %s, sitekey: %s)...", task_type, sitekey[:16])
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=10)) as client:
            # Create task
            resp = await client.post(
                f"{_API_BASE}/createTask",
                json={"clientKey": api_key, "task": task_payload},
            )
            data = _safe_json(resp)
            if data is None:
                log.warning("2Captcha createTask: non-JSON response (HTTP %s): %s", resp.status_code, resp.text[:200])
                return None
            if data.get("errorId", 0) != 0:
                log.warning("2Captcha createTask error: %s", data.get("errorDescription"))
                return None

            task_id = data.get("taskId")
            if not task_id:
                solution = data.get("solution", {})
                return solution.get("gRecaptchaResponse") or solution.get("token")

            log.info("2Captcha task created: %s, polling...", task_id)

            # Poll for result (max ~180s, reCAPTCHA can be slow)
            for attempt in range(90):
                await asyncio.sleep(2)
                resp = await client.post(
                    f"{_API_BASE}/getTaskResult",
                    json={"clientKey": api_key, "taskId": task_id},
                )
                result = _safe_json(resp)
                if result is None:
                    log.debug("2Captcha poll: non-JSON response, retrying...")
                    continue
                if result.get("errorId", 0) != 0:
                    log.warning("2Captcha poll error: %s", result.get("errorDescription"))
                    return None
                if result.get("status") == "ready":
                    solution = result.get("solution", {})
                    token = (
                        solution.get("gRecaptchaResponse")
                        or solution.get("token")
                        or solution.get("text")
                    )
                    log.info("2Captcha solved in %ds, token length=%d", attempt * 2, len(token or ""))
                    return token

            log.warning("2Captcha timed out after 180s")
            return None
    except Exception as exc:
        log.warning("2Captcha API error: %s", exc)
        return None


def _safe_json(resp: httpx.Response) -> Optional[Dict[str, Any]]:
    """Parse JSON response safely, return None if not valid JSON."""
    try:
        return resp.json()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Token injection + form submission
# ---------------------------------------------------------------------------

async def _inject_token(page: Page, captcha_type: str, token: str) -> None:
    """Inject the solved token into the page and trigger callbacks."""
    safe_token = token.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")

    if captcha_type in ("recaptchav2", "recaptchav3"):
        await page.evaluate(f"""
        () => {{
            document.querySelectorAll('[name="g-recaptcha-response"], #g-recaptcha-response').forEach(el => {{
                el.value = '{safe_token}';
                el.style.display = 'block';
            }});
            // Try triggering callback
            try {{
                if (typeof ___grecaptcha_cfg !== 'undefined') {{
                    const clients = ___grecaptcha_cfg.clients || {{}};
                    for (const key in clients) {{
                        const c = clients[key];
                        for (const p in c) {{
                            const o = c[p];
                            if (o && typeof o === 'object') {{
                                for (const k in o) {{
                                    if (o[k]?.callback) {{ o[k].callback('{safe_token}'); return; }}
                                }}
                            }}
                        }}
                    }}
                }}
            }} catch(e) {{}}
            // Also try global grecaptcha
            try {{ grecaptcha?.getResponse && grecaptcha.execute(); }} catch(e) {{}}
        }}
        """)
    elif captcha_type == "hcaptcha":
        await page.evaluate(f"""
        () => {{
            document.querySelectorAll('[name="h-captcha-response"], [name="g-recaptcha-response"]').forEach(el => {{
                el.value = '{safe_token}';
            }});
            try {{
                const widget = document.querySelector('.h-captcha');
                if (widget) {{
                    const cb = widget.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') window[cb]('{safe_token}');
                }}
            }} catch(e) {{}}
        }}
        """)
    elif captcha_type == "turnstile":
        await page.evaluate(f"""
        () => {{
            document.querySelectorAll('[name="cf-turnstile-response"]').forEach(el => {{
                el.value = '{safe_token}';
            }});
            try {{
                const widget = document.querySelector('.cf-turnstile');
                if (widget) {{
                    const cb = widget.getAttribute('data-callback');
                    if (cb && typeof window[cb] === 'function') window[cb]('{safe_token}');
                }}
            }} catch(e) {{}}
        }}
        """)

    log.info("Token injected for %s", captcha_type)


async def _try_submit_form(page: Page) -> None:
    """After injection, try to find and click a submit button."""
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "form button:not([type='button'])",
        "#submit", ".submit",
    ]
    for sel in submit_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click(timeout=3_000)
                log.info("Clicked submit button: %s", sel)
                return
        except Exception:
            continue
