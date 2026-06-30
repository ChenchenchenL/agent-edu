from __future__ import annotations

import time

from agent_core.domain.errors import ServiceError


class CircuitBreaker:
    """Simple circuit breaker with closed / open / half-open states.

    - closed: normal operation, failures are counted
    - open: calls are rejected immediately, no provider contact
    - half-open: one probe call is allowed through; success resets, failure re-opens
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        cooldown_seconds: float,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._failure_count: int = 0
        self._opened_at: float = 0.0
        self._state: str = "closed"

    @property
    def state(self) -> str:
        if self._state == "open" and self._cooldown_elapsed():
            self._state = "half_open"
        return self._state

    def allow_call(self) -> None:
        current = self.state
        if current == "closed":
            return
        if current == "half_open":
            return
        raise ServiceError(
            "LLM provider circuit breaker is open. "
            "Too many consecutive failures. Please retry later."
        )

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"
        self._opened_at = 0.0

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()

    def _cooldown_elapsed(self) -> bool:
        if self._opened_at == 0.0:
            return False
        return (time.monotonic() - self._opened_at) >= self._cooldown_seconds

    @property
    def status(self) -> dict[str, object]:
        return {
            "state": self.state,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "cooldown_seconds": self._cooldown_seconds,
        }
