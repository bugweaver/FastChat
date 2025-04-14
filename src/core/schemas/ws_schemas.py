import logging
from typing import Any, Literal

import orjson as json
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)
from pydantic_core import PydanticCustomError

log = logging.getLogger(__name__)


class BaseWsMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")


class PingMessage(BaseWsMessage):
    type: Literal["ping"] = "ping"


class SearchQueryMessage(BaseWsMessage):
    type: Literal["search_query"] = "search_query"
    query: str


class IncomingChatPayload(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)
    reply_to_id: int | None = None

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError(
                "value_error", "Content cannot be empty or whitespace."
            )
        return v


class IncomingChatMessage(BaseWsMessage):
    type: Literal["message"] = "message"
    data: IncomingChatPayload


class PongMessageResp(BaseWsMessage):
    type: Literal["pong"] = "pong"


HeartbeatMessageResp = PongMessageResp


class UserSearchResultData(BaseModel):
    id: int
    username: str
    avatar: str | None = None
    is_online: bool = False


class SearchResultsResp(BaseWsMessage):
    type: Literal["search_results"] = "search_results"
    results: list[UserSearchResultData]


class MessageDeletedData(BaseModel):
    message_id: int
    chat_id: int
    deleted_at: AwareDatetime


class MessageDeletedResp(BaseWsMessage):
    type: Literal["message_deleted"] = "message_deleted"
    data: MessageDeletedData


class InitialStatusData(BaseModel):
    online_users: list[int]


class InitialStatusResp(BaseWsMessage):
    type: Literal["initial_status"] = "initial_status"
    data: InitialStatusData


class StatusUpdateData(BaseModel):
    user_id: int
    is_online: bool


class StatusUpdateResp(BaseWsMessage):
    type: Literal["status_update"] = "status_update"
    data: StatusUpdateData


class WsErrorData(BaseModel):
    message: str
    code: int = 1011


class WsErrorResp(BaseWsMessage):
    type: Literal["error"] = "error"
    error: WsErrorData


WS_MESSAGE_SCHEMAS: dict[str, type[BaseWsMessage]] = {
    "ping": PingMessage,
    "search_query": SearchQueryMessage,
    "message": IncomingChatMessage,
}


def parse_ws_message(data_text: str) -> BaseWsMessage | str:
    """
    Parses incoming WebSocket text.

    Returns a Pydantic model if the text is valid JSON with a known type and valid data.
    Returns the original text if:
    - the text is not valid JSON.
    - the JSON does not contain a 'type' field or 'type' is not a string.
    - the message type is unknown (not in WS_MESSAGE_SCHEMAS).
    - an unexpected error occurred while parsing the JSON or looking up the type.

    Throws a ValidationError ONLY if:
    - the JSON is valid.
    - the message type is known (is in WS_MESSAGE_SCHEMAS).
    - the data does NOT pass validation for this model.
    """
    try:
        data: dict[str, Any] = json.loads(data_text)

        message_type = data.get("type")
        if not isinstance(message_type, str):
            log.debug(
                "Received message without valid string 'type' field: %s...",
                data_text[:100],
            )
            return data_text

        model_cls = WS_MESSAGE_SCHEMAS.get(message_type)

        if model_cls:
            try:
                validated_model = model_cls.model_validate(data)
                log.debug("Successfully parsed message type '%s'", message_type)
                return validated_model
            except ValidationError as e:
                log.warning(
                    "WebSocket message validation failed for known type '%s'",
                    message_type,
                    exc_info=False,
                )
                raise e
        else:
            log.debug(
                "Received message with unknown type '%s': %s...",
                message_type,
                data_text[:100],
            )
            return data_text

    except json.JSONDecodeError:
        log.debug("Received non-JSON message: %s...", data_text[:100])
        return data_text
    except Exception:
        log.exception(
            "Unexpected error parsing WebSocket message: %s...", data_text[:100]
        )
        return data_text
