"""Runtime protection alert bridge.

Bridges durable audit events to real-time operator alerts. The worker records
job failures as audit events (the source of truth); this module scans for new
failure events after each job tick and forwards the critical ones to the
AlertDispatcher so operators get notified without polling audit.

The bridge is intentionally simple: it does not dedupe, throttle, or classify
severity beyond what the audit event already carries. Those concerns belong in
a future alerting service; this module's job is to make sure the signal
reaches the dispatcher at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.infrastructure.observability.alerts import AlertDispatcher


_LOGGER = logging.getLogger(__name__)


# Audit event types that must trigger an immediate operator alert. Keep this
# list small and high-signal: these are the failures an operator cannot afford
# to discover by polling audit.
CRITICAL_FAILURE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "memory_maintenance.job.failed",
        "autonomy.job.failed",
        "skill_curator.job.failed",
        "reflection_skill_evolution_curator.pass_failed",
        "long_term_memory.materialization.replay_exhausted",
    }
)


@dataclass(frozen=True)
class AlertBridgeResult:
    """Result of a single bridge sweep."""

    seen_after: int
    alerted: int
    alert_names: tuple[str, ...]


class RuntimeProtectionAlertBridge:
    """Forward critical audit failure events to the AlertDispatcher."""

    def __init__(
        self,
        *,
        audit_service: AuditService,
        alert_dispatcher: AlertDispatcher,
    ) -> None:
        self._audit_service = audit_service
        self._alert_dispatcher = alert_dispatcher
        self._alerted_ids: set[str] = set()

    async def sweep(self) -> AlertBridgeResult:
        """Scan recent audit events and alert on any critical failures.

        The sweep is idempotent: events already alerted in a prior sweep are
        tracked by their id and skipped on subsequent sweeps. Dispatcher
        failures are logged and swallowed — alert delivery is best-effort,
        the durable audit event remains the source of truth.
        """
        events = await self._audit_service.list_recent(limit=50)
        alerted: list[str] = []
        for event in events:
            if event.event_type not in CRITICAL_FAILURE_EVENT_TYPES:
                continue
            if event.id in self._alerted_ids:
                continue
            severity = _severity_for(event.event_type)
            try:
                self._alert_dispatcher.dispatch(
                    alert_name=f"audit.{event.event_type}",
                    severity=severity,
                    message=f"Critical job failure: {event.event_type}",
                    details=_details_for(event),
                )
            except Exception:
                _LOGGER.exception(
                    "alert dispatcher failed for event=%s; continuing",
                    event.event_type,
                )
            else:
                alerted.append(event.event_type)
            # Mark alerted regardless of dispatch outcome: we do not want to
            # retry a failed alert on every sweep and flood the log.
            self._alerted_ids.add(event.id)
        self._trim_alerted_ids()
        return AlertBridgeResult(
            seen_after=len(events),
            alerted=len(alerted),
            alert_names=tuple(alerted),
        )

    def _trim_alerted_ids(self) -> None:
        # Bounded cache: keep the last 500 event ids to prevent unbounded
        # growth across long-running workers.
        if len(self._alerted_ids) <= 500:
            return
        # Drop older entries by retaining the most recent half. This is a
        # pragmatic trade-off; a real deployment would persist this state in
        # Redis.
        recent = list(self._alerted_ids)[-250:]
        self._alerted_ids = set(recent)


def _severity_for(event_type: str) -> str:
    if "exhausted" in event_type:
        return "critical"
    if "failed" in event_type:
        return "error"
    return "warning"


def _details_for(event: Any) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "actor": event.actor,
        "event_data": event.event_data or {},
    }
