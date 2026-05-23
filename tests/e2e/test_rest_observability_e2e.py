from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memoryx.api.errors import http_exception_handler, validation_exception_handler
from memoryx.observability.middleware import observability_middleware

try:
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException
except Exception:  # pragma: no cover
    RequestValidationError = None
    StarletteHTTPException = None


def make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(observability_middleware)
    if StarletteHTTPException:
        app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    if RequestValidationError:
        app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.get("/live")
    async def live():
        return {"live": True}

    @app.get("/boom")
    async def boom():
        from fastapi import HTTPException
        raise HTTPException(404, "not found")

    return app


def test_rest_trace_header_and_metrics_endpoint_like_behavior():
    client = TestClient(make_app())

    resp = client.get("/live", headers={"X-Trace-Id": "trace-e2e-1"})

    assert resp.status_code == 200
    assert resp.headers["X-Trace-Id"] == "trace-e2e-1"
    assert resp.json()["live"] is True


def test_rest_uniform_error_shape():
    client = TestClient(make_app())

    resp = client.get("/boom", headers={"X-Trace-Id": "trace-e2e-2"})

    assert resp.status_code == 404
    payload = resp.json()
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "not found"
    assert payload["trace_id"] == "trace-e2e-2"
