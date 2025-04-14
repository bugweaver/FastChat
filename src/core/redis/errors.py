import functools
import logging
from typing import Callable, Coroutine, TypeVar

from redis.exceptions import RedisError

log = logging.getLogger(__name__)

T = TypeVar("T")
AsyncFunc = Callable[..., Coroutine[None, None, T]]


def handle_redis_errors(
    default_return_value: T,
) -> Callable[[AsyncFunc[T]], AsyncFunc[T]]:
    """
    Decorator for handling standard Redis errors
    and other exceptions in asynchronous functions interacting with Redis.
    """

    def decorator(func: AsyncFunc[T]) -> AsyncFunc[T]:
        @functools.wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> T:
            try:
                return await func(*args, **kwargs)
            except RedisError as e:
                log.error("Redis error in '%s': %s", func.__name__, e)
                return default_return_value
            except Exception as e:
                log.error("Unexpected error in '%s': %s", func.__name__, e)
                return default_return_value

        return wrapper

    return decorator
