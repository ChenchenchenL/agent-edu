from __future__ import annotations

import asyncio
import logging

from agent_core.api.dependencies import get_memory_maintenance_service, get_session_factory, get_task_service
from agent_core.infrastructure.config.settings import get_settings


LOGGER = logging.getLogger(__name__)


async def run_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_task_service(session)
        processed = await service.run_due_autonomy_jobs(raise_on_error=False, lease_owner="worker")
        return processed


async def run_memory_maintenance_once() -> int:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = get_memory_maintenance_service(session)
        return await service.run_due_jobs(raise_on_error=False, lease_owner="worker")


async def run_forever() -> None:
    settings = get_settings()
    interval = settings.autonomy_worker_poll_interval_seconds
    LOGGER.info("autonomy worker started with poll interval %.2fs", interval)
    while True:
        try:
            await run_once()
            await run_memory_maintenance_once()
        except Exception:
            LOGGER.exception("autonomy worker tick failed")
        await asyncio.sleep(interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
