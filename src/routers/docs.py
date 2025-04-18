from fastapi import APIRouter, FastAPI, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Documentation"], include_in_schema=False)


@router.get("/docs")
async def custom_swagger_ui_html(request: Request) -> HTMLResponse:
    app: FastAPI = request.app
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


SWAGGER_OAUTH2_REDIRECT_URL = "/docs/oauth2-redirect"


@router.get(SWAGGER_OAUTH2_REDIRECT_URL)
async def swagger_ui_redirect() -> HTMLResponse:
    return get_swagger_ui_oauth2_redirect_html()


@router.get("/redoc")
async def redoc_html(request: Request) -> HTMLResponse:
    app: FastAPI = request.app
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        redoc_js_url="/static/redoc.standalone.js",
    )
