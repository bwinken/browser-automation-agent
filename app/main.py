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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient

from app.logging_config import setup_logging
from app.api import tasks as tasks_api
from app.api import users as users_api
from app.auth import hash_password
from app.config import settings

setup_logging(settings.log_level)
import secrets as _secrets
from app.models import InviteCode, Task, User
from app.ws.hitl import hitl_websocket

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Safety check: warn if DEV_MODE is on with a remote database
    if settings.dev_mode and "mongodb+srv" in settings.mongodb_url:
        log.warning("DEV_MODE=true with a remote MongoDB — authentication is BYPASSED! Set DEV_MODE=false for production.")

    client = AsyncIOMotorClient(settings.mongodb_url)
    await init_beanie(
        database=client[settings.db_name],
        document_models=[User, Task, InviteCode],
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

    # Auto-create admin user
    if settings.admin_username:
        admin_pw = settings.admin_password or ""
        if admin_pw in ("", "admin", "change-me", "password", "123456"):
            log.warning("ADMIN_PASSWORD is weak or default — set a strong password in production!")
        admin = await User.find_one(User.username == settings.admin_username)
        if not admin:
            admin = User(
                username=settings.admin_username,
                hashed_password=hash_password(admin_pw or _secrets.token_hex(16)),
                is_admin=True,
            )
            await admin.insert()
            log.info("Admin user created: %s (key: %s...)", admin.username, admin.api_key[:8])

    # Auto-generate initial invite codes
    code_count = await InviteCode.find(InviteCode.used == False).count()
    if code_count == 0 and settings.initial_invite_codes > 0:
        codes = []
        for _ in range(settings.initial_invite_codes):
            code = f"BAAS-{_secrets.token_hex(4).upper()}-{_secrets.token_hex(4).upper()}"
            await InviteCode(code=code).insert()
            codes.append(code)
        log.info("Generated %d invite codes (view via admin dashboard)", len(codes))

    yield
    client.close()


app = FastAPI(
    title="Browser Automation as a Service",
    description="Submit natural language tasks; an AI agent executes them in a headless browser.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# CORS — restrict in production, allow all in dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.dev_mode else [os.environ.get("ALLOWED_ORIGIN", "")],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


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
async def get_download(filename: str, authorization: str = Header(None), token: str = None):
    if not settings.dev_mode:
        # Support both Authorization header and ?token= query param
        api_key = None
        if authorization and authorization.startswith("Bearer "):
            api_key = authorization.split(" ", 1)[1]
        elif token:
            api_key = token
        if not api_key:
            raise HTTPException(status_code=401, detail="API key required")
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
