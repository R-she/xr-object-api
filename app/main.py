"""Application factory, router registration and error handlers."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .errors import AppError, error_payload, validation_detail
from .routers.objects import router as objects_router
from .service import ObjectService
from .storage import InMemoryObjectRepository, ObjectRepository, SqliteObjectRepository


def _lifespan(repository: ObjectRepository):
    """Close repository resources (SQLite) when the ASGI app shuts down."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(repository, "close", None)
        if callable(close):
            close()

    return lifespan


def create_app(repository: ObjectRepository | None = None) -> FastAPI:
    """Build a fresh application with its own repository unless one is injected."""
    if repository is None:
        db_path = os.environ.get("XR_DB_PATH")
        if db_path:
            repository = SqliteObjectRepository(db_path)
        else:
            repository = InMemoryObjectRepository()

    app = FastAPI(
        title="XR Scene Object API",
        version="1.0.0",
        lifespan=_lifespan(repository),
    )
    app.state.repository = repository
    app.state.service = ObjectService(repository)

    @app.get("/healthz", tags=["system"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(objects_router)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=error_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [validation_detail(err) for err in exc.errors()]
        return JSONResponse(
            status_code=422,
            content=error_payload("validation_error", "請求資料驗證失敗", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            code, message = "not_found", "找不到資源"
        elif exc.status_code == 405:
            code, message = "method_not_allowed", "不支援的 HTTP 方法"
        elif exc.status_code >= 500:
            code, message = "internal_error", "伺服器發生未預期錯誤"
        else:
            code, message = "client_error", "請求無法處理"
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, message),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_payload("internal_error", "伺服器發生未預期錯誤"),
        )

    return app
