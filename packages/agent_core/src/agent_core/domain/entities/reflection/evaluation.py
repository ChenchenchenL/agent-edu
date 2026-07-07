from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

EVIDENCE_SOURCE_TYPES = {"session_turn", "task_attempt", "workflow_run", "memory_corpus", "quiz_answer_attempt"}
EVIDENCE_SIGNAL_CODES = {
    "high_hint_dependency",
    "repeat_confusion",
    "short_guess_answer",
    "assessment_regression",
    "workflow_provider_failure",
    "workflow_validation_failure",
    "workflow_runtime_failure",
    "stalled_progress",
    "repeated_skip_pattern",
    "cross_session_confusion",
    "topic_failure_cluster",
    "repeated_misconception",
    "hint_after_wrong_answer",
    "low_mastery_high_difficulty_mismatch",
    "assessment_regression_from_quiz",
    "quiz_strategy_failure",
}
OUTCOME_EVALUATION_STATUSES = {"pending", "effective", "ineffective", "inconclusive"}
REVIEW_DECISION_TYPES = {"reviewed", "resolved", "override_root_cause", "override_action", "rejected"}
STRATEGY_CARD_STATUSES = {"active", "superseded", "draft"}
INSTRUCTION_MODES = {"guided", "explanatory", "mixed"}
DIFFICULTY_BIASES = {"supportive", "balanced", "challenging"}
REVIEW_BIASES = {"light", "normal", "intensive"}
REPLAN_BIASES = {"conservative", "normal", "aggressive"}
ASSESSMENT_BIASES = {"early", "standard", "delayed"}
REFLECTIVE_MEMORY_LEVELS = {"episode", "pattern", "heuristic"}
REFLECTIVE_MEMORY_STATUSES = {"candidate", "active", "archived", "suppressed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_score(name: str, value: float) -> None:
    if value < 0 or value > 1:
        raise ValidationError(f"{name} must be between 0 and 1.")


@dataclass(frozen=True)
class ReflectionEvidenceSignal:
    id: str
    learner_profile_id: str
    learner_goal_id: str
    session_id: str | None
    daily_task_id: str | None
    workflow_run_id: str | None
    source_type: str
    signal_code: str
    topic_key: str | None
    severity_score: float
    confidence_score: float
    payload: dict[str, Any]
    observed_at: datetime
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str,
        session_id: str | None,
        daily_task_id: str | None,
        workflow_run_id: str | None,
        source_type: str,
        signal_code: str,
        topic_key: str | None,
        severity_score: float,
        confidence_score: float,
        payload: dict[str, Any],
        observed_at: datetime | None = None,
    ) -> "ReflectionEvidenceSignal":
        if source_type not in EVIDENCE_SOURCE_TYPES:
            raise ValidationError("Unsupported reflection evidence source type.")
        if signal_code not in EVIDENCE_SIGNAL_CODES:
            raise ValidationError("Unsupported reflection evidence signal code.")
        _validate_score("severity_score", severity_score)
        _validate_score("confidence_score", confidence_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            source_type=source_type,
            signal_code=signal_code,
            topic_key=topic_key,
            severity_score=severity_score,
            confidence_score=confidence_score,
            payload=dict(payload),
            observed_at=observed_at or now,
            created_at=now,
        )


@dataclass(frozen=True)
class ReflectionOutcomeEvaluation:
    id: str
    reflection_record_id: str
    learner_goal_id: str
    topic_key: str | None
    evaluation_status: str
    window_size: int
    observed_attempt_count: int
    baseline_snapshot: dict[str, Any]
    outcome_snapshot: dict[str, Any]
    improvement_score: float
    evaluation_note: str
    evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        reflection_record_id: str,
        learner_goal_id: str,
        topic_key: str | None,
        window_size: int,
        baseline_snapshot: dict[str, Any],
    ) -> "ReflectionOutcomeEvaluation":
        if window_size < 1:
            raise ValidationError("window_size must be positive.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            topic_key=topic_key,
            evaluation_status="pending",
            window_size=window_size,
            observed_attempt_count=0,
            baseline_snapshot=dict(baseline_snapshot),
            outcome_snapshot={},
            improvement_score=0.0,
            evaluation_note="pending",
            evaluated_at=None,
            created_at=now,
            updated_at=now,
        )

    def with_result(
        self,
        *,
        evaluation_status: str,
        observed_attempt_count: int,
        outcome_snapshot: dict[str, Any],
        improvement_score: float,
        evaluation_note: str,
        evaluated: bool,
    ) -> "ReflectionOutcomeEvaluation":
        if evaluation_status not in OUTCOME_EVALUATION_STATUSES:
            raise ValidationError("Unsupported reflection outcome evaluation status.")
        now = _utcnow()
        return ReflectionOutcomeEvaluation(
            id=self.id,
            reflection_record_id=self.reflection_record_id,
            learner_goal_id=self.learner_goal_id,
            topic_key=self.topic_key,
            evaluation_status=evaluation_status,
            window_size=self.window_size,
            observed_attempt_count=observed_attempt_count,
            baseline_snapshot=dict(self.baseline_snapshot),
            outcome_snapshot=dict(outcome_snapshot),
            improvement_score=improvement_score,
            evaluation_note=evaluation_note,
            evaluated_at=now if evaluated else self.evaluated_at,
            created_at=self.created_at,
            updated_at=now,
        )


@dataclass(frozen=True)
class ReflectionReviewDecision:
    id: str
    reflection_record_id: str
    decision_type: str
    previous_status: str | None
    new_status: str | None
    previous_root_cause: str | None
    new_root_cause: str | None
    previous_action_payload: dict[str, Any] | None
    new_action_payload: dict[str, Any] | None
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        reflection_record_id: str,
        decision_type: str,
        previous_status: str | None,
        new_status: str | None,
        previous_root_cause: str | None,
        new_root_cause: str | None,
        previous_action_payload: dict[str, Any] | None,
        new_action_payload: dict[str, Any] | None,
        reason_code: str,
        reason_note: str | None,
        operator_id: str,
    ) -> "ReflectionReviewDecision":
        if decision_type not in REVIEW_DECISION_TYPES:
            raise ValidationError("Unsupported reflection review decision type.")
        return cls(
            id=str(uuid4()),
            reflection_record_id=reflection_record_id,
            decision_type=decision_type,
            previous_status=previous_status,
            new_status=new_status,
            previous_root_cause=previous_root_cause,
            new_root_cause=new_root_cause,
            previous_action_payload=dict(previous_action_payload) if previous_action_payload is not None else None,
            new_action_payload=dict(new_action_payload) if new_action_payload is not None else None,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class LearnerGoalStrategyCard:
    id: str
    learner_goal_id: str
    version: int
    status: str
    source_reflection_ids: list[str]
    primary_instruction_mode: str
    difficulty_bias: str
    review_bias: str
    replan_bias: str
    assessment_bias: str
    intervention_policy: dict[str, Any]
    rationale: str
    confidence_score: float
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        version: int,
        source_reflection_ids: list[str],
        primary_instruction_mode: str,
        difficulty_bias: str,
        review_bias: str,
        replan_bias: str,
        assessment_bias: str,
        intervention_policy: dict[str, Any],
        rationale: str,
        confidence_score: float,
        status: str = "active",
    ) -> "LearnerGoalStrategyCard":
        if status not in STRATEGY_CARD_STATUSES:
            raise ValidationError("Unsupported strategy card status.")
        if primary_instruction_mode not in INSTRUCTION_MODES:
            raise ValidationError("Unsupported primary instruction mode.")
        if difficulty_bias not in DIFFICULTY_BIASES:
            raise ValidationError("Unsupported difficulty bias.")
        if review_bias not in REVIEW_BIASES:
            raise ValidationError("Unsupported review bias.")
        if replan_bias not in REPLAN_BIASES:
            raise ValidationError("Unsupported replan bias.")
        if assessment_bias not in ASSESSMENT_BIASES:
            raise ValidationError("Unsupported assessment bias.")
        _validate_score("confidence_score", confidence_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            version=version,
            status=status,
            source_reflection_ids=list(source_reflection_ids),
            primary_instruction_mode=primary_instruction_mode,
            difficulty_bias=difficulty_bias,
            review_bias=review_bias,
            replan_bias=replan_bias,
            assessment_bias=assessment_bias,
            intervention_policy=dict(intervention_policy),
            rationale=rationale,
            confidence_score=confidence_score,
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: str) -> "LearnerGoalStrategyCard":
        if status not in STRATEGY_CARD_STATUSES:
            raise ValidationError("Unsupported strategy card status.")
        return LearnerGoalStrategyCard(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            version=self.version,
            status=status,
            source_reflection_ids=list(self.source_reflection_ids),
            primary_instruction_mode=self.primary_instruction_mode,
            difficulty_bias=self.difficulty_bias,
            review_bias=self.review_bias,
            replan_bias=self.replan_bias,
            assessment_bias=self.assessment_bias,
            intervention_policy=dict(self.intervention_policy),
            rationale=self.rationale,
            confidence_score=self.confidence_score,
            created_at=self.created_at,
            updated_at=_utcnow(),
        )


@dataclass(frozen=True)
class ReflectiveMemory:
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    reflection_record_id: str
    memory_key: str
    title: str
    summary: str
    details: str
    memory_level: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    evidence_count: int
    status: str
    source_reflection_ids: list[str]
    source_action_ids: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        reflection_record_id: str,
        memory_key: str,
        title: str,
        summary: str,
        details: str,
        memory_level: str,
        importance_score: float,
        confidence_score: float,
        freshness_score: float,
        evidence_count: int,
        source_reflection_ids: list[str],
        source_action_ids: list[str],
        tags: list[str],
        status: str = "candidate",
    ) -> "ReflectiveMemory":
        if memory_level not in REFLECTIVE_MEMORY_LEVELS:
            raise ValidationError("Unsupported reflective memory level.")
        if status not in REFLECTIVE_MEMORY_STATUSES:
            raise ValidationError("Unsupported reflective memory status.")
        _validate_score("importance_score", importance_score)
        _validate_score("confidence_score", confidence_score)
        _validate_score("freshness_score", freshness_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            reflection_record_id=reflection_record_id,
            memory_key=memory_key,
            title=title,
            summary=summary,
            details=details,
            memory_level=memory_level,
            importance_score=importance_score,
            confidence_score=confidence_score,
            freshness_score=freshness_score,
            evidence_count=evidence_count,
            status=status,
            source_reflection_ids=list(source_reflection_ids),
            source_action_ids=list(source_action_ids),
            tags=list(tags),
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: str,
        *,
        importance_score: float | None = None,
        confidence_score: float | None = None,
        freshness_score: float | None = None,
        evidence_count: int | None = None,
    ) -> "ReflectiveMemory":
        if status not in REFLECTIVE_MEMORY_STATUSES:
            raise ValidationError("Unsupported reflective memory status.")
        return ReflectiveMemory(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            reflection_record_id=self.reflection_record_id,
            memory_key=self.memory_key,
            title=self.title,
            summary=self.summary,
            details=self.details,
            memory_level=self.memory_level,
            importance_score=self.importance_score if importance_score is None else importance_score,
            confidence_score=self.confidence_score if confidence_score is None else confidence_score,
            freshness_score=self.freshness_score if freshness_score is None else freshness_score,
            evidence_count=self.evidence_count if evidence_count is None else evidence_count,
            status=status,
            source_reflection_ids=list(self.source_reflection_ids),
            source_action_ids=list(self.source_action_ids),
            tags=list(self.tags),
            created_at=self.created_at,
            updated_at=_utcnow(),
        )
