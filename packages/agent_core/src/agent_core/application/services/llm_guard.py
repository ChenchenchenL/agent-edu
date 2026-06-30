from __future__ import annotations

import time

from agent_core.domain.errors import ServiceError


class LLMCallGuard:
    def __init__(self, *, enabled: bool, max_calls_per_hour: int, alert_dispatcher: object | None = None) -> None:
        self._enabled = enabled
        self._max_calls = max_calls_per_hour
        self._alert_dispatcher = alert_dispatcher
        self._calls: list[float] = []

    def check(self) -> None:
        if not self._enabled:
            return
        now = time.monotonic()
        cutoff = now - 3600.0
        self._calls = [t for t in self._calls if t > cutoff]
        if len(self._calls) >= self._max_calls:
            if self._alert_dispatcher is not None:
                self._alert_dispatcher.dispatch(
                    alert_name="llm_call_budget_exhausted",
                    severity="critical",
                    message=f"LLM call budget exhausted ({self._max_calls}/hour)",
                    details={"limit_per_hour": self._max_calls, "calls_in_window": len(self._calls)},
                )
            raise ServiceError(
                "LLM call budget exhausted for the current hour. "
                "Please retry later or increase AGENT_EDU_LLM_CALL_LIMIT_PER_HOUR."
            )
        self._calls.append(now)

    @property
    def current_usage(self) -> dict[str, int]:
        now = time.monotonic()
        cutoff = now - 3600.0
        active = [t for t in self._calls if t > cutoff]
        return {
            "calls_in_window": len(active),
            "limit_per_hour": self._max_calls,
            "enabled": self._enabled,
        }
