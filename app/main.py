import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

# Playwright spawns subprocesses — Windows needs ProactorEventLoop for that.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from beanie import init_beanie
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient

from app.logging_config import setup_logging
from app.api import tasks as tasks_api
from app.api import users as users_api
from app.auth import hash_password
from app.config import settings

setup_logging(settings.log_level)
from app.models import Task, User
from app.ws.hitl import hitl_websocket


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = AsyncIOMotorClient(settings.mongodb_url)
    await init_beanie(
        database=client[settings.db_name],
        document_models=[User, Task],
    )
    # Auto-create demo user if DEMO_API_KEY is set in .env
    if settings.demo_api_key:
        existing = await User.find_one(User.api_key == settings.demo_api_key)
        if not existing:
            await User(
                username="demo",
                hashed_password=hash_password(uuid.uuid4().hex),
                api_key=settings.demo_api_key,
            ).insert()
    yield
    client.close()


app = FastAPI(
    title="Browser Automation as a Service",
    description="Submit natural language tasks; an AI agent executes them in a headless browser.",
    version="1.0.0",
    lifespan=lifespan,
)

log = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# REST routes
app.include_router(users_api.router, prefix="/api")
app.include_router(tasks_api.router, prefix="/api")


# WebSocket HITL endpoint
app.add_api_websocket_route("/ws/task/{task_id}", hitl_websocket)

# Serve downloaded files (auth-protected)
download_dir = os.path.abspath(settings.download_dir)
os.makedirs(download_dir, exist_ok=True)

from fastapi import Header, HTTPException
from fastapi.responses import FileResponse

@app.get("/downloads/{filename}")
async def get_download(filename: str, authorization: str = Header(None)):
    if not settings.dev_mode:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="API key required")
        api_key = authorization.split(" ", 1)[1]
        user = await User.find_one(User.api_key == api_key)
        if not user:
            raise HTTPException(status_code=403, detail="Invalid API key")
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    file_path = os.path.join(download_dir, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=safe_name)

# Serve the SPA last so it doesn't shadow API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")
