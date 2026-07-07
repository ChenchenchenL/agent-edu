"""Unit and integration tests for the Phase 3 Adaptive Quiz Policy."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from agent_core.application.services.adaptive_quiz_policy import (
    AdaptiveQuizPolicyService,
    AdaptiveQuizPolicyOutput,
)
from agent_core.application.services.audit import AuditService
from agent_core.application.services.quiz import QuizService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery
from agent_core.domain.entities.session.quiz import SessionQuiz, SessionQuizAnswerAttempt
from agent_core.domain.entities.reflection_v2 import LearnerGoalStrategyCard
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.schemas.quiz import GenerateQuizRequest, QuizQuestion
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.llm.types import QuizDraft

# Reuse stub classes from test_quiz_service.py or construct custom stubs
from test_quiz_service import (
    FakeSession,
    StubAuditRepository,
    StubQuizRepository,
    StubSessionRepository,
    StubLLMProvider,
)


@pytest.fixture
def policy_service() -> AdaptiveQuizPolicyService:
    return AdaptiveQuizPolicyService()


def make_attempt(
    is_correct: bool,
    misconception_codes: list[str] = (),
    subskill_keys: list[str] = (),
) -> SessionQuizAnswerAttempt:
    return SessionQuizAnswerAttempt.build(
        session_id="session-1",
        quiz_id="quiz-1",
        question_id="question-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id=None,
        topic_key="Matrices",
        subskill_keys=subskill_keys,
        question_prompt="What is A?",
        reference_answer="A",
        learner_answer="B" if not is_correct else "A",
        grading_status="graded",
        grading_source="deterministic",
        score=1.0 if is_correct else 0.0,
        is_correct=is_correct,
        confidence=1.0,
        rubric_feedback=None,
        misconception_codes=misconception_codes,
        hint_used=False,
        hint_count=0,
        attempt_number=1,
    )


class TestAdaptiveQuizPolicyUnit:
    """Unit tests for AdaptiveQuizPolicyService."""

    def test_low_mastery_lowers_difficulty(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
        )

        assert output.effective_difficulty == "easy"
        assert output.question_count == 5
        assert "resolved as 'remedial'" in output.adaptation_rationale

    def test_high_mastery_raises_difficulty(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.88, confidence=0.8, evidence_count=5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
        )

        assert output.effective_difficulty == "hard"
        assert output.question_count == 2
        assert "resolved as 'advanced'" in output.adaptation_rationale

    def test_high_mastery_preserves_hard_difficulty(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.9, confidence=0.8, evidence_count=5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="hard",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
        )

        assert output.effective_difficulty == "hard"

    def test_repeated_misconception_changes_distribution(self, policy_service: AdaptiveQuizPolicyService) -> None:
        attempts = [
            make_attempt(is_correct=False, misconception_codes=["MC-1"], subskill_keys=["sub-1"]),
            make_attempt(is_correct=False, misconception_codes=["MC-1"], subskill_keys=["sub-1"]),
        ]

        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.7, confidence=0.5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=attempts,
        )

        assert "MC-1" in output.desired_misconception_probes
        assert "misconception:MC-1" in output.remediation_focus
        assert output.topic_subskill_distribution["sub-1"] == 0.7
        assert output.topic_subskill_distribution["Matrices"] == 0.3
        assert "Targeting repeated misconception" in output.adaptation_rationale

    def test_strategy_card_difficulty_bias_supportive(self, policy_service: AdaptiveQuizPolicyService) -> None:
        card = LearnerGoalStrategyCard.build(
            learner_goal_id="goal-1",
            version=1,
            source_reflection_ids=["ref-1"],
            primary_instruction_mode="guided",
            difficulty_bias="supportive",
            review_bias="normal",
            replan_bias="normal",
            assessment_bias="standard",
            intervention_policy={},
            rationale="Test supportive bias",
            confidence_score=0.8,
        )

        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.7, confidence=0.5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
            active_strategy_card=card,
        )

        assert output.effective_difficulty == "easy"
        assert "difficulty_bias=supportive applied" in output.adaptation_rationale

    def test_strategy_card_difficulty_bias_challenging(self, policy_service: AdaptiveQuizPolicyService) -> None:
        card = LearnerGoalStrategyCard.build(
            learner_goal_id="goal-1",
            version=1,
            source_reflection_ids=["ref-1"],
            primary_instruction_mode="guided",
            difficulty_bias="challenging",
            review_bias="normal",
            replan_bias="normal",
            assessment_bias="standard",
            intervention_policy={},
            rationale="Test challenging bias",
            confidence_score=0.8,
        )

        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.7, confidence=0.5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
            active_strategy_card=card,
        )

        assert output.effective_difficulty == "hard"
        assert "difficulty_bias=challenging applied" in output.adaptation_rationale

    def test_rollout_runtime_directives_override_default_policy(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )

        runtime_directives = {
            "difficulty": "hard",
            "question_count": 6,
            "feedback_style": "special",
            "skill_directives": ["some_directive"],
        }

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
            runtime_directives=runtime_directives,
        )

        assert output.effective_difficulty == "hard"
        assert output.question_count == 6
        assert output.feedback_style == "special"
        assert output.skill_directives["directives"] == ["some_directive"]
        assert "Difficulty overridden by runtime directives" in output.adaptation_rationale
        assert "Question count overridden by runtime directives" in output.adaptation_rationale

    def test_invalid_runtime_difficulty_ignored(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )

        runtime_directives = {"difficulty": "impossible"}

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
            runtime_directives=runtime_directives,
        )

        assert output.effective_difficulty == "easy"
        assert "Difficulty overridden" not in output.adaptation_rationale

    def test_invalid_runtime_question_count_ignored(self, policy_service: AdaptiveQuizPolicyService) -> None:
        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )

        runtime_directives = {"question_count": "not-a-number"}

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=[],
            runtime_directives=runtime_directives,
        )

        assert output.question_count == 5
        assert "Question count overridden" not in output.adaptation_rationale

    def test_no_mastery_with_recent_failures_remmedial(self, policy_service: AdaptiveQuizPolicyService) -> None:
        attempts = [
            make_attempt(is_correct=False),
            make_attempt(is_correct=False),
        ]

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=None,
            recent_attempts=attempts,
        )

        assert output.effective_difficulty == "easy"
        assert "resolved as 'remedial'" in output.adaptation_rationale

    def test_no_mastery_no_failures_standard(self, policy_service: AdaptiveQuizPolicyService) -> None:
        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=None,
            recent_attempts=[],
        )

        assert output.effective_difficulty == "medium"
        assert "resolved as 'standard'" in output.adaptation_rationale

    def test_multiple_misconceptions_distribution(self, policy_service: AdaptiveQuizPolicyService) -> None:
        attempts = [
            make_attempt(is_correct=False, misconception_codes=["MC-1", "MC-2"], subskill_keys=["sub-1"]),
            make_attempt(is_correct=False, misconception_codes=["MC-1", "MC-2"], subskill_keys=["sub-2"]),
        ]

        mastery = LearnerTopicMastery.build(
            learner_goal_id="goal-1", topic_key="Matrices",
            mastery_score=0.7, confidence=0.5,
        )

        output = policy_service.resolve_policy(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            session_id="session-1",
            topic_key="Matrices",
            requested_difficulty="medium",
            requested_question_count=3,
            current_mastery=mastery,
            recent_attempts=attempts,
        )

        assert "MC-1" in output.desired_misconception_probes
        assert "MC-2" in output.desired_misconception_probes
        assert "misconception:MC-1" in output.remediation_focus
        assert "misconception:MC-2" in output.remediation_focus


class StubLearnerTopicMasteryRepository:
    def __init__(self, mastery: LearnerTopicMastery | None = None) -> None:
        self.mastery = mastery

    async def get_by_goal_and_topic(self, learner_goal_id: str, topic_key: str) -> LearnerTopicMastery | None:
        return self.mastery


class StubSessionQuizAnswerAttemptRepository:
    def __init__(self, attempts: list[SessionQuizAnswerAttempt] = None) -> None:
        self.attempts = attempts or []

    async def list_recent_by_goal_topic(
        self, learner_goal_id: str, topic_key: str, limit: int = 20
    ) -> list[SessionQuizAnswerAttempt]:
        return self.attempts[:limit]


class StubLearnerGoalStrategyCardRepository:
    def __init__(self, card: LearnerGoalStrategyCard | None = None) -> None:
        self.card = card

    async def get_active_by_goal(self, learner_goal_id: str) -> LearnerGoalStrategyCard | None:
        return self.card


class CaptureQuizServiceLLMProvider:
    def __init__(self) -> None:
        self.last_difficulty = None
        self.last_question_count = None
        self.last_skill_directives = None
        self.last_feedback_style = None

    async def generate_quiz_draft(
        self,
        *,
        topic: str,
        difficulty: str,
        question_count: int,
        skill_directives: list[str] | None = None,
        feedback_style: str | None = None,
    ) -> QuizDraft:
        self.last_difficulty = difficulty
        self.last_question_count = question_count
        self.last_skill_directives = skill_directives
        self.last_feedback_style = feedback_style
        return QuizDraft(
            topic=topic,
            difficulty=difficulty,
            questions=[
                QuizQuestion(prompt=f"{topic} question {index + 1}", answer=f"answer {index + 1}")
                for index in range(question_count)
            ],
            provider="capture",
            model="capture-model",
            latency_ms=10,
            retry_count=0,
            response_shape_valid=True,
        )


class TestQuizServiceAdaptiveIntegration:
    """Integration tests verifying QuizService generate_quiz merges policy and logs audit."""

    @pytest.mark.asyncio
    async def test_generate_quiz_integration_with_low_mastery(self, monkeypatch) -> None:
        session = LearningSession.build(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            title="Linear Algebra",
            subject="Matrices",
        )
        
        mastery = LearnerTopicMastery.build(
            learner_goal_id=session.learner_goal_id, topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )

        stub_mastery_repo = StubLearnerTopicMasteryRepository(mastery)
        stub_attempt_repo = StubSessionQuizAnswerAttemptRepository([])
        stub_card_repo = StubLearnerGoalStrategyCardRepository(None)

        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerTopicMasteryRepository",
            lambda s: stub_mastery_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.SessionQuizAnswerAttemptRepository",
            lambda s: stub_attempt_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerGoalStrategyCardRepository",
            lambda s: stub_card_repo,
        )

        db_session = FakeSession()
        audit_repository = StubAuditRepository()
        quiz_repository = StubQuizRepository()
        llm_provider = CaptureQuizServiceLLMProvider()

        service = QuizService(
            db_session=db_session,
            audit_service=AuditService(audit_repository),
            session_repository=StubSessionRepository(session),
            quiz_repository=quiz_repository,
            llm_provider=llm_provider,
            skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
        )

        await service.generate_quiz(
            GenerateQuizRequest(
                session_id=session.id,
                topic="Matrices",
                difficulty="medium",
                question_count=3,
            )
        )

        assert llm_provider.last_difficulty == "easy"
        assert llm_provider.last_question_count == 5

    @pytest.mark.asyncio
    async def test_generate_quiz_integration_with_high_mastery(self, monkeypatch) -> None:
        session = LearningSession.build(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            title="Linear Algebra",
            subject="Matrices",
        )
        
        mastery = LearnerTopicMastery.build(
            learner_goal_id=session.learner_goal_id, topic_key="Matrices",
            mastery_score=0.9, confidence=0.85, evidence_count=6,
        )

        stub_mastery_repo = StubLearnerTopicMasteryRepository(mastery)
        stub_attempt_repo = StubSessionQuizAnswerAttemptRepository([])
        stub_card_repo = StubLearnerGoalStrategyCardRepository(None)

        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerTopicMasteryRepository",
            lambda s: stub_mastery_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.SessionQuizAnswerAttemptRepository",
            lambda s: stub_attempt_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerGoalStrategyCardRepository",
            lambda s: stub_card_repo,
        )

        db_session = FakeSession()
        audit_repository = StubAuditRepository()
        quiz_repository = StubQuizRepository()
        llm_provider = CaptureQuizServiceLLMProvider()

        service = QuizService(
            db_session=db_session,
            audit_service=AuditService(audit_repository),
            session_repository=StubSessionRepository(session),
            quiz_repository=quiz_repository,
            llm_provider=llm_provider,
            skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
        )

        await service.generate_quiz(
            GenerateQuizRequest(
                session_id=session.id,
                topic="Matrices",
                difficulty="medium",
                question_count=3,
            )
        )

        assert llm_provider.last_difficulty == "hard"
        assert llm_provider.last_question_count == 2

    @pytest.mark.asyncio
    async def test_audit_logs_adaptation_rationale(self, monkeypatch) -> None:
        session = LearningSession.build(
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            title="Linear Algebra",
            subject="Matrices",
        )
        mastery = LearnerTopicMastery.build(
            learner_goal_id=session.learner_goal_id, topic_key="Matrices",
            mastery_score=0.3, confidence=0.5,
        )
        
        stub_mastery_repo = StubLearnerTopicMasteryRepository(mastery)
        stub_attempt_repo = StubSessionQuizAnswerAttemptRepository([])
        stub_card_repo = StubLearnerGoalStrategyCardRepository(None)
    
        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerTopicMasteryRepository",
            lambda s: stub_mastery_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.SessionQuizAnswerAttemptRepository",
            lambda s: stub_attempt_repo,
        )
        monkeypatch.setattr(
            "agent_core.application.services.quiz.LearnerGoalStrategyCardRepository",
            lambda s: stub_card_repo,
        )
    
        db_session = FakeSession()
        audit_repository = StubAuditRepository()
        quiz_repository = StubQuizRepository()
        llm_provider = CaptureQuizServiceLLMProvider()
    
        service = QuizService(
            db_session=db_session,
            audit_service=AuditService(audit_repository),
            session_repository=StubSessionRepository(session),
            quiz_repository=quiz_repository,
            llm_provider=llm_provider,
            skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
        )
    
        response = await service.generate_quiz(
            GenerateQuizRequest(
                session_id=session.id,
                topic="Matrices",
                difficulty="medium",
                question_count=3,
            )
        )
    
        assert llm_provider.last_difficulty == "easy"
        assert llm_provider.last_question_count == 5
    
        generated_event = next(e for e in audit_repository.events if e.event_type == "quiz.generated")
        assert "adaptation_rationale" in generated_event.event_data
        assert "resolved as 'remedial'" in generated_event.event_data["adaptation_rationale"]

