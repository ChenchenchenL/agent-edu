"""MVP acceptance smoke test.

Chains the full MVP main path end-to-end:
  profile → goal → plan → task → session → chat/hint/quiz → memory → audit
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from agent_core.infrastructure.db.models import (
    AuditEventModel,
    KnowledgeMemoryModel,
    BehaviorMemoryModel,
    SessionMemoryEventModel,
)


def _learner_headers(access_key: str) -> dict[str, str]:
    return {"X-Learner-Key": access_key}


def _run_autonomy_worker_once() -> None:
    from agent_core.api import dependencies as api_dependencies

    async def _run() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            service = api_dependencies.get_task_autonomy_scheduling_service(db)
            await service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="mvp-test-worker")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


async def _fetch_audit_event_types() -> list[str]:
    engine = create_async_engine(os.environ["AGENT_EDU_DATABASE_URL"], future=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                select(AuditEventModel.event_type).order_by(AuditEventModel.created_at)
            )
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _fetch_session_memory_event_count() -> int:
    engine = create_async_engine(os.environ["AGENT_EDU_DATABASE_URL"], future=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(select(SessionMemoryEventModel.id))
            return len(result.scalars().all())
    finally:
        await engine.dispose()


def test_mvp_end_to_end_main_path(app_client_factory) -> None:
    """Single test that chains every MVP MUST path and verifies the result."""
    client = app_client_factory(
        env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"}
    )
    deadline = (date.today() + timedelta(days=21)).isoformat()

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

    # ── A3/A4: Create session bound to profile + goal ──
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

    # ── B1/B2: Chat → structured teaching response ──
    chat_resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
    )
    assert chat_resp.status_code == 200
    chat_payload = chat_resp.json()
    assert chat_payload["assistant_payload"]["type"] == "explanation"
    assert chat_payload["skill_trace"] == ["explain_concept"]

    # ── B3: Hint → adaptive hint (not direct answer) ──
    hint_resp = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Give me a hint on matrix multiplication.", "mode": "hint"},
    )
    assert hint_resp.status_code == 200
    hint_payload = hint_resp.json()
    assert hint_payload["assistant_payload"]["type"] == "hint"

    # ── B4: Quiz → structured questions bound to session ──
    quiz_resp = client.post(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        json={"topic": "Matrix multiplication", "difficulty": "easy", "question_count": 2},
    )
    assert quiz_resp.status_code == 200
    quiz_payload = quiz_resp.json()
    assert quiz_payload["question_count"] == 2
    assert quiz_payload["skill_trace"] == ["create_quiz"]

    # ── B5: Message history with pagination ──
    history_resp = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"limit": 2},
    )
    assert history_resp.status_code == 200
    history_payload = history_resp.json()
    assert history_payload["total"] >= 4
    assert len(history_payload["items"]) == 2
    assert history_payload["next_before_id"] is not None

    # ── C1/C2: Memory events written after chat turns ──
    memory_event_count = asyncio.run(_fetch_session_memory_event_count())
    assert memory_event_count >= 1, "Expected at least 1 session memory event after chat turns"

    # ── C8: Long-term memory retrieval API ──
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

    # ── D3/D4: Execute task → auto session creation ──
    execute_resp = client.post(
        f"/api/v1/tasks/{first_task['id']}/execute",
        headers=headers,
    )
    assert execute_resp.status_code == 200
    execute_payload = execute_resp.json()
    assert execute_payload["task"]["status"] == "in_progress"
    assert execute_payload["execution_session_id"] is not None

    # ── D5: Complete task → review scheduling via worker ──
    complete_resp = client.patch(
        f"/api/v1/tasks/{first_task['id']}/status",
        headers=headers,
        json={"status": "completed", "result_note": "Finished"},
    )
    assert complete_resp.status_code == 200
    assert complete_resp.json()["status"] == "completed"

    _run_autonomy_worker_once()

    tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_after.status_code == 200
    task_types = {item["task_type"] for item in tasks_after.json()}
    assert "review" in task_types, "Expected review task after completion + worker run"

    # ── A5: Workflow runs recorded ──
    runs_resp = client.get(f"/api/v1/goals/{goal_id}/workflow-runs", headers=headers)
    assert runs_resp.status_code == 200
    workflow_types = {item["workflow_type"] for item in runs_resp.json()}
    assert {"plan_generation", "task_execution"}.issubset(workflow_types)

    # ── E1-E7: Audit events cover the full chain ──
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
