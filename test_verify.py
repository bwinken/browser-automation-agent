"""
Post-task verification: cross-check agent results against evidence screenshots.
Uses GPT vision to compare summary text with screenshot content.
Saves full API response + logs + verification to test_<task_id>.log
"""
import asyncio
import base64
import json
import os
import sys
from datetime import datetime

import httpx
from openai import AsyncOpenAI


async def verify_task(
    task_id: str, api_key: str, openai_key: str,
    base_url: str = "http://localhost:8000", log_dir: str = "test_logs",
):
    """Fetch task result, verify against screenshots, save full log."""

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"test_{task_id[:8]}.log")
    log_lines = []

    def log(msg: str):
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("ascii", errors="replace").decode())
        log_lines.append(msg)

    # 1. Fetch task data
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/task/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        task = resp.json()

    status = task["status"]
    logs = task.get("logs", [])
    result = task.get("result_data") or {}
    summary = result.get("summary", "")
    screenshots = result.get("screenshots", [])
    prompt = task.get("prompt", "")
    created = task.get("created_at", "")
    has_history = task.get("has_history", False)

    log(f"{'=' * 60}")
    log(f"TASK: {task_id}")
    log(f"Date: {created}")
    log(f"Status: {status}")
    log(f"Prompt: {prompt}")
    log(f"Has history: {has_history}")
    log(f"Summary length: {len(summary)} chars")
    log(f"Screenshots: {len(screenshots)}")
    log(f"Log entries: {len(logs)}")
    log(f"{'=' * 60}")

    # 2. Write full agent logs
    log("")
    log("--- AGENT LOGS ---")
    for entry in logs:
        log(entry)

    # 3. Write full summary
    log("")
    log("--- SUMMARY ---")
    log(summary if summary else "(empty)")

    # 4. Write result_data (without screenshots base64)
    log("")
    log("--- RESULT DATA ---")
    result_clean = {k: v for k, v in result.items() if k != "screenshots"}
    result_clean["screenshot_count"] = len(screenshots)
    log(json.dumps(result_clean, indent=2, ensure_ascii=False))

    # 5. Verification
    log("")
    log("--- VERIFICATION ---")

    if status != "completed":
        log("VERDICT: FAIL — Task did not complete")
        _write_log(log_path, log_lines)
        return False

    if not summary or len(summary) < 20:
        log("VERDICT: FAIL — Summary is empty or too short")
        _write_log(log_path, log_lines)
        return False

    checks = [
        "1. DATA ACCURACY: Do the numbers in the summary (prices, temperatures, percentages) match the screenshot? Small rounding differences are OK.",
        "2. COMPLETENESS: Did the task ask for N items? Does the summary contain that many? Count them.",
        "3. SCREENSHOT RELEVANCE: Does the screenshot show a data page? If the screenshot shows an error (e.g. 429) but the agent noted it used an API fallback, that is ACCEPTABLE — do not penalize.",
        "4. SOURCE CREDIBILITY: Is the data from a legitimate source?",
        "5. DATE RANGES: 'since 2024' means 2024 and later (2024, 2025, 2026 are all valid). Do not penalize papers from 2025 if the task says 'since 2024'.",
        "6. AGENT ADAPTATION: If the agent encountered an error (429, CAPTCHA, redirect) and adapted by using an API or alternative approach, this is GOOD behavior — do not penalize as long as the final data is reasonable.",
    ]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a QA reviewer for a browser automation agent. "
                "You will receive: (1) the user's original task, (2) the agent's summary, "
                "and (3) evidence screenshots. "
                "Verify the agent's output against the screenshots. "
                "Respond in JSON: {\"pass\": true/false, \"score\": 0-100, \"issues\": [\"...\"], \"details\": \"...\"}"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"TASK: {prompt}\n\n"
                        f"AGENT SUMMARY:\n{summary}\n\n"
                        f"VERIFICATION CHECKLIST:\n" + "\n".join(checks)
                    ),
                },
            ],
        },
    ]

    for i, b64 in enumerate(screenshots[:3]):
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"},
        })

    if not screenshots:
        messages[1]["content"].append({
            "type": "text",
            "text": "\n\nNOTE: No evidence screenshots provided. Mark screenshot relevance as FAIL.",
        })

    llm = AsyncOpenAI(api_key=openai_key)
    try:
        resp = await llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
        )
        review = json.loads(resp.choices[0].message.content)
    except Exception as exc:
        log(f"Verification LLM call failed: {exc}")
        log("VERDICT: FAIL — Verification error")
        _write_log(log_path, log_lines)
        return False

    passed = review.get("pass", False)
    score = review.get("score", 0)
    issues = review.get("issues", [])
    details = review.get("details", "")

    log(f"Score: {score}/100")
    log(f"VERDICT: {'PASS' if passed else 'FAIL'}")
    if issues:
        log("Issues:")
        for issue in issues:
            log(f"  - {issue}")
    if details:
        log(f"Details: {details}")

    # 6. Save screenshot files for review
    for i, b64 in enumerate(screenshots):
        img_path = os.path.join(log_dir, f"test_{task_id[:8]}_screenshot_{i+1}.png")
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(b64))
        log(f"Screenshot {i+1} saved: {img_path}")

    _write_log(log_path, log_lines)
    return passed


def _write_log(path: str, lines: list):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nLog saved: {path}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_verify.py <task_id> [task_id2 ...]")
        print("  Env vars: DEMO_API_KEY, OPENAI_API_KEY")
        print(f"  Logs saved to: test_logs/test_<task_id>.log")
        sys.exit(1)

    api_key = os.environ.get("DEMO_API_KEY", "a5a6541b-5ee9-426e-95f8-437aa5d77374")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if not openai_key:
        try:
            with open(".env") as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        openai_key = line.split("=", 1)[1].strip()
        except FileNotFoundError:
            pass

    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    task_ids = sys.argv[1:]
    results = []
    for tid in task_ids:
        passed = await verify_task(tid, api_key, openai_key)
        results.append((tid[:8], passed))

    print()
    print("=" * 50)
    print("VERIFICATION SUMMARY:")
    for tid, passed in results:
        print(f"  {tid}: {'PASS' if passed else 'FAIL'}")
    total_pass = sum(1 for _, p in results if p)
    print(f"\n  {total_pass}/{len(results)} passed")
    print(f"  Logs: test_logs/")


if __name__ == "__main__":
    asyncio.run(main())
