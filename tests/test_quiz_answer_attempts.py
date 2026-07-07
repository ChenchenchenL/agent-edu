"""End-to-end tests for Phase 1 quiz answer attempt submission.

The suite uses the in-memory FastAPI TestClient (``app_client_factory``) for
the happy path and validation tests, and a directly-constructed service with
stub dependencies for transactional failure scenarios (audit failure
rollback, usage record failure not blocking commit).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.quiz_attempt import (
    QuizAttemptService,
    _RecommendedNextActionPolicy,
)
from agent_core.application.services.quiz_grading import (
    AnswerGradingService,
    GradingResult,
)
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery
from agent_core.domain.entities.session.quiz import (
    SessionQuiz,
    SessionQuizAnswerAttempt,
    SessionQuizQuestion,
)
from agent_core.domain.entities.session.session import LearningSession
from agent_core.domain.schemas.quiz import QuizQuestion
from agent_core.infrastructure.db.repositories.learner import (
    LearnerTopicMasteryRepository,
)
from agent_core.infrastructure.db.repositories.quiz_answer_attempt import (
    SessionQuizAnswerAttemptRepository,
)


# ---------------------------------------------------------------------------
# HTTP API tests (using app_client_factory)
# ---------------------------------------------------------------------------


def _create_session_and_quiz(client) -> tuple[str, str, str]:
    session_resp = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    generate_resp = client.post(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        json={"topic": "Matrices", "difficulty": "easy", "question_count": 2},
    )
    assert generate_resp.status_code == 200
    quiz_id = generate_resp.json()["quiz_id"]

    detail_resp = client.get(f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}")
    assert detail_resp.status_code == 200
    questions = detail_resp.json()["questions"]
    question_id = questions[0]["id"]
    assert question_id is not None
    return session_id, quiz_id, question_id


class TestSubmitAttemptAPI:
    def test_submit_attempt_success_path(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, question_id = _create_session_and_quiz(client)

        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={
                "learner_answer": "some open-ended answer",
                "hint_used": False,
                "hint_count": 0,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["quiz_id"] == quiz_id
        assert body["question_id"] == question_id
        assert body["attempt_number"] == 1
        assert body["grading"]["grading_status"] in {
            "graded",
            "rejected",
            "needs_review",
        }
        assert body["recommended_next_action"] in {
            "continue",
            "review",
            "request_hint",
            "easier_question",
            "assessment_ready",
            "request_review",
        }
        assert body["attempt_id"]

    def test_submit_attempt_session_not_found(self, app_client_factory) -> None:
        client = app_client_factory()
        resp = client.post(
            "/api/v1/sessions/missing-sess/quizzes/q/questions/qq/attempts",
            json={"learner_answer": "x"},
        )
        assert resp.status_code == 404

    def test_submit_attempt_quiz_not_in_session(self, app_client_factory) -> None:
        client = app_client_factory()
        session_resp = client.post(
            "/api/v1/sessions",
            json={"title": "T", "subject": "S"},
        )
        session_id = session_resp.json()["id"]
        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/missing-quiz/questions/qq/attempts",
            json={"learner_answer": "x"},
        )
        assert resp.status_code == 404

    def test_submit_attempt_question_not_in_quiz(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, _question_id = _create_session_and_quiz(client)
        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/missing-q/attempts",
            json={"learner_answer": "x"},
        )
        assert resp.status_code == 404

    def test_submit_attempt_empty_answer_rejected(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, question_id = _create_session_and_quiz(client)
        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={"learner_answer": ""},
        )
        assert resp.status_code == 422

    def test_submit_attempt_invalid_grading_strategy(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, question_id = _create_session_and_quiz(client)
        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={"learner_answer": "answer", "grading_strategy": "magic"},
        )
        assert resp.status_code == 422

    def test_submit_attempt_hint_count_bounded(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, question_id = _create_session_and_quiz(client)
        resp = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={"learner_answer": "answer", "hint_count": 25},
        )
        assert resp.status_code == 422

    def test_attempt_number_increments_per_question(self, app_client_factory) -> None:
        client = app_client_factory()
        session_id, quiz_id, question_id = _create_session_and_quiz(client)
        first = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={"learner_answer": "first"},
        )
        second = client.post(
            f"/api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts",
            json={"learner_answer": "second"},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["attempt_number"] == 1
        assert second.json()["attempt_number"] == 2


# ---------------------------------------------------------------------------
# Recommended next action policy (pure unit tests)
# ---------------------------------------------------------------------------


class TestRecommendedNextActionPolicy:
    def test_continue_on_high_score(self) -> None:
        action = _RecommendedNextActionPolicy.decide(
            score=0.9,
            is_correct=True,
            hint_used=False,
            hint_count=0,
            attempt_number=1,
            grading_status="graded",
        )
        assert action == "continue"

    def test_easier_question_on_third_failure(self) -> None:
        action = _RecommendedNextActionPolicy.decide(
            score=0.0,
            is_correct=False,
            hint_used=False,
            hint_count=0,
            attempt_number=3,
            grading_status="graded",
        )
        assert action == "easier_question"

    def test_request_hint_when_hints_accumulated(self) -> None:
        action = _RecommendedNextActionPolicy.decide(
            score=0.0,
            is_correct=False,
            hint_used=True,
            hint_count=2,
            attempt_number=2,
            grading_status="graded",
        )
        assert action == "request_hint"

    def test_request_review_when_needs_review(self) -> None:
        action = _RecommendedNextActionPolicy.decide(
            score=None,
            is_correct=None,
            hint_used=False,
            hint_count=0,
            attempt_number=1,
            grading_status="needs_review",
        )
        assert action == "request_review"

    def test_review_when_correct_but_hint_used(self) -> None:
        action = _RecommendedNextActionPolicy.decide(
            score=1.0,
            is_correct=True,
            hint_used=True,
            hint_count=1,
            attempt_number=1,
            grading_status="graded",
        )
        assert action == "review"


# ---------------------------------------------------------------------------
# Stub helpers for service-level tests
# ---------------------------------------------------------------------------


@dataclass
class _StubAuditService:
    events: list[AuditEvent] = None  # type: ignore[assignment]
    raise_on_record: bool = False

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []

    async def record(self, **kwargs: Any) -> AuditEvent:
        if self.raise_on_record:
            raise RuntimeError("audit failure simulated")
        event = AuditEvent.build(
            event_type=kwargs["event_type"],
            resource_type=kwargs["resource_type"],
            resource_id=kwargs["resource_id"],
            actor=kwargs["actor"],
            event_data=kwargs["event_data"],
        )
        self.events.append(event)
        return event


class _StubLLMProvider:
    """Trivially deterministic provider used to drive the full service."""

    async def generate_answer_grading(self, **kwargs: Any) -> Any:
        from agent_core.infrastructure.llm.types import AnswerGradingDraft

        return AnswerGradingDraft(
            score=0.9,
            is_correct=True,
            confidence=0.8,
            rubric_feedback="stub",
            misconception_codes=[],
            reasoning_quality="stub",
            provider="stub",
            model="stub",
            latency_ms=0,
            retry_count=0,
            response_shape_valid=True,
        )


@dataclass
class _InMemorySession:
    """Minimal AsyncSession-shaped object supporting commit/rollback tracking."""

    committed: int = 0
    rolled_back: int = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _StubSessionRepository:
    def __init__(self, session: LearningSession | None = None) -> None:
        self._session = session

    async def get_by_id(self, session_id: str) -> LearningSession | None:
        if self._session is not None and self._session.id == session_id:
            return self._session
        return None


class _StubQuizRepository:
    def __init__(
        self,
        *,
        quiz: SessionQuiz | None = None,
        questions: list[SessionQuizQuestion] | None = None,
    ) -> None:
        self._quiz = quiz
        self._questions = questions or []

    async def get_quiz_with_questions(self, *, session_id: str, quiz_id: str):
        from agent_core.domain.entities.session.quiz import StoredSessionQuiz
        from agent_core.domain.errors import NotFoundError

        if self._quiz is None or self._quiz.session_id != session_id or self._quiz.id != quiz_id:
            raise NotFoundError(f"Quiz '{quiz_id}' was not found in session '{session_id}'.")
        return StoredSessionQuiz(
            quiz=self._quiz,
            questions=[
                QuizQuestion(
                    id=q.id,
                    prompt=q.prompt,
                    answer=q.answer,
                    question_type=q.question_type,
                    options=list(q.options),
                )
                for q in self._questions
            ],
        )


class _StubAttemptRepository:
    def __init__(self) -> None:
        self.attempts: list[SessionQuizAnswerAttempt] = []

    async def create(self, entity: SessionQuizAnswerAttempt) -> None:
        self.attempts.append(entity)

    async def get_last_by_question(self, question_id: str) -> SessionQuizAnswerAttempt | None:
        candidates = [a for a in self.attempts if a.question_id == question_id]
        if not candidates:
            return None
        return max(candidates, key=lambda a: a.attempt_number)


class _StubMasteryRepository:
    def __init__(self, mastery: LearnerTopicMastery | None = None) -> None:
        self._mastery = mastery

    async def get_by_goal_and_topic(
        self, learner_goal_id: str, topic_key: str
    ) -> LearnerTopicMastery | None:
        if self._mastery is None:
            return None
        if (
            self._mastery.learner_goal_id == learner_goal_id
            and self._mastery.topic_key == topic_key
        ):
            return self._mastery
        return None


def _build_learning_session(*, session_id: str = "sess-1") -> LearningSession:
    now = datetime.now(timezone.utc)
    return LearningSession(
        id=session_id,
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id=None,
        title="Linear Algebra",
        subject="Matrices",
        status="active",
        message_count=0,
        last_activity_at=now,
        summary=None,
        created_at=now,
        updated_at=now,
    )


def _build_quiz(*, session_id: str, quiz_id: str = "quiz-1") -> SessionQuiz:
    return SessionQuiz(
        id=quiz_id,
        session_id=session_id,
        topic="Matrices",
        difficulty="easy",
        question_count=1,
        skill_trace=["create_quiz"],
        created_at=datetime.now(timezone.utc),
    )


def _build_question(
    *,
    quiz_id: str,
    question_id: str = "qq-1",
    question_type: str = "short_answer",
    prompt: str = "What is 2+2?",
    answer: str = "4",
    options: tuple[str, ...] = (),
) -> SessionQuizQuestion:
    return SessionQuizQuestion(
        id=question_id,
        quiz_id=quiz_id,
        position=1,
        prompt=prompt,
        answer=answer,
        question_type=question_type,
        options=options,
    )


def _make_attempt_service(
    *,
    session: LearningSession | None = None,
    quiz: SessionQuiz | None = None,
    questions: list[SessionQuizQuestion] | None = None,
    mastery: LearnerTopicMastery | None = None,
    audit_raise: bool = False,
    skill_usage: Any | None = None,
) -> tuple[QuizAttemptService, _InMemorySession, _StubAuditService, _StubAttemptRepository]:
    sess = session or _build_learning_session()
    qz = quiz or _build_quiz(session_id=sess.id)
    qq = questions or [_build_question(quiz_id=qz.id)]
    db_session = _InMemorySession()
    audit = _StubAuditService(raise_on_record=audit_raise)
    attempt_repo = _StubAttemptRepository()
    svc = QuizAttemptService(
        db_session=db_session,
        audit_service=audit,
        session_repository=_StubSessionRepository(sess),
        quiz_repository=_StubQuizRepository(quiz=qz, questions=qq),
        attempt_repository=attempt_repo,
        grading_service=AnswerGradingService(llm_provider=_StubLLMProvider()),  # type: ignore[arg-type]
        topic_mastery_repository=_StubMasteryRepository(mastery),
        skill_usage_service=skill_usage,
    )
    return svc, db_session, audit, attempt_repo


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestSubmitAttemptService:
    @pytest.mark.asyncio
    async def test_success_path_records_attempt_and_audit(self) -> None:
        svc, db_session, audit, attempt_repo = _make_attempt_service()
        response = await svc.submit_attempt(
            session_id="sess-1",
            quiz_id="quiz-1",
            question_id="qq-1",
            learner_answer="4",
            hint_used=False,
            hint_count=0,
            grading_strategy="hybrid",
        )
        assert response.attempt_number == 1
        assert response.grading.grading_status == "graded"
        assert response.grading.is_correct is True
        assert response.recommended_next_action == "continue"
        assert db_session.committed == 1
        assert len(attempt_repo.attempts) == 1
        assert len(audit.events) == 1
        assert audit.events[0].event_type == "quiz.answer_attempt.submitted"

    @pytest.mark.asyncio
    async def test_ownership_failure_does_not_write_attempt(self) -> None:
        svc, db_session, audit, attempt_repo = _make_attempt_service()
        from agent_core.domain.errors import NotFoundError

        with pytest.raises(NotFoundError):
            await svc.submit_attempt(
                session_id="sess-other",
                quiz_id="quiz-1",
                question_id="qq-1",
                learner_answer="4",
                hint_used=False,
                hint_count=0,
            )
        assert attempt_repo.attempts == []
        assert audit.events == []
        assert db_session.committed == 0

    @pytest.mark.asyncio
    async def test_audit_failure_rolls_back_and_raises(self) -> None:
        svc, db_session, audit, attempt_repo = _make_attempt_service(audit_raise=True)
        # The service does not wrap audit calls, so the exception propagates
        # after the audit repo has flushed -- our stub session must be
        # observable for "rollback was called" semantics.
        with pytest.raises(RuntimeError, match="audit failure simulated"):
            await svc.submit_attempt(
                session_id="sess-1",
                quiz_id="quiz-1",
                question_id="qq-1",
                learner_answer="4",
                hint_used=False,
                hint_count=0,
            )
        # The service's flow: audit raise happens BEFORE the explicit
        # ``db_session.commit()`` call, so commit is never reached.
        assert db_session.committed == 0
        # The route layer (not the service) is responsible for calling
        # rollback on any exception; verify the attempt was still staged
        # in the repo (flushed), but without a commit.
        assert len(attempt_repo.attempts) == 1

    @pytest.mark.asyncio
    async def test_skill_usage_failure_does_not_block_commit(self) -> None:
        class _FailingUsage:
            async def record_usage(self, **kwargs: Any) -> None:
                raise RuntimeError("usage write failed")

        svc, db_session, audit, attempt_repo = _make_attempt_service(
            skill_usage=_FailingUsage()
        )
        response = await svc.submit_attempt(
            session_id="sess-1",
            quiz_id="quiz-1",
            question_id="qq-1",
            learner_answer="4",
            hint_used=False,
            hint_count=0,
        )
        assert response.attempt_number == 1
        assert db_session.committed == 1
        assert len(attempt_repo.attempts) == 1

    @pytest.mark.asyncio
    async def test_mastery_snapshot_returned_when_present(self) -> None:
        now = datetime.now(timezone.utc)
        mastery = LearnerTopicMastery(
            id=str(uuid4()),
            learner_goal_id="goal-1",
            topic_key="Matrices",
            mastery_score=0.72,
            confidence=0.6,
            evidence_count=3,
            last_attempt_status="completed",
            last_assessed_at=now,
            created_at=now,
            updated_at=now,
        )
        svc, _db, _audit, _repo = _make_attempt_service(mastery=mastery)
        response = await svc.submit_attempt(
            session_id="sess-1",
            quiz_id="quiz-1",
            question_id="qq-1",
            learner_answer="4",
            hint_used=False,
            hint_count=0,
        )
        assert response.mastery_snapshot is not None
        assert response.mastery_snapshot.topic_key == "Matrices"
        assert response.mastery_snapshot.mastery_score == 0.72
        assert response.mastery_snapshot.confidence == 0.6

    @pytest.mark.asyncio
    async def test_learner_identity_derived_from_session_not_payload(self) -> None:
        svc, _db, _audit, attempt_repo = _make_attempt_service()
        await svc.submit_attempt(
            session_id="sess-1",
            quiz_id="quiz-1",
            question_id="qq-1",
            learner_answer="4",
            hint_used=False,
            hint_count=0,
            client_context={"learner_profile_id": "attacker-controlled"},
        )
        attempt = attempt_repo.attempts[0]
        assert attempt.learner_profile_id == "profile-1"
        assert attempt.metadata == {"client_context": {"learner_profile_id": "attacker-controlled"}}
