import logging

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from api import router as api_router
from core.config import settings
from core.lifecycle import lifespan
from core.middleware import setup_cors_middleware
from routers.docs import SWAGGER_OAUTH2_REDIRECT_URL
from routers.docs import router as docs_router

logging.basicConfig(
    level=settings.logging.log_level_value,
    format=settings.logging.log_format,
)
app = FastAPI(
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=SWAGGER_OAUTH2_REDIRECT_URL,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
setup_cors_middleware(app)

app.include_router(docs_router)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.run.host, port=settings.run.port, reload=True)
