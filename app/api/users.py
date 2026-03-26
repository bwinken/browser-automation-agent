from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import hash_password, verify_password
from app.models import User

router = APIRouter(prefix="/users", tags=["users"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    existing = await User.find_one(User.username == body.username)
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
    )
    await user.insert()
    return {"username": user.username, "api_key": user.api_key}


@router.post("/login")
async def login(body: LoginRequest):
    user = await User.find_one(User.username == body.username)
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"username": user.username, "api_key": user.api_key}
