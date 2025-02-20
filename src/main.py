from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from core.config import settings

from api import router as api_router
from core.models import db_helper

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startapp
    yield
    # shutdown
    await db_helper.dispose()
app = FastAPI(lifespan=lifespan)
app.include_router(api_router, prefix=settings.api.prefix)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.run.host, port=settings.run.port, reload=True)
