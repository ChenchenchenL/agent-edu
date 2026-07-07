"""MVP Docker blackbox smoke test.

HTTP-only verification of the MVP main path against a running API container.
Complements `test_mvp_acceptance.py` (which uses the in-process FastAPI test
client and direct DB access). This test:

- Does not import any backend module.
- Does not connect to the database directly.
- Only asserts on HTTP status codes and response shapes.
- Skips automatically when `AGENT_EDU_API_BASE_URL` is not set.

The chain mirrors the in-process acceptance test but exercises the real
network, serialization, and container boundaries.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import httpx
import pytest


pytestmark = pytest.mark.skipif(
    not os.getenv("AGENT_EDU_API_BASE_URL"),
    reason="MVP blackbox requires AGENT_EDU_API_BASE_URL.",
)


def _client() -> httpx.Client:
    base = os.environ["AGENT_EDU_API_BASE_URL"].rstrip("/")
    # Bypass env proxy: the blackbox talks to the API on the Docker network,
    # not to an external service. trust_env=False stops httpx from picking up
    # HTTP_PROXY / http_proxy and routing Docker-internal traffic through it.
    return httpx.Client(
        base_url=base,
        timeout=60.0,
        trust_env=False,
    )


def _learner_headers(access_key: str) -> dict[str, str]:
    return {"X-Learner-Key": access_key}


def _post_retry(client: httpx.Client, path: str, payload: dict, *, retries: int = 2) -> httpx.Response:
    """POST with bounded retry on 503 (API still starting up)."""
    last: httpx.Response | None = None
    for attempt in range(retries + 1):
        response = client.post(path, json=payload)
        if response.status_code != 503 or attempt >= retries:
            return response
        last = response
    assert last is not None
    return last


def test_mvp_blackbox_main_path() -> None:
    deadline = (date.today() + timedelta(days=21)).isoformat()

    with _client() as client:
        # 1. Health + readiness.
        health = client.get("/healthz")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"

        # 2. Create learner profile.
        profile = _post_retry(client, "/api/v1/learner-profiles", {})
        assert profile.status_code == 200, profile.text
        profile_payload = profile.json()
        profile_id = profile_payload["id"]
        access_key = profile_payload["access_key"]
        headers = _learner_headers(access_key)

        # 3. Create learner goal.
        goal = client.post(
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
        assert goal.status_code == 200, goal.text
        goal_id = goal.json()["id"]

        # 4. Generate study plan.
        plan = client.post(
            f"/api/v1/goals/{goal_id}/plans",
            headers=headers,
            json={"trigger_source": "initial"},
        )
        assert plan.status_code == 200, plan.text
        plan_payload = plan.json()
        assert plan_payload["version"] == 1
        assert len(plan_payload["stages"]) >= 2

        # 5. List daily tasks.
        tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
        assert tasks.status_code == 200
        task_payloads = tasks.json()
        assert len(task_payloads) >= 1

        # 6. Create session.
        session = client.post(
            "/api/v1/sessions",
            json={
                "title": "Matrix basics",
                "subject": "Linear Algebra",
                "learner_profile_id": profile_id,
                "learner_goal_id": goal_id,
            },
        )
        assert session.status_code == 200
        session_id = session.json()["id"]

        # 7. Chat explanation.
        chat = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
        )
        assert chat.status_code == 200, chat.text
        chat_payload = chat.json()
        assert chat_payload["assistant_payload"]["type"] == "explanation"

        # 8. Hint.
        hint = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "Give me a hint on matrix multiplication.", "mode": "hint"},
        )
        assert hint.status_code == 200
        assert hint.json()["assistant_payload"]["type"] == "hint"

        # 9. Quiz generation.
        quiz = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/generate",
            json={"topic": "Matrix multiplication", "difficulty": "easy", "question_count": 2},
        )
        assert quiz.status_code == 200, quiz.text
        quiz_payload = quiz.json()
        assert quiz_payload["question_count"] == 2
        quiz_id = quiz_payload["quiz_id"]

        # 10. Fetch quiz detail to get persisted question id.
        detail = client.get(f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}")
        assert detail.status_code == 200
        question_id = detail.json()["questions"][0]["id"]
        assert question_id

        # 11. Submit answer attempt.
        attempt = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={
                "learner_answer": "rows of left matrix dotted with columns of right matrix",
                "hint_used": False,
                "hint_count": 0,
                "grading_strategy": "hybrid",
            },
        )
        assert attempt.status_code == 201, attempt.text
        attempt_payload = attempt.json()
        assert attempt_payload["question_id"] == question_id
        assert attempt_payload["grading"]["grading_status"] in {
            "graded",
            "needs_review",
            "rejected",
        }
        assert isinstance(attempt_payload["recommended_next_action"], str)

        # 12. Memory retrieval API returns stable shape (may be empty).
        knowledge = client.get(
            "/api/v1/memory/knowledge",
            headers=headers,
            params={"learner_profile_id": profile_id, "query_text": "matrix"},
        )
        assert knowledge.status_code == 200
        assert "items" in knowledge.json()

        # 13. Operator endpoints require a configured operator key. If the
        # deployment has one, verify the observability surface; otherwise
        # assert the expected 403 so we know the guard is in place.
        operator_key = os.environ.get("AGENT_EDU_OPERATOR_API_KEY")
        if operator_key:
            op_headers = {"X-Operator-Key": operator_key}
            browse = client.get(
                "/api/v1/operator/quizzes/attempts",
                headers=op_headers,
                params={"limit": 10, "offset": 0},
            )
            assert browse.status_code == 200
            assert browse.json()["total_count"] >= 1
        else:
            browse = client.get("/api/v1/operator/quizzes/attempts", params={"limit": 10})
            assert browse.status_code in {401, 403}
