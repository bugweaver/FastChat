import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from api import router as api_router
from core.config import settings
from core.lifecycle import lifespan
from core.middleware import setup_cors_middleware

logging.basicConfig(
    level=settings.logging.log_level_value,
    format=settings.logging.log_format,
)
app = FastAPI(
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
setup_cors_middleware(app)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.run.host, port=settings.run.port, reload=True)
