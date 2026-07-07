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
        name: str = "provider",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._failure_count: int = 0
        self._opened_at: float = 0.0
        self._state: str = "closed"
        self._name = name

    @property
    def name(self) -> str:
        return self._name

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
            f"{self._name} circuit breaker is open. "
            "Too many consecutive failures. Please retry later.",
            error_code="circuit_open",
        )

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "closed"
        self._opened_at = 0.0

    def record_failure(self) -> None:
        if self._state == "half_open":
            # A half-open probe failed: re-open with a fresh failure count so
            # the full cooldown must elapse before the next probe.
            self._failure_count = 1
            self._state = "open"
            self._opened_at = time.monotonic()
            return
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
            "name": self._name,
            "state": self.state,
            "failure_count": self._failure_count,
            "failure_threshold": self._failure_threshold,
            "cooldown_seconds": self._cooldown_seconds,
        }
