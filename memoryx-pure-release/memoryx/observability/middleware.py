"""FastAPI middleware for trace propagation and REST metrics."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from .context import bind_observability_context, clear_observability_context, current_trace_id
from .metrics import rest_request_seconds, rest_requests_total


def _route_label(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path or request.url.path)


async def observability_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    trace_id = request.headers.get("X-Trace-Id") or request.headers.get("X-Request-Id")
    session_id = request.headers.get("X-Session-Id") or request.query_params.get("session_id")
    tokens = bind_observability_context(trace_id=trace_id, session_id=session_id)
    route = _route_label(request)
    method = request.method
    start = time.perf_counter()
    status_code = "500"
    try:
        response = await call_next(request)
        status_code = str(response.status_code)
        if current_trace_id():
            response.headers["X-Trace-Id"] = current_trace_id() or ""
        return response
    finally:
        elapsed = time.perf_counter() - start
        rest_requests_total.labels(route=route, method=method, status_code=status_code).inc()
        rest_request_seconds.labels(route=route, method=method).observe(elapsed)
        clear_observability_context(tokens)
