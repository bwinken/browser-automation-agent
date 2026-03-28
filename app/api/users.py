import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_admin_user, get_current_user, hash_password, verify_password
from app.models import InviteCode, User

router = APIRouter(prefix="/users", tags=["users"])


class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    # Validate invite code
    invite = await InviteCode.find_one(
        InviteCode.code == body.invite_code,
        InviteCode.used == False,
    )
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or already used invite code")

    # Check username
    existing = await User.find_one(User.username == body.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Create user
    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    await user.insert()

    # Mark invite code as used
    invite.used = True
    invite.used_by = body.username
    invite.used_at = datetime.utcnow()
    await invite.save()

    return {"username": user.username, "api_key": user.api_key}


@router.post("/login")
async def login(body: LoginRequest):
    user = await User.find_one(User.username == body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": user.username, "api_key": user.api_key}


# ── Account / Quota ─────────────────────────────────────────────

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "username": user.username,
        "is_admin": user.is_admin,
        "token_usage": user.token_usage,
        "quota_usd": user.quota_usd,
        "spent_usd": round(user.spent_usd, 4),
        "remaining_usd": round(user.remaining_usd, 4),
        "has_custom_key": bool(user.encrypted_openai_key),
    }


class SetKeyRequest(BaseModel):
    openai_key: str


@router.post("/me/openai-key")
async def set_openai_key(body: SetKeyRequest, user: User = Depends(get_current_user)):
    key = body.openai_key.strip()
    if key and not key.startswith("sk-"):
        raise HTTPException(status_code=400, detail="Invalid OpenAI API key format (must start with sk-)")
    user.set_openai_key(key)
    await user.save()
    return {
        "has_custom_key": bool(key),
        "message": "Custom OpenAI key saved." if key else "Custom key removed. Using system quota.",
    }


# ── Admin endpoints ─────────────────────────────────────────────

@router.get("/admin/users")
async def list_users(admin: User = Depends(get_admin_user)):
    users = await User.find_all().sort(-User.token_usage).to_list()
    return [
        {
            "username": u.username,
            "is_admin": u.is_admin,
            "token_usage": u.token_usage,
            "quota_usd": u.quota_usd,
            "spent_usd": round(u.spent_usd, 4),
            "remaining_usd": round(u.remaining_usd, 4),
            "has_custom_key": bool(u.encrypted_openai_key),
            "api_key_prefix": u.api_key[:8] + "...",
        }
        for u in users
    ]


class SetQuotaRequest(BaseModel):
    username: str
    quota_usd: float


@router.post("/admin/quota")
async def set_user_quota(body: SetQuotaRequest, admin: User = Depends(get_admin_user)):
    user = await User.find_one(User.username == body.username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.quota_usd = body.quota_usd
    await user.save()
    return {"username": user.username, "quota_usd": user.quota_usd}


@router.get("/admin/stats")
async def admin_stats(admin: User = Depends(get_admin_user)):
    from app.models import Task
    total_users = await User.find_all().count()
    total_tasks = await Task.find_all().count()
    all_users = await User.find_all().to_list()
    total_spent = sum(u.spent_usd for u in all_users)
    total_tokens = sum(u.token_usage for u in all_users)
    return {
        "total_users": total_users,
        "total_tasks": total_tasks,
        "total_spent_usd": round(total_spent, 4),
        "total_tokens": total_tokens,
    }


@router.post("/admin/invite", status_code=201)
async def create_invite(admin: User = Depends(get_admin_user)):
    code = f"BAAS-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
    invite = InviteCode(code=code)
    await invite.insert()
    return {"code": code}


@router.get("/admin/invites")
async def list_invites(admin: User = Depends(get_admin_user)):
    invites = await InviteCode.find_all().sort(-InviteCode.created_at).to_list()
    return [
        {
            "code": inv.code,
            "used": inv.used,
            "used_by": inv.used_by,
            "created_at": inv.created_at.isoformat(),
            "used_at": inv.used_at.isoformat() if inv.used_at else None,
        }
        for inv in invites
    ]
