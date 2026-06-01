from __future__ import annotations

import os

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("AGENT_EDU_API_BASE_URL"),
    reason="External API blackbox tests require AGENT_EDU_API_BASE_URL.",
)


def test_external_mock_api_blackbox():
    base_url = os.environ["AGENT_EDU_API_BASE_URL"].rstrip("/")

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        def post_json(path: str, payload: dict[str, object], *, retries: int = 1) -> httpx.Response:
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

        chat_response = post_json(
            f"/api/v1/sessions/{session_id}/messages",
            {"content": "Explain matrix multiplication simply.", "mode": "chat"},
            retries=2,
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["assistant_payload"]["type"] == "explanation"

        quiz_response = post_json(
            f"/api/v1/sessions/{session_id}/quizzes/generate",
            {"topic": "Matrices", "difficulty": "easy", "question_count": 2},
            retries=2,
        )
        assert quiz_response.status_code == 200
        quiz_payload = quiz_response.json()
        assert len(quiz_payload["questions"]) == 2

        hint_response = post_json(
            f"/api/v1/sessions/{session_id}/messages",
            {
                "content": "I think my answer is wrong. Give me a hint.",
                "mode": "hint",
                "related_quiz_id": quiz_payload["quiz_id"],
                "question_prompt": quiz_payload["questions"][0]["prompt"],
                "learner_answer": "I multiplied matching positions directly.",
            },
            retries=2,
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
