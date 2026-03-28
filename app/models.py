import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class User(Document):
    username: str
    hashed_password: str
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    is_admin: bool = False
    token_usage: int = 0
    quota_usd: float = 10.0       # free credit in USD
    spent_usd: float = 0.0        # total spent so far
    encrypted_openai_key: str = "" # encrypted with Fernet (SECRET_KEY)

    @property
    def custom_openai_key(self) -> str:
        if not self.encrypted_openai_key:
            return ""
        from app.crypto import decrypt
        return decrypt(self.encrypted_openai_key)

    def set_openai_key(self, plaintext_key: str) -> None:
        if not plaintext_key:
            self.encrypted_openai_key = ""
            return
        from app.crypto import encrypt
        self.encrypted_openai_key = encrypt(plaintext_key)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.quota_usd - self.spent_usd)

    @property
    def has_budget(self) -> bool:
        return self.remaining_usd > 0 or bool(self.encrypted_openai_key)

    class Settings:
        name = "users"


class InviteCode(Document):
    code: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    used: bool = False
    used_by: Optional[str] = None
    used_at: Optional[datetime] = None

    class Settings:
        name = "invite_codes"


class Task(Document):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: PydanticObjectId
    prompt: str
    # pending | running | paused | completed | failed
    status: str = "pending"
    logs: List[str] = Field(default_factory=list)
    result_data: Optional[Dict[str, Any]] = None
    # Full LLM conversation history — enables task continuation
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "tasks"
