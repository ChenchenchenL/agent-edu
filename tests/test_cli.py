from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from agent_core.api import dependencies as api_dependencies
from agent_core.api.app import create_app
from agent_core.api.routes import health as health_routes
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.cli.main import main
from agent_core.infrastructure.config.settings import get_settings
from agent_core.infrastructure.db.base import Base
from sqlalchemy.ext.asyncio import create_async_engine


class _FakeRedisClient:
    async def ping(self) -> bool:
        return True


async def _prepare_database(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def _clear_state() -> None:
    get_settings.cache_clear()
    api_dependencies.get_engine.cache_clear()
    api_dependencies.get_session_factory.cache_clear()
    api_dependencies.get_redis_client.cache_clear()
    api_dependencies.get_skill_registry.cache_clear()
    api_dependencies.get_llm_provider.cache_clear()
    api_dependencies.get_embedding_provider.cache_clear()


def _seed_embedded_env(monkeypatch, tmp_path: Path) -> tuple[str, Path]:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}"
    config_path = tmp_path / "agent-edu-config.json"
    monkeypatch.setenv("AGENT_EDU_APP_ENV", "testing")
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", database_url)
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv(
        "AGENT_EDU_ALLOWED_SKILLS",
        "explain_concept,create_quiz,adaptive_hint,plan_study_path,schedule_review",
    )
    monkeypatch.setenv("AGENT_EDU_LLM_PROVIDER", "mock")
    monkeypatch.setenv("AGENT_EDU_LLM_MODEL", "mock-tutor-v1")
    monkeypatch.setenv("AGENT_EDU_CLI_MODE", "embedded")
    monkeypatch.setenv("AGENT_EDU_CLI_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("AGENT_EDU_API_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_EDU_OPERATOR_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_EDU_LEARNER_ACCESS_KEY", raising=False)
    _clear_state()
    asyncio.run(_prepare_database(database_url))
    monkeypatch.setattr(health_routes, "get_redis_client", lambda: _FakeRedisClient())
    return database_url, config_path


def test_cli_doctor_goal_select_and_task_today(monkeypatch, tmp_path, capsys):
    _, config_path = _seed_embedded_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        profile = client.post("/api/v1/learner-profiles", json={}).json()
        headers = {"X-Learner-Key": profile["access_key"]}
        monkeypatch.setenv("AGENT_EDU_LEARNER_ACCESS_KEY", profile["access_key"])
        goal = client.post(
            f"/api/v1/learner-profiles/{profile['id']}/goals",
            headers=headers,
            json={
                "title": "Linear Algebra",
                "subject": "Matrices",
                "target_outcome": "Understand matrices",
                "baseline_note": "Needs basics",
                "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
                "weekly_study_minutes": 180,
            },
        ).json()
        create_plan = client.post(f"/api/v1/goals/{goal['id']}/plans", headers=headers, json={"trigger_source": "initial"})
        assert create_plan.status_code == 200

    exit_code = main(["--json", "doctor"])
    assert exit_code == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["mode"] == "embedded"
    assert doctor_payload["health_ok"] is True
    assert doctor_payload["ready_ok"] is True
    assert doctor_payload["auth_source"] == "learner"

    exit_code = main(["--json", "goal", "select", "--profile-id", profile["id"], "--goal-id", goal["id"]])
    assert exit_code == 0
    select_payload = json.loads(capsys.readouterr().out)
    assert select_payload["active_goal_id"] == goal["id"]
    assert config_path.exists()

    exit_code = main(["--json", "task", "today"])
    assert exit_code == 0
    tasks_payload = json.loads(capsys.readouterr().out)
    assert len(tasks_payload) >= 1
    assert tasks_payload[0]["learner_goal_id"] == goal["id"]


def test_cli_memory_browse_uses_active_context(monkeypatch, tmp_path, capsys):
    _, _ = _seed_embedded_env(monkeypatch, tmp_path)

    with TestClient(create_app()) as client:
        profile = client.post("/api/v1/learner-profiles", json={}).json()
        headers = {"X-Learner-Key": profile["access_key"]}
        monkeypatch.setenv("AGENT_EDU_LEARNER_ACCESS_KEY", profile["access_key"])
        goal = client.post(
            f"/api/v1/learner-profiles/{profile['id']}/goals",
            headers=headers,
            json={
                "title": "Linear Algebra",
                "subject": "Matrices",
                "target_outcome": "Understand matrices",
                "baseline_note": "Needs basics",
                "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
                "weekly_study_minutes": 180,
            },
        ).json()
        session = client.post(
            "/api/v1/sessions",
            json={
                "learner_profile_id": profile["id"],
                "learner_goal_id": goal["id"],
                "title": "Matrix session",
                "subject": "Matrices",
            },
        ).json()
        message = client.post(
            f"/api/v1/sessions/{session['id']}/messages",
            json={"content": "Explain matrix multiplication.", "mode": "chat"},
        )
        assert message.status_code == 200
        session_factory = api_dependencies.get_session_factory()

        async def seed_long_term_memory() -> None:
            async with session_factory() as db:
                service = api_dependencies.get_memory_service(db)
                materialization_service = LongTermMemoryMaterializationService(service)
                memory_events = await service.record_learning_memories(
                    session_id=session["id"],
                    learner_profile_id=profile["id"],
                    learner_message="Explain matrix multiplication.",
                    assistant_message=message.json()["assistant_message"],
                    source_message_id=message.json()["user_message_id"],
                    mode="chat",
                    subject="Matrices",
                    session_title="Matrix session",
                )
                await materialization_service.materialize_from_chat_turn(
                    session_id=session["id"],
                    learner_profile_id=profile["id"],
                    learner_goal_id=goal["id"],
                    learner_message="Explain matrix multiplication.",
                    assistant_message=message.json()["assistant_message"],
                    source_message_id=message.json()["user_message_id"],
                    mode="chat",
                    subject="Matrices",
                    session_title="Matrix session",
                    memory_events=memory_events,
                    persist_embeddings=True,
                )
                await db.commit()

        asyncio.run(seed_long_term_memory())

    main(["--json", "goal", "select", "--profile-id", profile["id"], "--goal-id", goal["id"]])
    capsys.readouterr()

    exit_code = main(["--json", "memory", "browse", "--type", "knowledge", "--limit", "5"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] >= 1
    assert len(payload["items"]) >= 1
