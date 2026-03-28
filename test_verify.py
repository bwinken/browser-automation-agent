"""
Post-task verification: cross-check agent results against evidence screenshots.
Uses GPT vision to compare summary text with screenshot content.
"""
import asyncio
import base64
import json
import sys
import httpx
from openai import AsyncOpenAI


async def verify_task(task_id: str, api_key: str, openai_key: str, base_url: str = "http://localhost:8080"):
    """Fetch task result and verify against evidence screenshots."""

    # 1. Fetch task data
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api/task/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        task = resp.json()

    status = task["status"]
    result = task.get("result_data", {})
    summary = result.get("summary", "")
    screenshots = result.get("screenshots", [])
    prompt = task.get("prompt", "")

    print(f"=== Task: {task_id[:8]} ===")
    print(f"Status: {status}")
    print(f"Prompt: {prompt}")
    print(f"Summary length: {len(summary)} chars")
    print(f"Screenshots: {len(screenshots)}")
    print()

    if status != "completed":
        print("FAIL: Task did not complete")
        return False

    if not summary or len(summary) < 20:
        print("FAIL: Summary is empty or too short")
        return False

    # 2. Build verification prompt
    checks = [
        "1. DATA ACCURACY: Does the summary text match what is shown in the screenshot(s)? Are numbers, names, prices correct?",
        "2. COMPLETENESS: Did the task ask for N items (e.g. 'top 3', '5 jobs')? Does the summary contain that many items?",
        "3. SCREENSHOT RELEVANCE: Do the screenshots show the actual results page (not a login page, error page, or popup)?",
        "4. SOURCE CREDIBILITY: Is the data from a legitimate source (official website, not fabricated)?",
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

    # Add screenshots as vision images
    for i, b64 in enumerate(screenshots[:3]):  # max 3 screenshots
        messages[1]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"},
        })

    if not screenshots:
        messages[1]["content"].append({
            "type": "text",
            "text": "\n\nNOTE: No evidence screenshots provided. Mark screenshot relevance as FAIL.",
        })

    # 3. Call GPT vision for verification
    llm = AsyncOpenAI(api_key=openai_key)
    try:
        resp = await llm.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
        )
        review = json.loads(resp.choices[0].message.content)
    except Exception as exc:
        print(f"Verification LLM call failed: {exc}")
        return False

    # 4. Print results
    passed = review.get("pass", False)
    score = review.get("score", 0)
    issues = review.get("issues", [])
    details = review.get("details", "")

    print(f"{'PASS' if passed else 'FAIL'} (score: {score}/100)")
    if issues:
        print(f"Issues:")
        for issue in issues:
            print(f"  - {issue}")
    if details:
        print(f"Details: {details}")
    print()
    return passed


async def main():
    if len(sys.argv) < 2:
        print("Usage: python test_verify.py <task_id> [task_id2 ...]")
        print("  Env vars: DEMO_API_KEY, OPENAI_API_KEY")
        sys.exit(1)

    import os
    api_key = os.environ.get("DEMO_API_KEY", "a5a6541b-5ee9-426e-95f8-437aa5d77374")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if not openai_key:
        # Try reading from .env
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

    print("=" * 50)
    print("VERIFICATION SUMMARY:")
    for tid, passed in results:
        print(f"  {tid}: {'PASS' if passed else 'FAIL'}")
    total_pass = sum(1 for _, p in results if p)
    print(f"\n  {total_pass}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
