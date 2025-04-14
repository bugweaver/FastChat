import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from core.auth.services.redis_service import setup_redis_client
from core.chat.services.redis_service import check_redis_health
from core.config import settings
from core.models import db_helper
from core.websockets.connection_manager import ConnectionManager

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Manages the application lifecycle: initialization and closing of resources.
    """
    log.info("Application lifespan startup...")
    redis_client = None
    connection_manager = None

    try:
        log.info("Initializing Redis client...")
        redis_client = await setup_redis_client()
        if await check_redis_health(redis_client):
            log.info("Redis client connected successfully.")
            app.state.redis_client = redis_client
        else:
            log.error("Redis health check failed!")
            app.state.redis_client = None

        if app.state.redis_client:
            log.info("Initializing WebSocket Connection Manager...")

            connection_manager = ConnectionManager(
                redis_url=str(settings.redis.url), redis_client=app.state.redis_client
            )
            await connection_manager.initialize()
            app.state.connection_manager = connection_manager
            log.info("WebSocket Connection Manager initialized.")
        else:
            log.warning(
                "Skipping WebSocket Connection Manager initialization "
                "due to Redis connection failure."
            )
            app.state.connection_manager = None

        log.info("Application startup complete.")
        yield

    finally:
        log.info("Application lifespan shutdown...")

        if connection_manager:
            try:
                log.info("Closing WebSocket Connection Manager...")
                await connection_manager.close()
                log.info("WebSocket Connection Manager closed successfully.")
            except Exception as e:
                log.error(
                    "Error closing WebSocket Connection Manager: %s", e, exc_info=True
                )

        try:
            log.info("Closing database connections...")
            await db_helper.dispose()
            log.info("Database connections closed successfully.")
        except Exception as e:
            log.error("Error closing database connections: %s", e, exc_info=True)

        if redis_client:
            try:
                log.info("Closing Redis client connection...")
                await redis_client.close()
                log.info("Redis client closed successfully.")
            except Exception as e:
                log.error("Error closing Redis client: %s", e, exc_info=True)

        log.info("Application shutdown complete.")
