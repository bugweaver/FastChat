from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from api import router as api_router
from core.auth.services.redis_service import setup_redis_client
from core.config import settings
from core.models import db_helper


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # startapp
    app.state.redis_client = await setup_redis_client()
    yield
    # shutdown
    await db_helper.dispose()
    await app.state.redis_client.close()


app = FastAPI(
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.run.host, port=settings.run.port, reload=True)
