from __future__ import annotations

from dataclasses import dataclass

from agent_core.infrastructure.container import ApplicationContainer


@dataclass
class _FakeTaskCore:
    session_id: int


@dataclass
class _FakeMemoryService:
    session_id: int


def test_request_scope_caches_task_services():
    calls: list[int] = []

    def build_task_core(session):
        calls.append(id(session))
        return _FakeTaskCore(session_id=id(session))

    container = ApplicationContainer(
        task_core_builder=build_task_core,
        memory_service_builder=lambda session: _FakeMemoryService(session_id=id(session)),
    )
    session = object()
    scope = container.scope(session)

    first = scope.task_services()
    second = scope.task_services()

    assert first is second
    assert first.core.session_id == id(session)
    assert calls == [id(session)]


def test_request_scope_caches_memory_service():
    container = ApplicationContainer(
        task_core_builder=lambda session: _FakeTaskCore(session_id=id(session)),
        memory_service_builder=lambda session: _FakeMemoryService(session_id=id(session)),
    )
    session = object()
    scope = container.scope(session)

    first = scope.memory_service()
    second = scope.memory_service()

    assert first is second
    assert first.session_id == id(session)
