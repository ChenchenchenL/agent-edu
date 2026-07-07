import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field as dataclass_field

from agent_core.application.services.reflection import ReflectionService, ReflectionTriggerRequest
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_trigger_policy import (
    ReflectionTriggerPolicy,
    ReflectionTriggerContext,
    ExistingReflectionSummary,
)
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.domain.entities.reflection.record import ReflectionRecord, ReflectionAction
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.infrastructure.llm.types import ReflectionSummaryDraft


class StubReflectionEvidenceSignalRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity):
        self.records.append(entity)
        return entity


class StubReflectionRecordRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity):
        self.records.append(entity)
        return entity

    async def update(self, entity):
        for idx, item in enumerate(self.records):
            if item.id == entity.id:
                self.records[idx] = entity
                break
        return entity

    async def get_by_dedupe_key(self, dedupe_key):
        for item in self.records:
            if getattr(item, "dedupe_key", None) == dedupe_key:
                return item
        return None

    async def get_latest_by_aggregation_key(self, aggregation_key):
        for item in reversed(self.records):
            if getattr(item, "aggregation_key", None) == aggregation_key:
                return item
        return None

    async def list_by_goal(self, goal_id, limit=50):
        return [r for r in self.records if r.learner_goal_id == goal_id]


class StubReflectionActionRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity):
        self.records.append(entity)
        return entity

    async def update(self, entity):
        for idx, item in enumerate(self.records):
            if item.id == entity.id:
                self.records[idx] = entity
                break
        return entity

    async def list_by_reflection(self, reflection_id):
        return [r for r in self.records if r.reflection_record_id == reflection_id]


class StubAutonomyJobService:
    def __init__(self):
        self.jobs = []

    async def create_job(self, **kwargs):
        idempotency_key = kwargs.get("idempotency_key")
        for j in self.jobs:
            if j.idempotency_key == idempotency_key:
                return j
        job = ScheduledAutonomyJob.build(
            learner_goal_id=kwargs.get("learner_goal_id"),
            job_type=kwargs.get("job_type"),
            trigger_source=kwargs.get("trigger_source"),
            due_at=kwargs.get("due_at"),
            idempotency_key=idempotency_key,
            payload=kwargs.get("payload"),
        )
        self.jobs.append(job)
        return job


class StubQuizAnswerAttemptRepository:
    def __init__(self, attempts=None):
        self.attempts = attempts or []

    async def list_recent_by_goal_topic(self, learner_goal_id, topic_key, limit=10):
        return [
            a for a in self.attempts
            if a.learner_goal_id == learner_goal_id and a.topic_key == topic_key
        ][:limit]


class StubAuditService:
    def __init__(self):
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs)

    async def record_durable(self, **kwargs):
        pass


class StubLLMProvider:
    async def generate_reflection_summary(self, **kwargs) -> ReflectionSummaryDraft:
        return ReflectionSummaryDraft(
            summary="Reflection summary",
            evidence_summary="Evidence summary",
            recommended_next_step="Next step",
            provider="stub",
            model="stub-model",
            latency_ms=100,
            retry_count=0,
            response_shape_valid=True,
        )


class DummyDailyTaskRepository:
    async def get_by_id(self, task_id):
        return None


class DummyWorkflowRunRepository:
    async def get_by_id(self, run_id):
        return None


class DummyStudyPlanRepository:
    async def get_by_id(self, plan_id):
        return None


@dataclass
class MockInterpretationResult:
    facts: list = dataclass_field(default_factory=list)
    behavior_patterns: list = dataclass_field(default_factory=list)
    contested_items: list = dataclass_field(default_factory=list)
    recommended_constraints: list = dataclass_field(default_factory=list)
    conflict_count: int = 0


@dataclass
class MockCorpusSummary:
    id: str = "mock-summary"
    learner_profile_id: str = "p-1"
    learner_goal_id: str = "g-1"
    summary_text: str = "Mock summary text"
    created_at: datetime = dataclass_field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MockReflectionCorpusResult:
    items: list = dataclass_field(default_factory=list)
    summary: MockCorpusSummary = dataclass_field(default_factory=MockCorpusSummary)


class DummyMemoryService:
    async def build_interpretation(self, **kwargs):
        return MockInterpretationResult()

    async def build_reflection_corpus(self, **kwargs):
        return MockReflectionCorpusResult()


class TestAnswerAttemptReflection:
    @pytest.mark.asyncio
    async def test_repeated_misconception_derivation(self) -> None:
        # Pre-seed a prior attempt with misconception "mc-1"
        prior_attempt = SessionQuizAnswerAttempt.build(
            session_id="session-1",
            quiz_id="quiz-1",
            question_id="q-1",
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            daily_task_id=None,
            topic_key="topic-1",
            subskill_keys=[],
            question_prompt="P",
            reference_answer="A",
            learner_answer="W",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="F",
            misconception_codes=["mc-1"],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        current_attempt = SessionQuizAnswerAttempt.build(
            session_id="session-1",
            quiz_id="quiz-1",
            question_id="q-2",
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            daily_task_id=None,
            topic_key="topic-1",
            subskill_keys=[],
            question_prompt="P",
            reference_answer="A",
            learner_answer="W",
            grading_status="graded",
            grading_source="hybrid",
            score=0.0,
            is_correct=False,
            confidence=0.9,
            rubric_feedback="F",
            misconception_codes=["mc-1"],
            hint_used=False,
            hint_count=0,
            attempt_number=1,
        )

        attempt_repo = StubQuizAnswerAttemptRepository([prior_attempt, current_attempt])
        signal_repo = StubReflectionEvidenceSignalRepository()
        audit_service = StubAuditService()

        evidence_service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=None,
            audit_service=audit_service,
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await evidence_service.derive_from_answer_attempt(attempt=current_attempt)
        assert len(signals) >= 1
        assert any(s.signal_code == "repeated_misconception" for s in signals)

    @pytest.mark.asyncio
    async def test_reflection_cooldown_and_dedupe(self) -> None:
        # Pre-seed an existing reflection summary that is in cooldown
        existing = ExistingReflectionSummary(
            id="ref-1",
            scope="task",
            status="pending",
            cooldown_until=datetime.now(timezone.utc) + timedelta(minutes=5),
            topic_focus="topic-1",
            trigger_source="repeated_misconception",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        context = ReflectionTriggerContext(
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            goal_phase="active",
            existing_reflections=[existing],
            scope="task",
            topic_focus="topic-1",
            has_repeated_misconception=True,
        )

        # Evaluate should return a decision with should_trigger=False due to topic/source cooldown
        decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
        assert len(decisions) >= 1
        # Filter for repeated_misconception trigger decision
        target_decisions = [d for d in decisions if d.trigger_source == "repeated_misconception"]
        assert len(target_decisions) == 1
        assert target_decisions[0].should_trigger is False
        assert target_decisions[0].denial_reason in ("topic_cooldown", "source_cooldown")

    @pytest.mark.asyncio
    async def test_high_risk_action_goes_to_needs_review(self) -> None:
        record_repository = StubReflectionRecordRepository()
        action_repository = StubReflectionActionRepository()
        autonomy_job_service = StubAutonomyJobService()
        audit_service = StubAuditService()

        service = ReflectionService(
            reflection_record_repository=record_repository,
            reflection_action_repository=action_repository,
            goal_repository=None,
            daily_task_repository=DummyDailyTaskRepository(),
            workflow_run_repository=DummyWorkflowRunRepository(),
            study_plan_repository=DummyStudyPlanRepository(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=DummyMemoryService(),
            autonomy_job_service=autonomy_job_service,
            audit_service=audit_service,
            llm_provider=StubLLMProvider(),
        )

        # Trigger reflection with high risk trigger source: low_mastery_high_difficulty_mismatch
        # This primary cause is difficulty_mismatch, which proposes "update_strategy_card_candidate" (high risk)
        req = ReflectionTriggerRequest(
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            scope="goal",
            target_type="learner_goal",
            target_id="g-1",
            trigger_source="low_mastery_high_difficulty_mismatch",
            reflection_depth=1,
            topic_focus="topic-1",
        )

        record = await service.trigger_reflection(req)
        assert record is not None

        # Verify that the proposed action update_strategy_card_candidate is blocked
        actions = await action_repository.list_by_reflection(record.id)
        assert len(actions) == 1
        assert actions[0].action_type == "update_strategy_card_candidate"
        assert actions[0].risk_level == "high"
        assert actions[0].status == "blocked"
        assert actions[0].approval_required is True

    @pytest.mark.asyncio
    async def test_low_risk_review_scheduling_job_is_idempotent(self) -> None:
        record_repository = StubReflectionRecordRepository()
        action_repository = StubReflectionActionRepository()
        autonomy_job_service = StubAutonomyJobService()
        audit_service = StubAuditService()

        service = ReflectionService(
            reflection_record_repository=record_repository,
            reflection_action_repository=action_repository,
            goal_repository=None,
            daily_task_repository=DummyDailyTaskRepository(),
            workflow_run_repository=DummyWorkflowRunRepository(),
            study_plan_repository=DummyStudyPlanRepository(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=DummyMemoryService(),
            autonomy_job_service=autonomy_job_service,
            audit_service=audit_service,
            llm_provider=StubLLMProvider(),
        )

        # Trigger reflection with low risk trigger source: consecutive_wrong_answers
        # Proposes action type "enqueue_review_job" (low risk, review_scheduling job)
        req = ReflectionTriggerRequest(
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            scope="task",
            target_type="daily_task",
            target_id="t-1",
            trigger_source="consecutive_wrong_answers",
            reflection_depth=1,
            topic_focus="topic-1",
        )

        record = await service.trigger_reflection(req)
        assert record is not None

        # Verify that action has been executed automatically
        actions = await action_repository.list_by_reflection(record.id)
        assert len(actions) == 1
        assert actions[0].action_type == "enqueue_review_job"
        assert actions[0].status == "executed"
        
        # Get autonomy job
        assert len(autonomy_job_service.jobs) == 1
        job1 = autonomy_job_service.jobs[0]
        assert job1.job_type == "review_scheduling"

        # Explicitly trigger it again to test idempotency
        await service._execute_action(record=record, action=actions[0])

        # Verify that no duplicate job was created
        assert len(autonomy_job_service.jobs) == 1


class StubMasteryRepository:
    def __init__(self, mastery=None):
        self.mastery = mastery

    async def get_by_goal_and_topic(self, learner_goal_id, topic_key):
        return self.mastery


def _make_attempt(**overrides) -> SessionQuizAnswerAttempt:
    defaults = dict(
        session_id="session-1",
        quiz_id="quiz-1",
        question_id="q-1",
        learner_profile_id="p-1",
        learner_goal_id="g-1",
        daily_task_id=None,
        topic_key="topic-1",
        subskill_keys=[],
        question_prompt="P",
        reference_answer="A",
        learner_answer="W",
        grading_status="graded",
        grading_source="hybrid",
        score=0.0,
        is_correct=False,
        confidence=0.9,
        rubric_feedback="F",
        misconception_codes=[],
        hint_used=False,
        hint_count=0,
        attempt_number=1,
    )
    defaults.update(overrides)
    return SessionQuizAnswerAttempt.build(**defaults)


class TestSignalDerivation:
    @pytest.mark.asyncio
    async def test_hint_after_wrong_answer_signal(self) -> None:
        prior = _make_attempt(question_id="q-1", attempt_number=1, is_correct=False)
        current = _make_attempt(
            question_id="q-1",
            attempt_number=2,
            hint_used=True,
            hint_count=1,
            is_correct=True,
            score=1.0,
        )
        attempt_repo = StubQuizAnswerAttemptRepository([prior, current])
        signal_repo = StubReflectionEvidenceSignalRepository()

        service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=None,
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await service.derive_from_answer_attempt(attempt=current)
        assert any(s.signal_code == "hint_after_wrong_answer" for s in signals)

    @pytest.mark.asyncio
    async def test_low_mastery_high_difficulty_mismatch_signal(self) -> None:
        from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery

        mastery = LearnerTopicMastery.build(
            learner_goal_id="g-1", topic_key="topic-1",
            mastery_score=0.3, confidence=0.5,
        )
        current = _make_attempt(
            metadata={"difficulty": "hard"},
        )
        attempt_repo = StubQuizAnswerAttemptRepository([current])
        signal_repo = StubReflectionEvidenceSignalRepository()

        service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=StubMasteryRepository(mastery),
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await service.derive_from_answer_attempt(attempt=current)
        assert any(s.signal_code == "low_mastery_high_difficulty_mismatch" for s in signals)

    @pytest.mark.asyncio
    async def test_assessment_regression_from_quiz_signal(self) -> None:
        from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery

        mastery = LearnerTopicMastery.build(
            learner_goal_id="g-1", topic_key="topic-1",
            mastery_score=0.85, confidence=0.9,
        )
        current = _make_attempt(is_correct=False, score=0.0)
        attempt_repo = StubQuizAnswerAttemptRepository([current])
        signal_repo = StubReflectionEvidenceSignalRepository()

        service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=StubMasteryRepository(mastery),
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await service.derive_from_answer_attempt(attempt=current)
        assert any(s.signal_code == "assessment_regression_from_quiz" for s in signals)

    @pytest.mark.asyncio
    async def test_quiz_strategy_failure_signal(self) -> None:
        attempts = [
            _make_attempt(is_correct=False, question_id=f"q-{i}")
            for i in range(4)
        ]
        current = _make_attempt(is_correct=False, question_id="q-current")
        all_attempts = attempts + [current]
        attempt_repo = StubQuizAnswerAttemptRepository(all_attempts)
        signal_repo = StubReflectionEvidenceSignalRepository()

        service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=None,
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await service.derive_from_answer_attempt(attempt=current)
        strategy_signals = [s for s in signals if s.signal_code == "quiz_strategy_failure"]
        assert len(strategy_signals) == 1
        assert strategy_signals[0].payload["failure_count"] >= 3

    @pytest.mark.asyncio
    async def test_short_guess_answer_signal(self) -> None:
        current = _make_attempt(learner_answer="A", is_correct=True, score=1.0)
        attempt_repo = StubQuizAnswerAttemptRepository([current])
        signal_repo = StubReflectionEvidenceSignalRepository()

        service = ReflectionEvidenceService(
            repository=signal_repo,
            message_repository=None,
            memory_event_repository=None,
            daily_task_repository=None,
            workflow_run_repository=None,
            learner_topic_mastery_repository=None,
            audit_service=StubAuditService(),
            quiz_answer_attempt_repository=attempt_repo,
        )

        signals = await service.derive_from_answer_attempt(attempt=current)
        assert any(s.signal_code == "short_guess_answer" for s in signals)


class TestNewTriggerDecisions:
    def test_assessment_regression_trigger_decision(self) -> None:
        context = ReflectionTriggerContext(
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            goal_phase="active",
            existing_reflections=[],
            scope="goal",
            topic_focus="topic-1",
            has_assessment_regression_from_quiz=True,
        )
        decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
        target = [d for d in decisions if d.trigger_source == "assessment_regression_from_quiz"]
        assert len(target) == 1
        assert target[0].should_trigger is True

    def test_short_guess_answer_trigger_decision(self) -> None:
        context = ReflectionTriggerContext(
            learner_profile_id="p-1",
            learner_goal_id="g-1",
            goal_phase="active",
            existing_reflections=[],
            scope="task",
            topic_focus="topic-1",
            has_short_guess_answer=True,
        )
        decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
        target = [d for d in decisions if d.trigger_source == "short_guess_answer"]
        assert len(target) == 1
        assert target[0].should_trigger is True
