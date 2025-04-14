from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.validation.auth_validation import get_current_active_auth_user
from core.chat.services.chat_service import ChatService
from core.chat.services.message_service import MessageService
from core.dependencies import get_redis_client
from core.models import db_helper
from core.schemas.chat_schemas import (
    ChatCreatedResponse,
    ChatCreateRequest,
    ChatInfoResponse,
    MessagesListResponse,
    UserChatsResponse,
)
from core.schemas.user_schemas import UserSchema

router = APIRouter(tags=["Chats"])


@router.get("/my-chats", response_model=UserChatsResponse)
async def get_my_chats(
    current_user: UserSchema = Depends(get_current_active_auth_user),
    db: AsyncSession = Depends(db_helper.session_getter),
    redis: Redis = Depends(get_redis_client),
) -> UserChatsResponse:
    """
    Retrieves a list of chats the current user participates in,
    including summaries like the last message and partner info (for private chats).
    """
    return await ChatService.get_user_chats(db=db, user_id=current_user.id, redis=redis)


@router.post(
    "/create", response_model=ChatCreatedResponse, status_code=status.HTTP_201_CREATED
)
async def create_private_chat(
    request: ChatCreateRequest,
    current_user: UserSchema = Depends(get_current_active_auth_user),
    db: AsyncSession = Depends(db_helper.session_getter),
) -> ChatCreatedResponse:
    """
    Creates a new private chat between the current user and the target user.
    Returns 201 Created on success.
    """
    return await ChatService.create_private_chat(
        db, current_user.id, request.target_user_id
    )


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: int,
    current_user: UserSchema = Depends(get_current_active_auth_user),
    db: AsyncSession = Depends(db_helper.session_getter),
    redis: Redis = Depends(get_redis_client),
) -> Response:
    """
    Deletes a message if the current user is the sender.
    Returns 204 No Content on success.
    """
    await MessageService.delete_message(
        db=db,
        message_id=message_id,
        current_user_id=current_user.id,
        redis=redis,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{chat_id}", response_model=ChatInfoResponse)
async def get_chat_info(
    chat_id: int,
    current_user: UserSchema = Depends(get_current_active_auth_user),
    db: AsyncSession = Depends(db_helper.session_getter),
    redis: Redis = Depends(get_redis_client),
) -> ChatInfoResponse:
    """
    Retrieves information about a specific chat if the current user is a participant.
    """
    return await ChatService.get_chat_info(
        db=db, chat_id=chat_id, current_user_id=current_user.id, redis=redis
    )


@router.get("/{chat_id}/messages", response_model=MessagesListResponse)
async def get_chat_messages(
    chat_id: int,
    current_user: UserSchema = Depends(get_current_active_auth_user),
    db: AsyncSession = Depends(db_helper.session_getter),
    redis: Redis = Depends(get_redis_client),
) -> MessagesListResponse:
    """
    Retrieves recent messages for a specific chat if the current user is a participant.
    Attempts to fetch from Redis cache first, then falls back to the database.
    """
    return await MessageService.get_chat_messages(
        db=db, chat_id=chat_id, user_id=current_user.id, redis=redis
    )
