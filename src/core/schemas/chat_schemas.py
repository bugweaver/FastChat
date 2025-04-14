from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatCreateRequest(BaseModel):
    target_user_id: int


class MessageReplyRequest(BaseModel):
    content: str
    reply_to_id: int


class SenderInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar: str | None = None


class LastMessageInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str | None = None
    timestamp: datetime | None = None
    sender: SenderInfo | None = None


class ChatPartnerInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    avatar: str | None = None
    is_online: bool


class ChatCreatedResponse(BaseModel):
    chat_id: int


class ChatInfoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None = None
    is_group: bool
    created_at: datetime
    chat_partner: ChatPartnerInfo | None = None


class ChatSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_group: bool
    last_message: LastMessageInfo | None = None
    unread_count: int = 0
    avatar: str | None = None
    is_online: bool = False


class UserChatsResponse(BaseModel):
    chats: list[ChatSummarySchema]


class MessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    chat_id: int
    content: str
    created_at: datetime
    sender: SenderInfo | None = None
    reply_to_id: int | None = None


class MessagesListResponse(BaseModel):
    messages: list[MessageSchema]
