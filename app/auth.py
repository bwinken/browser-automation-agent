from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),
) -> User:
    from app.config import settings

    # DEV_MODE: skip auth entirely, use first available user
    if settings.dev_mode:
        user = await User.find_one()
        if not user:
            raise HTTPException(status_code=401, detail="No users exist. POST /api/users/register first.")
        return user

    if not credentials:
        raise HTTPException(status_code=401, detail="API key required")

    user = await User.find_one(User.api_key == credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
