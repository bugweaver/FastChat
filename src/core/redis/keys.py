def get_chat_messages_key(chat_id: int | str) -> str:
    """Redis key (List) for storing serialized chat messages."""
    return f"chat:{chat_id}:messages"


def get_chat_unique_messages_key(chat_id: int | str) -> str:
    """Redis key (Hash) to track unique message IDs in history."""
    return f"chat:{chat_id}:messages:unique"


def get_chat_deleted_messages_key(chat_id: int | str) -> str:
    """Redis key (Set) for storing IDs of deleted chat messages."""
    return f"chat:{chat_id}:messages:deleted"


def get_user_connections_key(user_id: int | str) -> str:
    """
    Redis key (String/Counter) for the counter
    of active WebSocket connections of the user.
    """
    return f"user:{user_id}:connections"


ONLINE_USERS_KEY = "online_users"


def get_chat_connections_key(chat_id: int | str) -> str:
    """Redis key (Set) to store IDs of users connected to this chat."""
    return f"chat:{chat_id}:connections"


def get_user_chats_key(user_id: int | str) -> str:
    """Redis key (Set) for storing IDs of chats the user is connected to."""
    return f"user:{user_id}:active_chats"


USER_STATUS_CHANNEL = "user_status_changes"
CHAT_MESSAGE_CHANNEL_PREFIX = "chat_message:"
MESSAGE_DELETED_CHANNEL_PREFIX = "message_deleted:"
SYSTEM_NOTIFICATION_CHANNEL = "system_notifications"


def get_chat_message_channel(chat_id: int | str) -> str:
    """Returns the Pub/Sub channel name for new messages in a specific chat."""
    return f"{CHAT_MESSAGE_CHANNEL_PREFIX}{chat_id}"


def get_message_deleted_channel(chat_id: int | str) -> str:
    """Returns the Pub/Sub channel name for chat message deletion notifications."""
    return f"{MESSAGE_DELETED_CHANNEL_PREFIX}{chat_id}"


CHAT_MESSAGES_PATTERN = f"{CHAT_MESSAGE_CHANNEL_PREFIX}*"
DELETED_MESSAGES_PATTERN = f"{MESSAGE_DELETED_CHANNEL_PREFIX}*"
