from __future__ import annotations

import asyncio
import logging

from agent_core.api.dependencies import (
    get_alert_dispatcher,
    get_audit_service,
    get_memory_maintenance_service,
    get_session_factory,
    get_skill_curator_job_service,
    get_skill_outcome_feedback_job_service,
    get_task_autonomy_scheduling_service,
)
from agent_core.application.services.runtime_protection.alert_bridge import (
    RuntimeProtectionAlertBridge,
)
from agent_core.infrastructure.config.settings import get_settings


LOGGER = logging.getLogger(__name__)


async def run_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_task_autonomy_scheduling_service(session)
        processed = await service.run_due_autonomy_jobs(raise_on_error=False, lease_owner="worker")
        return processed


async def run_memory_maintenance_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_memory_maintenance_service(session)
        return await service.run_due_jobs(raise_on_error=False, lease_owner="worker")


async def run_skill_curator_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_skill_curator_job_service(session)
        result = await service.run_once()
        await session.commit()
        return result.created_count + result.existing_count


async def run_skill_outcome_feedback_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_skill_outcome_feedback_job_service(session)
        result = await service.run_once()
        await session.commit()
        return result.quality_updated + result.flagged_for_review


async def _sweep_alert_bridge() -> None:
    """Run one alert-bridge sweep. Failures here must never break the worker.

    The bridge is best-effort observability: if it fails to read audit or to
    dispatch an alert, the worker must keep ticking. The underlying audit
    events remain the durable source of truth.
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            bridge = RuntimeProtectionAlertBridge(
                audit_service=get_audit_service(session),
                alert_dispatcher=get_alert_dispatcher(),
            )
            result = await bridge.sweep()
            if result.alerted:
                LOGGER.warning(
                    "runtime protection alert bridge dispatched %d alert(s): %s",
                    result.alerted,
                    ", ".join(result.alert_names),
                )
    except Exception:
        LOGGER.exception("runtime protection alert bridge sweep failed")


async def run_forever() -> None:
    settings = get_settings()
    interval = settings.autonomy_worker_poll_interval_seconds
    LOGGER.info("autonomy worker started with poll interval %.2fs", interval)
    while True:
        try:
            await run_once()
            await run_memory_maintenance_once()
            await run_skill_curator_once()
            await run_skill_outcome_feedback_once()
            await _sweep_alert_bridge()
        except Exception:
            LOGGER.exception("autonomy worker tick failed")
        await asyncio.sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
