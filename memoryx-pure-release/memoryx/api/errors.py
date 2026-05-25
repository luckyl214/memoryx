"""Uniform REST error responses for MemoryX."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _trace_id(request: Request) -> str | None:
    return request.headers.get("X-Trace-Id") or request.headers.get("X-Request-Id")


def error_payload(*, code: str, message: str, details=None, trace_id: str | None = None) -> dict:
    payload = {"error": {"code": code, "message": message, "details": details or {}}}
    if trace_id:
        payload["trace_id"] = trace_id
    return payload


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    status = int(exc.status_code)
    code = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status, "HTTP_ERROR")
    return JSONResponse(
        status_code=status,
        content=error_payload(code=code, message=str(exc.detail), trace_id=_trace_id(request)),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            details={"errors": exc.errors()},
            trace_id=_trace_id(request),
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(
            code="INTERNAL_ERROR",
            message="Internal server error",
            details={"exception_type": type(exc).__name__},
            trace_id=_trace_id(request),
        ),
    )
