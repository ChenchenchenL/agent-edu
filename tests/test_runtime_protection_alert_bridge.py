"""Runtime protection alert bridge tests.

Verifies that the bridge forwards critical audit failure events to the alert
dispatcher exactly once, ignores non-critical events, and never raises even
when the dispatcher fails.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest

from agent_core.application.services.runtime_protection.alert_bridge import (
    CRITICAL_FAILURE_EVENT_TYPES,
    RuntimeProtectionAlertBridge,
)
from agent_core.domain.entities.audit import AuditEvent


def _event(event_type: str, event_id: str | None = None) -> AuditEvent:
    return AuditEvent(
        id=event_id or str(uuid4()),
        event_type=event_type,
        resource_type="job",
        resource_id="job-1",
        actor="system",
        event_data={"error": "simulated"},
        created_at=datetime.now(timezone.utc),
    )


class _StubAuditService:
    def __init__(self, events: list[AuditEvent]) -> None:
        self._events = events

    async def list_recent(self, *, limit: int = 50) -> list[AuditEvent]:
        return self._events[:limit]


class _RecordingDispatcher:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[dict[str, Any]] = []
        self._fail = fail

    def dispatch(self, **kwargs: Any) -> None:
        if self._fail:
            raise RuntimeError("dispatcher down")
        self.events.append(kwargs)


@pytest.mark.asyncio
async def test_bridge_alerts_on_critical_failure_event() -> None:
    events = [_event("memory_maintenance.job.failed", event_id="e1")]
    bridge = RuntimeProtectionAlertBridge(
        audit_service=_StubAuditService(events),
        alert_dispatcher=_RecordingDispatcher(),
    )

    result = await bridge.sweep()

    assert result.alerted == 1
    assert result.alert_names == ("memory_maintenance.job.failed",)
    assert bridge._alert_dispatcher.events[0]["alert_name"] == "audit.memory_maintenance.job.failed"
    assert bridge._alert_dispatcher.events[0]["severity"] == "error"


@pytest.mark.asyncio
async def test_bridge_ignores_non_critical_events() -> None:
    events = [
        _event("quiz.answer_attempt.submitted"),
        _event("llm.chat.completed"),
        _event("memory_maintenance.job.retry_scheduled"),
    ]
    bridge = RuntimeProtectionAlertBridge(
        audit_service=_StubAuditService(events),
        alert_dispatcher=_RecordingDispatcher(),
    )

    result = await bridge.sweep()

    assert result.alerted == 0
    assert result.alert_names == ()


@pytest.mark.asyncio
async def test_bridge_does_not_re_alert_same_event() -> None:
    events = [_event("autonomy.job.failed", event_id="e1")]
    dispatcher = _RecordingDispatcher()
    bridge = RuntimeProtectionAlertBridge(
        audit_service=_StubAuditService(events),
        alert_dispatcher=dispatcher,
    )

    await bridge.sweep()
    await bridge.sweep()
    await bridge.sweep()

    assert len(dispatcher.events) == 1


@pytest.mark.asyncio
async def test_bridge_alerts_on_replay_exhausted_with_critical_severity() -> None:
    events = [_event("long_term_memory.materialization.replay_exhausted")]
    dispatcher = _RecordingDispatcher()
    bridge = RuntimeProtectionAlertBridge(
        audit_service=_StubAuditService(events),
        alert_dispatcher=dispatcher,
    )

    await bridge.sweep()

    assert dispatcher.events[0]["severity"] == "critical"


@pytest.mark.asyncio
async def test_bridge_survives_dispatcher_failure() -> None:
    events = [_event("autonomy.job.failed", event_id="e1")]
    dispatcher = _RecordingDispatcher(fail=True)
    bridge = RuntimeProtectionAlertBridge(
        audit_service=_StubAuditService(events),
        alert_dispatcher=dispatcher,
    )

    # Must not raise.
    result = await bridge.sweep()
    assert result.seen_after == 1
    assert result.alerted == 0, "failed dispatch must not count as alerted"
    assert "e1" in bridge._alerted_ids, "event must still be marked to avoid retry storms"

    # Second sweep must not retry the same event.
    result = await bridge.sweep()
    assert result.alerted == 0


def test_critical_event_types_are_known() -> None:
    # Guard rail: if someone renames an audit event, this test fails and
    # forces an explicit decision about whether the alert should follow.
    assert "memory_maintenance.job.failed" in CRITICAL_FAILURE_EVENT_TYPES
    assert "autonomy.job.failed" in CRITICAL_FAILURE_EVENT_TYPES
