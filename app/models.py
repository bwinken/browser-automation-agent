import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from beanie import Document, PydanticObjectId
from pydantic import Field


class User(Document):
    username: str
    hashed_password: str
    api_key: str = Field(default_factory=lambda: str(uuid.uuid4()))
    token_usage: int = 0

    class Settings:
        name = "users"


class BrowserState(Document):
    user_id: PydanticObjectId
    state_json: Dict[str, Any]
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "browser_states"


class Task(Document):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: PydanticObjectId
    prompt: str
    # pending | running | paused | completed | failed
    status: str = "pending"
    logs: List[str] = Field(default_factory=list)
    result_data: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "tasks"
