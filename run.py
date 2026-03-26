import asyncio
import sys

# Must be set BEFORE uvicorn creates the event loop.
# --reload spawns a subprocess that resets the policy, so we don't use reload here.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080)
