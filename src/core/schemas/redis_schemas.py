from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class RedisMessage(BaseModel):
    """Message Model in Redis"""

    id: int | str
    content: str
    chat_id: int | str
    user_id: int | str | None = None
    timestamp: str | None = None
    reply_to_id: int | str | None = None
    meta: dict[str, Any] | None = None

    @field_validator("id", "chat_id", "user_id", "reply_to_id")
    @classmethod
    def convert_ids_to_str(cls, v: str) -> str | None:
        """Преобразует ID в строки для хранения в Redis"""
        if v is None:
            return None
        return v

    @model_validator(mode="before")
    @classmethod
    def set_timestamp(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Устанавливает timestamp, если его нет"""
        if isinstance(data, dict) and not data.get("timestamp"):
            data["timestamp"] = datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            )
        return data

    class ConfigDict:
        populate_by_name = True


class RedisMessageFilter(BaseModel):
    """Model for filtering messages in Redis"""

    chat_id: int
    offset: int = Field(ge=0, default=0)
    limit: int = Field(gt=0, default=100)

    # start_time: Optional[datetime] = None
    # end_time: Optional[datetime] = None

    @field_validator("chat_id")
    @classmethod
    def convert_chat_id_to_str(cls, v: str) -> str:
        return v


class RedisChatSettings(BaseModel):
    """Chat settings in Redis"""

    max_history: int = 1000
    ttl: int = 86400 * 7
    deleted_ttl: int = 86400 * 30


class RedisConnectionSettings(BaseModel):
    """Settings for user connections"""

    connection_ttl: int = Field(300, ge=30)
