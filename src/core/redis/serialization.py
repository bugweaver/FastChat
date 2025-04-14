import logging
from typing import Any

import orjson
from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)


def serialize_data(data: dict[str, Any] | BaseModel) -> bytes:
    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return orjson.dumps(payload)


def deserialize_data(
    raw_data: bytes | str, model: type[BaseModel] | None = None
) -> dict[str, Any] | BaseModel | None:
    if not raw_data:
        return None
    if isinstance(raw_data, str):
        raw_data = raw_data.encode("utf-8")
    try:
        data = orjson.loads(raw_data)
        return model.model_validate(data) if model else data
    except ValidationError as ve:
        log.error("Validation error for %s: %s\nRaw data: %s", model, ve, raw_data)
        raise
    except Exception as e:
        log.error("Deserialization error: %s\nData type: %s", e, type(raw_data))
