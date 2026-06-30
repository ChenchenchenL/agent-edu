from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics", "/docs", "/redoc", "/openapi.json"})

_WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})


class _FixedWindowCounter:
    def __init__(self, window_seconds: int, max_requests: int) -> None:
        self._window_seconds = window_seconds
        self._max_requests = max_requests
        self._window_start: float = 0.0
        self._count: int = 0

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        if now - self._window_start >= self._window_seconds:
            self._window_start = now
            self._count = 0
        self._count += 1
        return self._count <= self._max_requests


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, per_minute: int, alert_dispatcher: object | None = None) -> None:
        super().__init__(app)
        self._per_minute = per_minute
        self._alert_dispatcher = alert_dispatcher
        self._counters: dict[str, _FixedWindowCounter] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._should_limit(request):
            return await call_next(request)

        key = self._extract_key(request)
        counter = self._counters.get(key)
        if counter is None:
            counter = _FixedWindowCounter(window_seconds=60, max_requests=self._per_minute)
            self._counters[key] = counter

        if not counter.is_allowed(key):
            if self._alert_dispatcher is not None:
                self._alert_dispatcher.dispatch(
                    alert_name="rate_limit_exceeded",
                    severity="warning",
                    message=f"Rate limit exceeded for key '{key}' ({self._per_minute}/min)",
                    details={"key": key, "limit_per_minute": self._per_minute},
                )
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limit_exceeded", "message": "Too many requests. Please retry later."}},
            )

        return await call_next(request)

    def _should_limit(self, request: Request) -> bool:
        if request.method not in _WRITE_METHODS:
            return False
        path = request.url.path
        if not path.startswith("/api/v1"):
            return False
        if path in _EXEMPT_PATHS:
            return False
        return True

    def _extract_key(self, request: Request) -> str:
        learner_key = request.headers.get("X-Learner-Key")
        if learner_key:
            return f"learner:{learner_key}"
        operator_key = request.headers.get("X-Operator-Key")
        if operator_key:
            return f"operator:{operator_key}"
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
