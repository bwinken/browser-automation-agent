"""
OpenAI tool schemas and the Playwright-backed executor.

Each schema entry maps 1-to-1 with a method on PlaywrightToolExecutor.
No LangChain / browser-use abstractions — pure openai + playwright.
"""
import json
from typing import Any

from playwright.async_api import Page

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
            "description": "Click an element on the page identified by a CSS selector.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector of the element to click.",
                    }
                },
                "required": ["selector"],
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
                "Execute a JavaScript expression in the browser context and return "
                "the result serialised as JSON. Use for reading DOM values or "
                "triggering JS-only actions."
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
            "name": "request_human_assistance",
            "description": (
                "Pause execution and ask the human operator for help. Use when "
                "encountering a CAPTCHA, a login challenge, or any ambiguity that "
                "cannot be resolved autonomously. A screenshot will be sent to the "
                "operator automatically."
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


class PlaywrightToolExecutor:
    """Wraps a Playwright Page and exposes each tool as an async method."""

    def __init__(self, page: Page) -> None:
        self._page = page

    async def navigate(self, url: str) -> str:
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return f"Navigated to {self._page.url}"

    async def click(self, selector: str) -> str:
        await self._page.click(selector, timeout=10_000)
        return f"Clicked '{selector}'"

    async def fill(self, selector: str, text: str) -> str:
        await self._page.fill(selector, text, timeout=10_000)
        return f"Filled '{selector}' with text"

    async def evaluate_javascript(self, script: str) -> str:
        result: Any = await self._page.evaluate(script)
        try:
            return json.dumps(result)
        except (TypeError, ValueError):
            return str(result)

    async def get_page_content(self) -> str:
        return await self._page.evaluate(_GET_PAGE_CONTENT_JS)
