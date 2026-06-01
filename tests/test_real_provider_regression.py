from __future__ import annotations

import os

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.infrastructure.db.models import AuditEventModel


pytestmark = pytest.mark.skipif(
    os.getenv("AGENT_EDU_RUN_REAL_PROVIDER_REGRESSION") != "1"
    or not os.getenv("AGENT_EDU_API_BASE_URL")
    or not os.getenv("AGENT_EDU_DATABASE_URL"),
    reason="Real provider regression requires API base URL, database URL, and explicit opt-in.",
)


@pytest.mark.asyncio
async def test_real_provider_regression_chain_records_provider_audit_metadata():
    base_url = os.environ["AGENT_EDU_API_BASE_URL"].rstrip("/")
    database_url = os.environ["AGENT_EDU_DATABASE_URL"]

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        async def post_json(path: str, payload: dict[str, object], *, retries: int = 2) -> httpx.Response:
            last_response: httpx.Response | None = None
            for attempt in range(retries + 1):
                response = await client.post(path, json=payload)
                if response.status_code == 200:
                    return response
                last_response = response
                if response.status_code != 503 or attempt >= retries:
                    break
            assert last_response is not None
            return last_response

        seed_session_response = await client.post(
            "/api/v1/sessions",
            json={"title": "Real Provider Seed", "subject": "Matrices"},
        )
        assert seed_session_response.status_code == 200
        seed_session_id = seed_session_response.json()["id"]

        seed_chat_response = await post_json(
            f"/api/v1/sessions/{seed_session_id}/messages",
            {"content": "Explain matrix addition simply.", "mode": "chat"},
        )
        assert seed_chat_response.status_code == 200

        session_response = await client.post(
            "/api/v1/sessions",
            json={"title": "Real Provider Main", "subject": "Matrices"},
        )
        assert session_response.status_code == 200
        session_id = session_response.json()["id"]

        chat_response = await post_json(
            f"/api/v1/sessions/{session_id}/messages",
            {"content": "Explain matrix multiplication simply.", "mode": "chat"},
        )
        assert chat_response.status_code == 200
        chat_payload = chat_response.json()
        assert chat_payload["assistant_payload"]["type"] == "explanation"

        quiz_response = await post_json(
            f"/api/v1/sessions/{session_id}/quizzes/generate",
            {"topic": "Matrices", "difficulty": "easy", "question_count": 2},
        )
        assert quiz_response.status_code == 200
        quiz_payload = quiz_response.json()

        hint_response = await post_json(
            f"/api/v1/sessions/{session_id}/messages",
            {
                "content": "I think my answer is wrong. Give me a hint instead.",
                "mode": "hint",
                "related_quiz_id": quiz_payload["quiz_id"],
                "question_prompt": quiz_payload["questions"][0]["prompt"],
                "learner_answer": "I think you multiply matching positions directly.",
            },
        )
        assert hint_response.status_code == 200
        hint_payload = hint_response.json()
        assert hint_payload["assistant_payload"]["type"] == "hint"
        assert hint_payload["turn_metrics"]["hint_level"] in {"scaffolded", "targeted"}

    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(AuditEventModel).where(
                    AuditEventModel.resource_id == session_id,
                    AuditEventModel.event_type.in_(
                        [
                            "llm.chat.completed",
                            "llm.quiz.completed",
                            "embedding.query.completed",
                        ]
                    ),
                )
            )
            events = result.scalars().all()

        by_type = {event.event_type: event for event in events}
        assert "llm.chat.completed" in by_type
        assert "llm.quiz.completed" in by_type
        assert "embedding.query.completed" in by_type

        llm_chat = by_type["llm.chat.completed"].event_data
        assert llm_chat["provider"] == "dashscope_compatible"
        assert llm_chat["model"]
        assert llm_chat["latency_ms"] > 0
        assert llm_chat["response_shape_valid"] is True

        llm_quiz = by_type["llm.quiz.completed"].event_data
        assert llm_quiz["provider"] == "dashscope_compatible"
        assert llm_quiz["model"]
        assert llm_quiz["latency_ms"] > 0
        assert llm_quiz["response_shape_valid"] is True

        embedding_query = by_type["embedding.query.completed"].event_data
        assert embedding_query["provider"] == "dashscope_compatible"
        assert embedding_query["model"]
        assert embedding_query["latency_ms"] >= 0
        assert embedding_query["response_shape_valid"] is True
    finally:
        await engine.dispose()
