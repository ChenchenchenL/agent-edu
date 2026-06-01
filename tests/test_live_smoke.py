from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from agent_core.api.app import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("AGENT_EDU_RUN_LIVE_SMOKE") != "1",
    reason="Live smoke tests are disabled unless AGENT_EDU_RUN_LIVE_SMOKE=1.",
)


def test_live_chat_and_quiz_smoke():
    client = TestClient(create_app())

    def post_json(path: str, payload: dict[str, object], *, retries: int = 1):
        last_response = None
        for attempt in range(retries + 1):
            response = client.post(path, json=payload)
            if response.status_code == 200:
                return response
            last_response = response
            if response.status_code != 503 or attempt >= retries:
                break
        assert last_response is not None
        return last_response

    seed_session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra Review", "subject": "Matrices"},
    )
    assert seed_session_response.status_code == 200
    seed_session_id = seed_session_response.json()["id"]

    seed_chat_response = post_json(
        f"/api/v1/sessions/{seed_session_id}/messages",
        {"content": "Explain matrix addition simply.", "mode": "chat"},
        retries=2,
    )
    assert seed_chat_response.status_code == 200

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    chat_response = post_json(
        f"/api/v1/sessions/{session_id}/messages",
        {"content": "Explain matrix multiplication simply.", "mode": "chat"},
        retries=2,
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["assistant_payload"]["type"] == "explanation"
    assert chat_payload["turn_metrics"]["cross_session_context_count"] >= 1

    quiz_response = post_json(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        {"topic": "Matrices", "difficulty": "easy", "question_count": 2},
        retries=2,
    )
    assert quiz_response.status_code == 200
    quiz_payload = quiz_response.json()
    assert quiz_payload["session_id"] == session_id
    assert len(quiz_payload["questions"]) == 2

    hint_response = post_json(
        f"/api/v1/sessions/{session_id}/messages",
        {
            "content": "I think my answer is wrong. Give me a hint instead.",
            "mode": "hint",
            "related_quiz_id": quiz_payload["quiz_id"],
            "question_prompt": quiz_payload["questions"][0]["prompt"],
            "learner_answer": "I think you multiply matching positions directly.",
        },
        retries=2,
    )
    assert hint_response.status_code == 200
    hint_payload = hint_response.json()
    assert hint_payload["assistant_payload"]["type"] == "hint"
    assert hint_payload["assistant_payload"]["direct_answer_given"] is False
    assert hint_payload["assistant_payload"]["hint_level"] in {"scaffolded", "targeted"}
    assert hint_payload["turn_metrics"]["history_count"] >= 2
    assert hint_payload["turn_metrics"]["memory_context_count"] >= 1
    assert hint_payload["turn_metrics"]["hint_level"] in {"scaffolded", "targeted"}
    assert hint_payload["turn_metrics"]["used_error_analysis"] is True

    list_response = client.get(f"/api/v1/sessions/{session_id}/quizzes")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert len(listed) >= 1

    detail_response = client.get(
        f"/api/v1/sessions/{session_id}/quizzes/{quiz_payload['quiz_id']}"
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["quiz_id"] == quiz_payload["quiz_id"]
