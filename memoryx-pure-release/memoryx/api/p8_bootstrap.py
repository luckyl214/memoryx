"""P8 bootstrap helpers for REST apps.

Call install_p8_observability(app) from memoryx.api.rest_app after app is
created. Kept separate to minimize merge conflicts with the existing REST file.
"""

from __future__ import annotations

from fastapi import FastAPI

from memoryx.observability.middleware import observability_middleware

from .errors import http_exception_handler, unhandled_exception_handler, validation_exception_handler

try:
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
except Exception:  # pragma: no cover
    RequestValidationError = None  # type: ignore[assignment]
    StarletteHTTPException = None  # type: ignore[assignment]


def install_p8_observability(app: FastAPI) -> None:
    # Avoid duplicate middleware when tests repeatedly configure the app.
    if not getattr(app.state, "memoryx_p8_observability_installed", False):
        app.middleware("http")(observability_middleware)
        app.state.memoryx_p8_observability_installed = True

    if StarletteHTTPException is not None:
        app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    if RequestValidationError is not None:
        app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
