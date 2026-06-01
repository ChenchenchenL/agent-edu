from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from httpx import ASGITransport, Response

from agent_core.api.app import create_app
from agent_core.domain.schemas.autonomy import GoalAutonomyStateResponse, ScheduledAutonomyJobResponse
from agent_core.domain.schemas.goal import LearnerGoalResponse, LearnerProfileResponse
from agent_core.domain.schemas.memory import (
    BehaviorMemoryBrowseResponse,
    BehaviorMemoryRetrievalResponse,
    KnowledgeMemoryBrowseResponse,
    KnowledgeMemoryRetrievalResponse,
)
from agent_core.domain.schemas.planning import DailyTaskResponse, ExecuteDailyTaskResponse
from agent_core.domain.schemas.session import MessageHistoryResponse, MessageRequest, MessageResponse
from agent_core.domain.schemas.workspace import WorkspaceSummaryResponse


@dataclass(frozen=True)
class DoctorReport:
    mode: str
    base_url: str
    health_ok: bool
    ready_ok: bool
    auth_source: str
    active_profile_id: str | None
    active_goal_id: str | None
    errors: list[str]


class BackendClient(Protocol):
    async def close(self) -> None: ...

    async def doctor(self, *, active_profile_id: str | None, active_goal_id: str | None) -> DoctorReport: ...

    async def list_profiles(self) -> list[LearnerProfileResponse]: ...

    async def list_goals(self, profile_id: str) -> list[LearnerGoalResponse]: ...

    async def get_workspace(self, profile_id: str, goal_id: str | None = None) -> WorkspaceSummaryResponse: ...

    async def list_tasks_today(self, goal_id: str) -> list[DailyTaskResponse]: ...
    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJobResponse]: ...
    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse: ...

    async def execute_task(self, task_id: str) -> ExecuteDailyTaskResponse: ...

    async def update_task_status(self, task_id: str, *, status: str, result_note: str | None) -> DailyTaskResponse: ...

    async def get_message_history(self, session_id: str, *, limit: int = 20) -> MessageHistoryResponse: ...

    async def create_message(self, session_id: str, payload: MessageRequest) -> MessageResponse: ...

    async def retrieve_knowledge_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3
    ) -> KnowledgeMemoryRetrievalResponse: ...

    async def retrieve_behavior_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3
    ) -> BehaviorMemoryRetrievalResponse: ...

    async def browse_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> KnowledgeMemoryBrowseResponse: ...

    async def browse_behavior_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BehaviorMemoryBrowseResponse: ...


class HttpBackendClient:
    def __init__(
        self,
        *,
        mode: str,
        client: httpx.AsyncClient,
        operator_api_key: str | None = None,
        learner_access_key: str | None = None,
    ) -> None:
        self._mode = mode
        self._client = client
        self._operator_api_key = operator_api_key
        self._learner_access_key = learner_access_key

    async def close(self) -> None:
        await self._client.aclose()

    async def doctor(self, *, active_profile_id: str | None, active_goal_id: str | None) -> DoctorReport:
        errors: list[str] = []
        health_ok = False
        ready_ok = False
        try:
            health = await self._client.get("/healthz")
            health.raise_for_status()
            health_ok = health.json().get("status") == "ok"
        except Exception as exc:  # pragma: no cover - surfaced via CLI
            errors.append(f"healthz: {exc}")
        try:
            ready = await self._client.get("/readyz")
            ready_ok = ready.status_code == 200 and ready.json().get("status") == "ready"
            if ready.status_code != 200:
                errors.append(f"readyz: {ready.text}")
        except Exception as exc:  # pragma: no cover - surfaced via CLI
            errors.append(f"readyz: {exc}")
        return DoctorReport(
            mode=self._mode,
            base_url=str(self._client.base_url).rstrip("/"),
            health_ok=health_ok,
            ready_ok=ready_ok,
            auth_source=self._auth_source(),
            active_profile_id=active_profile_id,
            active_goal_id=active_goal_id,
            errors=errors,
        )

    def _auth_source(self) -> str:
        if self._operator_api_key:
            return "operator"
        if self._learner_access_key:
            return "learner"
        return "missing"

    async def list_profiles(self) -> list[LearnerProfileResponse]:
        response = await self._client.get("/api/v1/learner-profiles")
        return _parse_list(response, LearnerProfileResponse)

    async def list_goals(self, profile_id: str) -> list[LearnerGoalResponse]:
        response = await self._client.get(f"/api/v1/learner-profiles/{profile_id}/goals")
        return _parse_list(response, LearnerGoalResponse)

    async def get_workspace(self, profile_id: str, goal_id: str | None = None) -> WorkspaceSummaryResponse:
        params = {"goal_id": goal_id} if goal_id is not None else None
        response = await self._client.get(f"/api/v1/learner-profiles/{profile_id}/workspace", params=params)
        return _parse_model(response, WorkspaceSummaryResponse)

    async def list_tasks_today(self, goal_id: str) -> list[DailyTaskResponse]:
        response = await self._client.get(
            f"/api/v1/goals/{goal_id}/tasks",
            params=[("status", "pending"), ("status", "in_progress")],
        )
        return _parse_list(response, DailyTaskResponse)

    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJobResponse]:
        response = await self._client.get(f"/api/v1/goals/{goal_id}/autonomy/jobs")
        return _parse_list(response, ScheduledAutonomyJobResponse)

    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse:
        response = await self._client.post(f"/api/v1/goals/{goal_id}/autonomy/materialize-today")
        return _parse_model(response, GoalAutonomyStateResponse)

    async def execute_task(self, task_id: str) -> ExecuteDailyTaskResponse:
        response = await self._client.post(f"/api/v1/tasks/{task_id}/execute")
        return _parse_model(response, ExecuteDailyTaskResponse)

    async def update_task_status(self, task_id: str, *, status: str, result_note: str | None) -> DailyTaskResponse:
        response = await self._client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": status, "result_note": result_note},
        )
        return _parse_model(response, DailyTaskResponse)

    async def get_message_history(self, session_id: str, *, limit: int = 20) -> MessageHistoryResponse:
        response = await self._client.get(f"/api/v1/sessions/{session_id}/messages", params={"limit": limit})
        return _parse_model(response, MessageHistoryResponse)

    async def create_message(self, session_id: str, payload: MessageRequest) -> MessageResponse:
        response = await self._client.post(f"/api/v1/sessions/{session_id}/messages", json=payload.model_dump())
        return _parse_model(response, MessageResponse)

    async def retrieve_knowledge_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3
    ) -> KnowledgeMemoryRetrievalResponse:
        response = await self._client.get(
            "/api/v1/memory/knowledge",
            params={"learner_profile_id": learner_profile_id, "query_text": query_text, "limit": limit},
        )
        return _parse_model(response, KnowledgeMemoryRetrievalResponse)

    async def retrieve_behavior_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3
    ) -> BehaviorMemoryRetrievalResponse:
        response = await self._client.get(
            "/api/v1/memory/behavior",
            params={"learner_profile_id": learner_profile_id, "query_text": query_text, "limit": limit},
        )
        return _parse_model(response, BehaviorMemoryRetrievalResponse)

    async def browse_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> KnowledgeMemoryBrowseResponse:
        params: list[tuple[str, str | int]] = [
            ("learner_profile_id", learner_profile_id),
            ("limit", limit),
            ("offset", offset),
        ]
        if learner_goal_id is not None:
            params.append(("learner_goal_id", learner_goal_id))
        for status in statuses or []:
            params.append(("status", status))
        response = await self._client.get("/api/v1/memory/knowledge/browse", params=params)
        return _parse_model(response, KnowledgeMemoryBrowseResponse)

    async def browse_behavior_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BehaviorMemoryBrowseResponse:
        params: list[tuple[str, str | int]] = [
            ("learner_profile_id", learner_profile_id),
            ("limit", limit),
            ("offset", offset),
        ]
        if learner_goal_id is not None:
            params.append(("learner_goal_id", learner_goal_id))
        for status in statuses or []:
            params.append(("status", status))
        response = await self._client.get("/api/v1/memory/behavior/browse", params=params)
        return _parse_model(response, BehaviorMemoryBrowseResponse)


def create_remote_client(
    base_url: str,
    *,
    operator_api_key: str | None = None,
    learner_access_key: str | None = None,
) -> BackendClient:
    headers = _build_auth_headers(operator_api_key=operator_api_key, learner_access_key=learner_access_key)
    client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=30.0, headers=headers)
    return HttpBackendClient(
        mode="remote",
        client=client,
        operator_api_key=operator_api_key,
        learner_access_key=learner_access_key,
    )


def create_embedded_client(
    *,
    operator_api_key: str | None = None,
    learner_access_key: str | None = None,
) -> BackendClient:
    headers = _build_auth_headers(operator_api_key=operator_api_key, learner_access_key=learner_access_key)
    transport = ASGITransport(app=create_app())
    client = httpx.AsyncClient(base_url="http://agent-edu.local", transport=transport, timeout=30.0, headers=headers)
    return HttpBackendClient(
        mode="embedded",
        client=client,
        operator_api_key=operator_api_key,
        learner_access_key=learner_access_key,
    )


def _build_auth_headers(
    *,
    operator_api_key: str | None,
    learner_access_key: str | None,
) -> dict[str, str] | None:
    headers: dict[str, str] = {}
    if operator_api_key:
        headers["X-Operator-Key"] = operator_api_key
    if learner_access_key:
        headers["X-Learner-Key"] = learner_access_key
    return headers or None


def _parse_model(response: Response, schema: type[Any]) -> Any:
    response.raise_for_status()
    return schema.model_validate(response.json())


def _parse_list(response: Response, schema: type[Any]) -> list[Any]:
    response.raise_for_status()
    payload = response.json()
    return [schema.model_validate(item) for item in payload]
