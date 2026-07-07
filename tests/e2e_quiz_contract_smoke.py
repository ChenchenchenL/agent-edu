"""End-to-end contract smoke test.

Runs against a live API (http://localhost:8000 by default) and verifies the
full chain: create session → generate quiz → submit answer attempt → validate
the AnswerAttemptResponse shape (grading / mastery_snapshot / recommended_next_action).

Usage:
    python tests/e2e_quiz_contract_smoke.py
    API_BASE_URL=http://... python tests/e2e_quiz_contract_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import urllib.request
import urllib.error

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_SECONDS = 120


def _request(method: str, path: str, body: dict | None = None) -> tuple[int, Any]:
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as res:
            return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode() if exc.fp else ""
        print(f"HTTPError {exc.code} for {method} {path}: {body_text}", file=sys.stderr)
        raise


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def main() -> int:
    print("== E2E quiz contract smoke ==")
    print(f"API_BASE={API_BASE}")

    # 1. Health
    status, _ = _request("GET", "/healthz")
    _assert(status == 200, f"GET /healthz → {status}")

    # 2. Create session
    status, session = _request(
        "POST",
        "/api/v1/sessions",
        {"title": "E2E Smoke", "subject": "LinearAlgebra"},
    )
    _assert(status == 200, f"POST /sessions → {status}")
    session_id = session["id"]
    _assert(isinstance(session_id, str) and session_id, "session has id")
    _assert(session["subject"] == "LinearAlgebra", "session.subject preserved")

    # 3. Generate quiz
    status, quiz = _request(
        "POST",
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        {"topic": "LinearAlgebra", "difficulty": "easy", "question_count": 2},
    )
    _assert(status == 200, f"POST /quizzes/generate → {status}")
    quiz_id = quiz["quiz_id"]
    _assert(isinstance(quiz_id, str) and quiz_id, "quiz has quiz_id")
    _assert(len(quiz["questions"]) == 2, "quiz has 2 questions")

    # 3b. Fetch persisted quiz detail (generate response omits question IDs)
    status, quiz_detail = _request(
        "GET",
        f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}",
    )
    _assert(status == 200, f"GET /quizzes/{{id}} → {status}")
    _assert(len(quiz_detail["questions"]) == 2, "detail has 2 questions")
    first_question = quiz_detail["questions"][0]
    _assert("prompt" in first_question and "answer" in first_question, "question has prompt/answer")
    question_id = first_question.get("id")
    _assert(isinstance(question_id, str) and bool(question_id), "question has id (required for attempt API)")

    # 4. Submit answer attempt
    status, attempt = _request(
        "POST",
        f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
        {
            "learner_answer": "some answer for smoke test",
            "hint_used": False,
            "hint_count": 0,
            "grading_strategy": "hybrid",
        },
    )
    _assert(status == 201, f"POST /attempts → {status}")

    # 5. Validate AnswerAttemptResponse shape
    _assert(isinstance(attempt.get("attempt_id"), str), "attempt.attempt_id present")
    _assert(attempt["session_id"] == session_id, "attempt.session_id matches")
    _assert(attempt["quiz_id"] == quiz_id, "attempt.quiz_id matches")
    _assert(attempt["question_id"] == question_id, "attempt.question_id matches")
    _assert(isinstance(attempt.get("attempt_number"), int) and attempt["attempt_number"] >= 1, "attempt.attempt_number >= 1")
    _assert(isinstance(attempt.get("created_at"), str), "attempt.created_at present")

    # Grading block
    grading = attempt.get("grading") or {}
    _assert(grading.get("grading_status") in {"graded", "needs_review", "rejected"}, "grading.grading_status in enum")
    _assert("score" in grading, "grading.score present (may be null)")
    _assert("is_correct" in grading, "grading.is_correct present (may be null)")
    _assert("misconception_codes" in grading and isinstance(grading["misconception_codes"], list), "grading.misconception_codes is list")
    _assert("needs_human_review" in grading, "grading.needs_human_review present")

    # Mastery snapshot (may be null for first attempt)
    snapshot = attempt.get("mastery_snapshot")
    if snapshot is not None:
        _assert("topic_key" in snapshot, "mastery_snapshot.topic_key present")
        _assert(isinstance(snapshot.get("mastery_score"), (int, float)), "mastery_snapshot.mastery_score is number")
        _assert(isinstance(snapshot.get("confidence"), (int, float)), "mastery_snapshot.confidence is number")
        _assert(isinstance(snapshot.get("evidence_count"), int), "mastery_snapshot.evidence_count is int")

    # Recommended next action
    action = attempt.get("recommended_next_action")
    _assert(isinstance(action, str) and bool(action), f"recommended_next_action present (got {action!r})")
    allowed_actions = {
        "continue", "review", "request_review", "request_hint",
        "easier_question", "assessment_ready", "generate_quiz", "review_scheduling",
    }
    _assert(action in allowed_actions, f"recommended_next_action in allowed set (got {action!r})")

    # 6. Submit a second attempt → attempt_number increments
    status, attempt2 = _request(
        "POST",
        f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
        {"learner_answer": "second answer", "grading_strategy": "hybrid"},
    )
    _assert(status == 201, "second POST /attempts → 201")
    _assert(attempt2["attempt_number"] == attempt["attempt_number"] + 1, "attempt_number increments per question")

    print()
    print("== All E2E contract checks passed ==")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"API unreachable at {API_BASE}: {exc}", file=sys.stderr)
        sys.exit(2)
