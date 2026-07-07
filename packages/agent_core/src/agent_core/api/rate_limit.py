from __future__ import annotations

from hashlib import sha256
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

_EXEMPT_PATHS = frozenset({"/healthz", "/readyz", "/metrics", "/docs", "/redoc", "/openapi.json"})

_WRITE_METHODS = frozenset({"POST", "PATCH", "DELETE"})


def _hash_credential(value: str) -> str:
    """Hash a credential for use as a rate-limit key / log identifier.

    The raw learner access key and operator API key must never appear in logs,
    metrics, or alert details. A truncated SHA-256 prefix is sufficient for
    distinguishing callers while being irreversible.
    """
    return sha256(value.encode("utf-8")).hexdigest()[:12]


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

        scope, hashed_key = self._extract_key(request)
        counter = self._counters.get(hashed_key)
        if counter is None:
            counter = _FixedWindowCounter(window_seconds=60, max_requests=self._per_minute)
            self._counters[hashed_key] = counter

        if not counter.is_allowed(hashed_key):
            if self._alert_dispatcher is not None:
                self._alert_dispatcher.dispatch(
                    alert_name="rate_limit_exceeded",
                    severity="warning",
                    message=f"Rate limit exceeded for {scope} '{hashed_key}' ({self._per_minute}/min)",
                    details={
                        "scope": scope,
                        "key_hash": hashed_key,
                        "limit_per_minute": self._per_minute,
                    },
                )
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": "Too many requests. Please retry later.",
                        "retry_after_seconds": 60,
                    }
                },
                headers={"Retry-After": "60"},
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

    def _extract_key(self, request: Request) -> tuple[str, str]:
        """Return (scope, hashed_key) for the request.

        Scope is one of `learner`, `operator`, `ip`. The key is always hashed —
        raw credentials are never retained by the rate limiter.
        """
        learner_key = request.headers.get("X-Learner-Key")
        if learner_key and learner_key.strip():
            return "learner", f"learner:{_hash_credential(learner_key.strip())}"
        operator_key = request.headers.get("X-Operator-Key")
        if operator_key and operator_key.strip():
            return "operator", f"operator:{_hash_credential(operator_key.strip())}"
        client_ip = request.client.host if request.client else "unknown"
        return "ip", f"ip:{client_ip}"
