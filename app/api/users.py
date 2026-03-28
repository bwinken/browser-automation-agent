import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_admin_user, hash_password, verify_password
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


# ── Admin endpoints ─────────────────────────────────────────────

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
