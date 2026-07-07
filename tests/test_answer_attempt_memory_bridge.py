import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass

from agent_core.application.services.long_term_memory_materialization import (
    LongTermMemoryMaterializationService,
    LongTermMemoryMaterializationResult,
)
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryMaterializationReplayExecutor,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.quiz_attempt import QuizAttemptService
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt, SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.memory import KnowledgeMemory, BehaviorMemory, MemoryEvidenceLink
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt, ScheduledAutonomyJob
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.audit import AuditEvent
from agent_core.application.services.quiz_grading import GradingResult, AnswerGradingService
from agent_core.domain.schemas.quiz import QuizQuestion


class StubKnowledgeMemoryRepository:
    def __init__(self):
        self.memories = []

    async def create(self, entity):
        self.memories.append(entity)
        return None

    async def get_by_id(self, memory_id: str):
        for m in self.memories:
            if m.id == memory_id:
                return m
        return None

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        knowledge_key: str,
        semantic_category: str,
        statuses: set[str] | None = None,
    ):
        for item in reversed(self.memories):
            if (
                item.learner_profile_id == learner_profile_id
                and item.learner_goal_id == learner_goal_id
                and item.knowledge_key == knowledge_key
                and item.semantic_category == semantic_category
                and (statuses is None or item.status in statuses)
            ):
                return item
        return None


class StubBehaviorMemoryRepository:
    def __init__(self):
        self.memories = []

    async def create(self, entity):
        self.memories.append(entity)
        return None

    async def get_by_id(self, memory_id: str):
        for m in self.memories:
            if m.id == memory_id:
                return m
        return None

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        statuses: set[str] | None = None,
    ):
        for item in reversed(self.memories):
            if (
                item.learner_profile_id == learner_profile_id
                and item.learner_goal_id == learner_goal_id
                and item.behavior_key == behavior_key
                and item.behavior_category == behavior_category
                and (statuses is None or item.status in statuses)
            ):
                return item
        return None


class StubMemoryEvidenceLinkRepository:
    def __init__(self):
        self.records = {}

    async def upsert(self, entity: MemoryEvidenceLink):
        key = (
            entity.memory_type,
            entity.memory_id,
            entity.evidence_source_type,
            entity.evidence_source_id,
            entity.evidence_role,
        )
        self.records[key] = entity


class StubMemoryRepository:
    def __init__(self):
        self.events = []

    async def create(self, entity):
        self.events.append(entity)


class DummyMemoryService(MemoryService):
    def __init__(
        self,
        knowledge_memory_repository,
        behavior_memory_repository,
        evidence_link_repository,
    ):
        super().__init__(
            StubMemoryRepository(),
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            evidence_link_repository=evidence_link_repository,
        )


class StubAutonomyJobService:
    def __init__(self):
        self.jobs = []

    async def create_job(self, **kwargs):
        job = ScheduledAutonomyJob.build(
            learner_goal_id=kwargs.get("learner_goal_id"),
            job_type=kwargs.get("job_type"),
            trigger_source=kwargs.get("trigger_source"),
            due_at=kwargs.get("due_at"),
            idempotency_key=kwargs.get("idempotency_key"),
            payload=kwargs.get("payload"),
        )
        self.jobs.append(job)
        return job
        

class StubSessionRepository:
    def __init__(self, session):
        self.session = session

    async def get_by_id(self, session_id):
        return self.session if self.session.id == session_id else None


class StubQuizRepository:
    def __init__(self, quiz, questions):
        self.quiz = quiz
        self.questions = questions

    async def get_quiz_with_questions(self, session_id, quiz_id):
        return StoredQuizWrapper(self.quiz, self.questions)


class StoredQuizWrapper:
    def __init__(self, quiz, questions):
        self.quiz = quiz
        self.questions = [
            QuizQuestion(
                id=q.id,
                prompt=q.prompt,
                answer=q.answer,
                question_type="mcq",
                options=[],
            )
            for q in questions
        ]


class StubAttemptRepository:
    def __init__(self) -> None:
        self.attempts = []

    async def create(self, entity):
        self.attempts.append(entity)

    async def get_last_by_question(self, question_id):
        return None

    async def get_by_id(self, attempt_id):
        for a in self.attempts:
            if a.id == attempt_id:
                return a
        return None


class StubAnswerGradingService:
    async def grade(self, **kwargs):
        return GradingResult(
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="Wrong alignment",
            misconception_codes=("matrix_alignment_error",),
            reasoning_quality=1.0,
            needs_human_review=False,
            grading_status="graded",
            grading_source="hybrid",
            validation_error=None,
        )


class StubMasteryRepository:
    async def get_by_goal_and_topic(self, learner_goal_id, topic_key):
        return None


class StubAuditService:
    def __init__(self):
        self.durable_events = []
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs)

    async def record_durable(self, **kwargs):
        self.durable_events.append(kwargs)


class FailingMaterializationService:
    async def materialize_from_answer_attempt(self, **kwargs):
        raise RuntimeError("Failed to materialize memory candidate from quiz attempt.")


@dataclass
class _InMemorySession:
    committed: int = 0
    rolled_back: int = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def begin_nested(self):
        return self


class TestAnswerAttemptMemoryBridge:
    @pytest.mark.asyncio
    async def test_answer_attempt_creates_candidate_only(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-123",
            quiz_id="quiz-456",
            question_id="question-789",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Matrix Multiplication",
            subskill_keys=[],
            question_prompt="Solve the matrix multiplication",
            reference_answer="[[2]]",
            learner_answer="[[3]]",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="Incorrect result",
            misconception_codes=[],
            hint_used=True,
            hint_count=1,
            attempt_number=1,
        )

        result = await materialization_service.materialize_from_answer_attempt(attempt=attempt)

        assert len(result.knowledge) == 1
        assert len(result.behavior) == 1
        assert result.knowledge[0].action == "created"
        assert result.behavior[0].action == "created"
        
        # Verify status defaults to candidate
        assert knowledge_repo.memories[0].status == "candidate"
        assert behavior_repo.memories[0].status == "candidate"

    @pytest.mark.asyncio
    async def test_suppressed_memory_not_automatically_restored(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-123",
            quiz_id="quiz-456",
            question_id="question-789",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Matrix Multiplication",
            subskill_keys=[],
            question_prompt="Solve the matrix multiplication",
            reference_answer="[[2]]",
            learner_answer="[[3]]",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="Incorrect result",
            misconception_codes=[],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        # Pre-seed a suppressed memory for the topic key
        suppressed_mem = KnowledgeMemory.build(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            knowledge_key="matrix-multiplication",
            title="Struggle with Matrix Multiplication",
            summary="Learner struggles.",
            details="Some details.",
            knowledge_level="core",
            time_horizon="mid",
            importance_score=0.5,
            confidence_score=0.5,
            freshness_score=1.0,
            prerequisite_keys=[],
            source_event_ids=[],
            source_memory_ids=[],
            tags=[],
        )
        # Manually set to suppressed
        suppressed_mem = suppressed_mem.with_status("suppressed", suppressed_reason_code="operator_block")
        await knowledge_repo.create(suppressed_mem)

        result = await materialization_service.materialize_from_answer_attempt(attempt=attempt)

        assert len(result.knowledge) == 1
        assert result.knowledge[0].action == "skipped_suppressed"
        assert knowledge_repo.memories[0].status == "suppressed"

    @pytest.mark.asyncio
    async def test_evidence_link_provenance_points_to_attempt_id(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-123",
            quiz_id="quiz-456",
            question_id="question-789",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Matrix Multiplication",
            subskill_keys=[],
            question_prompt="Solve the matrix multiplication",
            reference_answer="[[2]]",
            learner_answer="[[3]]",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="Incorrect result",
            misconception_codes=["code_1"],
            hint_used=True,
            hint_count=2,
            attempt_number=1,
        )

        result = await materialization_service.materialize_from_answer_attempt(attempt=attempt)

        # Get evidence links from records
        assert len(evidence_repo.records) == 2
        for link in evidence_repo.records.values():
            assert link.evidence_source_type == "quiz_answer_attempt"
            assert link.evidence_source_id == attempt.id
            assert link.payload["score"] == 0.0
            assert link.payload["difficulty"] == "medium"
            assert link.payload["misconception_codes"] == ["code_1"]
            assert link.payload["hint_count"] == 2
            assert link.payload["question_id"] == "question-789"

    @pytest.mark.asyncio
    async def test_materialization_failure_schedules_replay_and_durable_audit(self) -> None:
        db_session = _InMemorySession()
        audit_service = StubAuditService()
        job_service = StubAutonomyJobService()
        replay_scheduler = LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=job_service
        )

        session = LearningSession.build(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            title="Math",
            subject="Algebra",
        )
        quiz = SessionQuiz.build(
            session_id=session.id,
            topic="Algebra",
            difficulty="easy",
            question_count=1,
            skill_trace=["explain_concept"],
        )
        question = SessionQuizQuestion.build(
            quiz_id=quiz.id,
            position=0,
            question_type="mcq",
            prompt="Is 1+1=2?",
            answer="yes",
            options=["yes", "no"],
        )

        svc = QuizAttemptService(
            db_session=db_session,
            audit_service=audit_service,
            session_repository=StubSessionRepository(session),
            quiz_repository=StubQuizRepository(quiz, [question]),
            attempt_repository=StubAttemptRepository(),
            grading_service=StubAnswerGradingService(),
            topic_mastery_repository=StubMasteryRepository(),
            materialization_service=FailingMaterializationService(),
            long_term_memory_replay_scheduler=replay_scheduler,
        )

        response = await svc.submit_attempt(
            session_id=session.id,
            quiz_id=quiz.id,
            question_id=question.id,
            learner_answer="no",
            hint_used=False,
            hint_count=0,
        )

        assert response is not None
        # Verify job scheduled and audit recorded
        assert len(job_service.jobs) == 1
        assert job_service.jobs[0].job_type == "long_term_memory_materialization_replay"
        assert job_service.jobs[0].payload["source_type"] == "quiz_answer_attempt"
        assert job_service.jobs[0].payload["attempt_id"] == response.attempt_id

        assert len(audit_service.durable_events) == 1
        durable_event = audit_service.durable_events[0]
        assert durable_event["event_type"] == "long_term_memory.materialization.failed"
        assert durable_event["event_data"]["replay_enqueued"] is True
        assert durable_event["event_data"]["replay_job_id"] == job_service.jobs[0].id

    @pytest.mark.asyncio
    async def test_replay_executor_quiz_answer_attempt(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-123",
            quiz_id="quiz-456",
            question_id="question-789",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Matrix Multiplication",
            subskill_keys=[],
            question_prompt="Solve the matrix multiplication",
            reference_answer="[[2]]",
            learner_answer="[[3]]",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="Incorrect result",
            misconception_codes=[],
            hint_used=True,
            hint_count=1,
            attempt_number=1,
        )
        attempt_repo = StubAttemptRepository()
        await attempt_repo.create(attempt)

        executor = LongTermMemoryMaterializationReplayExecutor(
            session_repository=StubSessionRepository(None),
            message_repository=None,
            memory_event_repository=None,
            goal_repository=None,
            daily_task_repository=None,
            task_attempt_repository=None,
            reflection_record_repository=None,
            reflection_outcome_evaluation_repository=None,
            materialization_service=materialization_service,
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        job = ScheduledAutonomyJob.build(
            learner_goal_id="goal-1",
            job_type="long_term_memory_materialization_replay",
            trigger_source="long_term_memory_materialization_failed",
            due_at=datetime.now(timezone.utc),
            idempotency_key="ltm-replay:quiz_answer_attempt:1",
            payload={
                "source_type": "quiz_answer_attempt",
                "attempt_id": attempt.id,
            },
        )

        await executor.replay(job)

        # Verify that memory candidates were materialized
        assert len(knowledge_repo.memories) == 1
        assert len(behavior_repo.memories) == 1
        assert knowledge_repo.memories[0].status == "candidate"

    @pytest.mark.asyncio
    async def test_correct_answer_generates_knowledge_and_positive_behavior(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-123",
            quiz_id="quiz-456",
            question_id="question-789",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Algebra",
            subskill_keys=[],
            question_prompt="Solve 2x=4",
            reference_answer="x=2",
            learner_answer="x=2",
            grading_status="graded",
            grading_source="deterministic",
            score=1.0,
            is_correct=True,
            confidence=0.95,
            rubric_feedback="Correct",
            misconception_codes=[],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        result = await materialization_service.materialize_from_answer_attempt(attempt=attempt)

        assert len(result.knowledge) == 1
        assert result.knowledge[0].action == "created"
        knowledge_mem = knowledge_repo.memories[0]
        assert "success" in knowledge_mem.tags
        assert knowledge_mem.provenance_type == "quiz_answer_attempt"
        assert "Mastery of" in knowledge_mem.title

        assert len(result.behavior) == 1
        assert result.behavior[0].action == "created"
        behavior_mem = behavior_repo.memories[0]
        assert "success_pattern" in behavior_mem.tags
        assert "positive" in behavior_mem.tags
        assert behavior_mem.behavior_category == "guided_progress"
        assert behavior_mem.freshness_score == 0.4

        for link in evidence_repo.records.values():
            assert link.evidence_role == "supporting"

    @pytest.mark.asyncio
    async def test_evidence_weight_scales_with_confidence(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        high_conf_attempt = SessionQuizAnswerAttempt.build(
            session_id="session-1",
            quiz_id="quiz-1",
            question_id="q-1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Algebra",
            subskill_keys=[],
            question_prompt="Solve 2x=4",
            reference_answer="x=2",
            learner_answer="wrong",
            grading_status="graded",
            grading_source="deterministic",
            score=0.0,
            is_correct=False,
            confidence=0.95,
            rubric_feedback=None,
            misconception_codes=[],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        await materialization_service.materialize_from_answer_attempt(attempt=high_conf_attempt)

        high_conf_links = list(evidence_repo.records.values())
        assert len(high_conf_links) >= 1
        high_conf_weight = high_conf_links[0].weight
        assert high_conf_weight > 0.5

    @pytest.mark.asyncio
    async def test_evidence_weight_lower_for_needs_review(self) -> None:
        knowledge_repo = StubKnowledgeMemoryRepository()
        behavior_repo = StubBehaviorMemoryRepository()
        evidence_repo = StubMemoryEvidenceLinkRepository()
        memory_service = DummyMemoryService(
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
            evidence_link_repository=evidence_repo,
        )

        materialization_service = LongTermMemoryMaterializationService(
            memory_service=memory_service
        )

        needs_review_attempt = SessionQuizAnswerAttempt.build(
            session_id="session-1",
            quiz_id="quiz-1",
            question_id="q-1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Algebra",
            subskill_keys=[],
            question_prompt="Explain calculus",
            reference_answer="derivatives",
            learner_answer="some answer",
            grading_status="needs_review",
            grading_source="llm",
            score=None,
            is_correct=None,
            confidence=None,
            rubric_feedback=None,
            misconception_codes=[],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        await materialization_service.materialize_from_answer_attempt(attempt=needs_review_attempt)

        review_links = list(evidence_repo.records.values())
        assert len(review_links) >= 1
        assert review_links[0].weight < 0.5

    @pytest.mark.asyncio
    async def test_replay_with_missing_attempt_raises_validation_error(self) -> None:
        empty_attempt_repo = StubAttemptRepository()

        executor = LongTermMemoryMaterializationReplayExecutor(
            session_repository=StubSessionRepository(None),
            message_repository=None,
            memory_event_repository=None,
            goal_repository=None,
            daily_task_repository=None,
            task_attempt_repository=None,
            reflection_record_repository=None,
            reflection_outcome_evaluation_repository=None,
            materialization_service=LongTermMemoryMaterializationService(
                memory_service=DummyMemoryService(
                    knowledge_memory_repository=StubKnowledgeMemoryRepository(),
                    behavior_memory_repository=StubBehaviorMemoryRepository(),
                    evidence_link_repository=StubMemoryEvidenceLinkRepository(),
                )
            ),
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=empty_attempt_repo,
        )

        job = ScheduledAutonomyJob.build(
            learner_goal_id="goal-1",
            job_type="long_term_memory_materialization_replay",
            trigger_source="long_term_memory_materialization_failed",
            due_at=datetime.now(timezone.utc),
            idempotency_key="ltm-replay:quiz_answer_attempt:missing-id",
            payload={
                "source_type": "quiz_answer_attempt",
                "attempt_id": "nonexistent-attempt-id",
            },
        )

        with pytest.raises(Exception):
            await executor.replay(job)

    @pytest.mark.asyncio
    async def test_replay_with_goal_mismatch_raises_validation_error(self) -> None:
        attempt = SessionQuizAnswerAttempt.build(
            session_id="session-1",
            quiz_id="quiz-1",
            question_id="q-1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            daily_task_id=None,
            topic_key="Algebra",
            subskill_keys=[],
            question_prompt="Solve",
            reference_answer="answer",
            learner_answer="answer",
            grading_status="graded",
            grading_source="deterministic",
            score=1.0,
            is_correct=True,
            confidence=0.9,
            rubric_feedback=None,
            misconception_codes=[],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )
        attempt_repo = StubAttemptRepository()
        await attempt_repo.create(attempt)

        executor = LongTermMemoryMaterializationReplayExecutor(
            session_repository=StubSessionRepository(None),
            message_repository=None,
            memory_event_repository=None,
            goal_repository=None,
            daily_task_repository=None,
            task_attempt_repository=None,
            reflection_record_repository=None,
            reflection_outcome_evaluation_repository=None,
            materialization_service=LongTermMemoryMaterializationService(
                memory_service=DummyMemoryService(
                    knowledge_memory_repository=StubKnowledgeMemoryRepository(),
                    behavior_memory_repository=StubBehaviorMemoryRepository(),
                    evidence_link_repository=StubMemoryEvidenceLinkRepository(),
                )
            ),
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        job = ScheduledAutonomyJob.build(
            learner_goal_id="different-goal-id",
            job_type="long_term_memory_materialization_replay",
            trigger_source="long_term_memory_materialization_failed",
            due_at=datetime.now(timezone.utc),
            idempotency_key="ltm-replay:quiz_answer_attempt:mismatch",
            payload={
                "source_type": "quiz_answer_attempt",
                "attempt_id": attempt.id,
            },
        )

        with pytest.raises(Exception):
            await executor.replay(job)
