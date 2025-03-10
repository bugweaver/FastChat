from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings


def setup_cors_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,  # type: ignore
        allow_origins=settings.cors.allow_origins,
        allow_credentials=settings.cors.allow_credentials,
        allow_methods=settings.cors.allow_methods,
        allow_headers=settings.cors.allow_headers,
        expose_headers=settings.cors.expose_headers,
    )
