from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.worker.main import run_memory_maintenance_once, run_once, run_skill_curator_once


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class _FakeSessionFactory:
    def __init__(self) -> None:
        self.session = _FakeSession()

    def __call__(self) -> "_FakeSessionFactory":
        return self

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeService:
    async def run_due_autonomy_jobs(self, *, raise_on_error: bool, lease_owner: str) -> int:
        assert raise_on_error is False
        assert lease_owner == "worker"
        return 0


class _FakeMemoryService:
    async def run_memory_maintenance(self, *, batch_size: int):
        raise AssertionError("worker must not call legacy full memory maintenance")

    async def run_due_jobs(self, *, raise_on_error: bool, lease_owner: str) -> int:
        assert raise_on_error is False
        assert lease_owner == "worker"
        return 3


class _FakeSkillCuratorResult:
    created_count = 2
    existing_count = 1


class _FakeSkillCuratorService:
    async def run_once(self) -> _FakeSkillCuratorResult:
        return _FakeSkillCuratorResult()


@pytest.mark.asyncio
async def test_worker_run_once_handles_empty_queue(monkeypatch):
    monkeypatch.setattr("apps.worker.main.get_session_factory", lambda: _FakeSessionFactory())
    monkeypatch.setattr("apps.worker.main.get_task_autonomy_scheduling_service", lambda session: _FakeService())

    processed = await run_once()

    assert processed == 0


@pytest.mark.asyncio
async def test_worker_run_memory_maintenance_once_aggregates_counts(monkeypatch):
    session_factory = _FakeSessionFactory()
    monkeypatch.setattr("apps.worker.main.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("apps.worker.main.get_memory_maintenance_service", lambda session: _FakeMemoryService())

    processed = await run_memory_maintenance_once()

    assert processed == 3
    assert session_factory.session.committed is False


@pytest.mark.asyncio
async def test_worker_run_skill_curator_once_commits_recommendations(monkeypatch):
    session_factory = _FakeSessionFactory()
    monkeypatch.setattr("apps.worker.main.get_session_factory", lambda: session_factory)
    monkeypatch.setattr("apps.worker.main.get_skill_curator_job_service", lambda session: _FakeSkillCuratorService())

    processed = await run_skill_curator_once()

    assert processed == 3
    assert session_factory.session.committed is True
