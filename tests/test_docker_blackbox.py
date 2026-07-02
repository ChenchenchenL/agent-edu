"""Docker blackbox tests for the agent-edu API.

Contains two tests:
1. test_external_mock_api_blackbox - simple session/chat/quiz smoke test
2. test_docker_mvp_full_chain - full MVP path: profile→goal→plan→task→session→chat→hint→quiz→memory→audit
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine


pytestmark = pytest.mark.skipif(
    not os.getenv("AGENT_EDU_API_BASE_URL"),
    reason="External API blackbox tests require AGENT_EDU_API_BASE_URL.",
)


def _learner_headers(access_key: str) -> dict[str, str]:
    return {"X-Learner-Key": access_key}


def _post_with_retry(client: httpx.Client, path: str, payload: dict, *, retries: int = 2) -> httpx.Response:
    last_response: httpx.Response | None = None
    for attempt in range(retries + 1):
        response = client.post(path, json=payload)
        if response.status_code == 200:
            return response
        last_response = response
        if response.status_code != 503 or attempt >= retries:
            break
    assert last_response is not None
    return last_response


def _run_autonomy_worker_once() -> None:
    from agent_core.api import dependencies as api_dependencies

    async def _run() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            service = api_dependencies.get_task_autonomy_scheduling_service(db)
            await service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="docker-blackbox-worker")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


async def _fetch_audit_event_types() -> list[str]:
    db_url = os.environ["AGENT_EDU_DATABASE_URL"]
    engine = create_async_engine(db_url, future=True)
    try:
        from agent_core.infrastructure.db.models import AuditEventModel
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditEventModel.event_type).order_by(AuditEventModel.created_at)
            )
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _fetch_session_memory_event_count() -> int:
    db_url = os.environ["AGENT_EDU_DATABASE_URL"]
    engine = create_async_engine(db_url, future=True)
    try:
        from agent_core.infrastructure.db.models import SessionMemoryEventModel
        async with engine.connect() as conn:
            result = await conn.execute(select(SessionMemoryEventModel.id))
            return len(result.scalars().all())
    finally:
        await engine.dispose()


def test_external_mock_api_blackbox():
    base_url = os.environ["AGENT_EDU_API_BASE_URL"].rstrip("/")

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        health = client.get("/healthz")
        assert health.status_code == 200

        ready = client.get("/readyz")
        assert ready.status_code == 200

        session_response = client.post(
            "/api/v1/sessions",
            json={"title": "Docker Blackbox", "subject": "Matrices"},
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["id"]

        chat_response = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/messages",
            {"content": "Explain matrix multiplication simply.", "mode": "chat"},
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["assistant_payload"]["type"] == "explanation"

        quiz_response = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/quizzes/generate",
            {"topic": "Matrices", "difficulty": "easy", "question_count": 2},
        )
        assert quiz_response.status_code == 200
        quiz_payload = quiz_response.json()
        assert len(quiz_payload["questions"]) == 2

        hint_response = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/messages",
            {
                "content": "I think my answer is wrong. Give me a hint.",
                "mode": "hint",
                "related_quiz_id": quiz_payload["quiz_id"],
                "question_prompt": quiz_payload["questions"][0]["prompt"],
                "learner_answer": "I multiplied matching positions directly.",
            },
        )
        assert hint_response.status_code == 200
        hint_payload = hint_response.json()
        assert hint_payload["assistant_payload"]["type"] == "hint"
        assert hint_payload["turn_metrics"]["history_count"] >= 2

        history_response = client.get(f"/api/v1/sessions/{session_id}/messages", params={"limit": 10})
        assert history_response.status_code == 200
        assert history_response.json()["total"] >= 4

        detail_response = client.get(f"/api/v1/sessions/{session_id}/quizzes/{quiz_payload['quiz_id']}")
        assert detail_response.status_code == 200
        assert detail_response.json()["quiz_id"] == quiz_payload["quiz_id"]

        metrics_response = client.get("/metrics")
        assert metrics_response.status_code == 200
        assert "agent_edu_http_requests_total" in metrics_response.text
        assert "agent_edu_llm_operations_total" in metrics_response.text


def test_docker_mvp_full_chain():
    """Full MVP main path chained against a live Docker-deployed API.

    profile → goal → plan → task → session → chat/hint/quiz → memory → task execution → workflow → audit
    """
    from datetime import date, timedelta

    base_url = os.environ["AGENT_EDU_API_BASE_URL"].rstrip("/")
    deadline = (date.today() + timedelta(days=21)).isoformat()

    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        # ── Health checks ──
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200

        # ── A1: Create learner profile ──
        profile_resp = client.post("/api/v1/learner-profiles", json={})
        assert profile_resp.status_code == 200
        profile_id = profile_resp.json()["id"]
        access_key = profile_resp.json()["access_key"]
        headers = _learner_headers(access_key)

        # ── A2: Create learner goal ──
        goal_resp = client.post(
            f"/api/v1/learner-profiles/{profile_id}/goals",
            headers=headers,
            json={
                "title": "Master matrices",
                "subject": "Linear Algebra",
                "target_outcome": "Solve core matrix exercises independently",
                "baseline_note": "Learner struggles with dimensions.",
                "deadline_date": deadline,
                "weekly_study_minutes": 180,
            },
        )
        assert goal_resp.status_code == 200
        goal_id = goal_resp.json()["id"]

        # ── D1: Generate study plan ──
        plan_resp = client.post(
            f"/api/v1/goals/{goal_id}/plans",
            headers=headers,
            json={"trigger_source": "initial"},
        )
        assert plan_resp.status_code == 200
        plan_payload = plan_resp.json()
        assert plan_payload["version"] == 1
        assert len(plan_payload["stages"]) >= 2

        # ── D2: List daily tasks ──
        tasks_resp = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
        assert tasks_resp.status_code == 200
        task_payloads = tasks_resp.json()
        assert len(task_payloads) >= 1
        first_task = task_payloads[0]

        # ── A3: Create session bound to profile + goal ──
        session_resp = client.post(
            "/api/v1/sessions",
            json={
                "title": "Matrix basics",
                "subject": "Linear Algebra",
                "learner_profile_id": profile_id,
                "learner_goal_id": goal_id,
            },
        )
        assert session_resp.status_code == 200
        session_id = session_resp.json()["id"]

        # ── B1: Chat → structured teaching response ──
        chat_resp = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/messages",
            {"content": "Explain matrix multiplication simply.", "mode": "chat"},
        )
        assert chat_resp.status_code == 200
        chat_payload = chat_resp.json()
        assert chat_payload["assistant_payload"]["type"] == "explanation"
        assert chat_payload["skill_trace"] == ["explain_concept"]

        # ── B2: Hint → adaptive hint ──
        hint_resp = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/messages",
            {"content": "Give me a hint on matrix multiplication.", "mode": "hint"},
        )
        assert hint_resp.status_code == 200
        hint_payload = hint_resp.json()
        assert hint_payload["assistant_payload"]["type"] == "hint"

        # ── B3: Quiz → structured questions ──
        quiz_resp = _post_with_retry(
            client,
            f"/api/v1/sessions/{session_id}/quizzes/generate",
            {"topic": "Matrix multiplication", "difficulty": "easy", "question_count": 2},
        )
        assert quiz_resp.status_code == 200
        quiz_payload = quiz_resp.json()
        assert quiz_payload["question_count"] == 2
        assert quiz_payload["skill_trace"] == ["create_quiz"]

        # ── B4: Message history with pagination ──
        history_resp = client.get(
            f"/api/v1/sessions/{session_id}/messages",
            params={"limit": 2},
        )
        assert history_resp.status_code == 200
        history_payload = history_resp.json()
        assert history_payload["total"] >= 4
        assert len(history_payload["items"]) == 2
        assert history_payload["next_before_id"] is not None

        # ── C1: Memory events written after chat turns ──
        memory_event_count = asyncio.run(_fetch_session_memory_event_count())
        assert memory_event_count >= 1, "Expected at least 1 session memory event after chat turns"

        # ── C2: Long-term memory retrieval API ──
        knowledge_resp = client.get(
            "/api/v1/memory/knowledge",
            headers=headers,
            params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
        )
        assert knowledge_resp.status_code == 200
        assert "items" in knowledge_resp.json()

        behavior_resp = client.get(
            "/api/v1/memory/behavior",
            headers=headers,
            params={"learner_profile_id": profile_id, "query_text": "I need a hint"},
        )
        assert behavior_resp.status_code == 200
        assert "items" in behavior_resp.json()

        # ── D3: Execute task → auto session creation ──
        execute_resp = client.post(
            f"/api/v1/tasks/{first_task['id']}/execute",
            headers=headers,
        )
        assert execute_resp.status_code == 200
        execute_payload = execute_resp.json()
        assert execute_payload["task"]["status"] == "in_progress"
        assert execute_payload["execution_session_id"] is not None

        # ── D4: Complete task ──
        complete_resp = client.patch(
            f"/api/v1/tasks/{first_task['id']}/status",
            headers=headers,
            json={"status": "completed", "result_note": "Finished"},
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["status"] == "completed"

        # ── D5: Trigger autonomy worker → review task scheduling ──
        _run_autonomy_worker_once()

        tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
        assert tasks_after.status_code == 200
        task_types = {item["task_type"] for item in tasks_after.json()}
        assert "review" in task_types, "Expected review task after completion + worker run"

        # ── A4: Workflow runs recorded ──
        runs_resp = client.get(f"/api/v1/goals/{goal_id}/workflow-runs", headers=headers)
        assert runs_resp.status_code == 200
        workflow_types = {item["workflow_type"] for item in runs_resp.json()}
        assert {"plan_generation", "task_execution"}.issubset(workflow_types)

        # ── E1: Audit events cover the full chain ──
        audit_types = asyncio.run(_fetch_audit_event_types())
        assert len(audit_types) >= 5, f"Expected at least 5 audit events, got {len(audit_types)}"

        expected_audit_prefixes = [
            "session.",
            "session.message.",
            "quiz.",
            "memory.",
            "llm.",
        ]
        for prefix in expected_audit_prefixes:
            assert any(
                event_type.startswith(prefix) for event_type in audit_types
            ), f"Expected audit event with prefix '{prefix}', got: {audit_types}"

        # ── Metrics ──
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "agent_edu_http_requests_total" in metrics_resp.text
