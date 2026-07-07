from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

REFLECTION_SCOPES = {"task", "goal"}
REFLECTION_TARGET_TYPES = {"daily_task", "workflow_run", "learner_goal", "study_plan"}
REFLECTION_TRIGGER_SOURCES = {
    "task_failed",
    "task_skipped",
    "assessment_completed",
    "workflow_failed",
    "plan_replanned",
    "consecutive_failure_pattern",
    "corpus_review_threshold",
    "corpus_backlog_threshold",
    "corpus_contested_high_priority",
    "fallback_to_baseline_burst",
    "low_confidence_burst",
    "repeated_sequence_mismatch",
    "consecutive_wrong_answers",
    "repeated_misconception",
    "low_mastery_high_difficulty_mismatch",
    "hint_dependency_failure",
    "high_failure_rate_artifact",
    "assessment_regression_from_quiz",
    "short_guess_answer",
}
REFLECTION_STATUSES = {"pending", "completed", "actioned", "needs_review", "failed"}
REFLECTION_ROOT_CAUSES = {
    "knowledge_gap",
    "difficulty_mismatch",
    "review_gap",
    "sequencing_issue",
    "engagement_constraint",
    "workflow_issue",
    "assessment_regression",
    "router_issue",
    "template_issue",
    "memory_governance_issue",
    "sandbox_admission_issue",
}
REFLECTION_SEVERITIES = {"low", "medium", "high"}
REFLECTION_ACTION_TYPES = {
    "enqueue_replan_job",
    "enqueue_review_job",
    "enqueue_assessment_job",
    "enqueue_router_review",
    "enqueue_template_review",
    "enqueue_memory_governance_review",
    "enqueue_sandbox_admission_review",
    "update_strategy_card_candidate",
    "enqueue_skill_curator_review",
}
REFLECTION_ACTION_STATUSES = {"proposed", "executed", "blocked", "failed", "skipped"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ReflectionRecord:
    id: str
    learner_profile_id: str
    learner_goal_id: str
    daily_task_id: str | None
    workflow_run_id: str | None
    study_plan_id: str | None
    scope: str
    target_type: str
    target_id: str
    trigger_source: str
    status: str
    reflection_depth: int
    dedupe_key: str
    aggregation_key: str
    duplicate_count: int
    priority_score: float
    last_duplicate_at: datetime | None
    cooldown_until: datetime | None
    primary_root_cause: str
    secondary_root_causes: list[str]
    severity: str
    confidence_score: float
    summary: str
    evidence_summary: str
    recommended_next_step: str
    evidence_payload: dict[str, Any]
    llm_provider: str | None
    llm_model: str | None
    llm_latency_ms: int | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str,
        daily_task_id: str | None,
        workflow_run_id: str | None,
        study_plan_id: str | None,
        scope: str,
        target_type: str,
        target_id: str,
        trigger_source: str,
        reflection_depth: int,
        dedupe_key: str,
        aggregation_key: str,
        duplicate_count: int,
        priority_score: float,
        last_duplicate_at: datetime | None,
        cooldown_until: datetime | None,
        primary_root_cause: str,
        secondary_root_causes: list[str],
        severity: str,
        confidence_score: float,
        summary: str,
        evidence_summary: str,
        recommended_next_step: str,
        evidence_payload: dict[str, Any],
        llm_provider: str | None = None,
        llm_model: str | None = None,
        llm_latency_ms: int | None = None,
    ) -> "ReflectionRecord":
        cls._validate(
            scope=scope,
            target_type=target_type,
            trigger_source=trigger_source,
            primary_root_cause=primary_root_cause,
            secondary_root_causes=secondary_root_causes,
            severity=severity,
            reflection_depth=reflection_depth,
            confidence_score=confidence_score,
        )
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            study_plan_id=study_plan_id,
            scope=scope,
            target_type=target_type,
            target_id=target_id,
            trigger_source=trigger_source,
            status="pending",
            reflection_depth=reflection_depth,
            dedupe_key=dedupe_key,
            aggregation_key=aggregation_key,
            duplicate_count=duplicate_count,
            priority_score=priority_score,
            last_duplicate_at=last_duplicate_at,
            cooldown_until=cooldown_until,
            primary_root_cause=primary_root_cause,
            secondary_root_causes=list(secondary_root_causes),
            severity=severity,
            confidence_score=confidence_score,
            summary=summary,
            evidence_summary=evidence_summary,
            recommended_next_step=recommended_next_step,
            evidence_payload=dict(evidence_payload),
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_latency_ms=llm_latency_ms,
            created_at=now,
            updated_at=now,
            processed_at=None,
        )

    def with_status(
        self,
        status: str,
        *,
        summary: str | None = None,
        evidence_summary: str | None = None,
        recommended_next_step: str | None = None,
        llm_provider: str | None | object = None,
        llm_model: str | None | object = None,
        llm_latency_ms: int | None | object = None,
        processed: bool = False,
    ) -> "ReflectionRecord":
        if status not in REFLECTION_STATUSES:
            raise ValidationError("Unsupported reflection record status.")
        now = _utcnow()
        return ReflectionRecord(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            daily_task_id=self.daily_task_id,
            workflow_run_id=self.workflow_run_id,
            study_plan_id=self.study_plan_id,
            scope=self.scope,
            target_type=self.target_type,
            target_id=self.target_id,
            trigger_source=self.trigger_source,
            status=status,
            reflection_depth=self.reflection_depth,
            dedupe_key=self.dedupe_key,
            aggregation_key=self.aggregation_key,
            duplicate_count=self.duplicate_count,
            priority_score=self.priority_score,
            last_duplicate_at=self.last_duplicate_at,
            cooldown_until=self.cooldown_until,
            primary_root_cause=self.primary_root_cause,
            secondary_root_causes=list(self.secondary_root_causes),
            severity=self.severity,
            confidence_score=self.confidence_score,
            summary=summary if summary is not None else self.summary,
            evidence_summary=evidence_summary if evidence_summary is not None else self.evidence_summary,
            recommended_next_step=(
                recommended_next_step if recommended_next_step is not None else self.recommended_next_step
            ),
            evidence_payload=dict(self.evidence_payload),
            llm_provider=self.llm_provider if llm_provider is None else llm_provider,
            llm_model=self.llm_model if llm_model is None else llm_model,
            llm_latency_ms=self.llm_latency_ms if llm_latency_ms is None else llm_latency_ms,
            created_at=self.created_at,
            updated_at=now,
            processed_at=now if processed else self.processed_at,
        )

    def with_aggregation_update(
        self,
        *,
        duplicate_count: int,
        priority_score: float,
        last_duplicate_at: datetime | None,
        cooldown_until: datetime | None,
    ) -> "ReflectionRecord":
        return ReflectionRecord(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            daily_task_id=self.daily_task_id,
            workflow_run_id=self.workflow_run_id,
            study_plan_id=self.study_plan_id,
            scope=self.scope,
            target_type=self.target_type,
            target_id=self.target_id,
            trigger_source=self.trigger_source,
            status=self.status,
            reflection_depth=self.reflection_depth,
            dedupe_key=self.dedupe_key,
            aggregation_key=self.aggregation_key,
            duplicate_count=duplicate_count,
            priority_score=priority_score,
            last_duplicate_at=last_duplicate_at,
            cooldown_until=cooldown_until,
            primary_root_cause=self.primary_root_cause,
            secondary_root_causes=list(self.secondary_root_causes),
            severity=self.severity,
            confidence_score=self.confidence_score,
            summary=self.summary,
            evidence_summary=self.evidence_summary,
            recommended_next_step=self.recommended_next_step,
            evidence_payload=dict(self.evidence_payload),
            llm_provider=self.llm_provider,
            llm_model=self.llm_model,
            llm_latency_ms=self.llm_latency_ms,
            created_at=self.created_at,
            updated_at=_utcnow(),
            processed_at=self.processed_at,
        )

    @staticmethod
    def _validate(
        *,
        scope: str,
        target_type: str,
        trigger_source: str,
        primary_root_cause: str,
        secondary_root_causes: list[str],
        severity: str,
        reflection_depth: int,
        confidence_score: float,
    ) -> None:
        if scope not in REFLECTION_SCOPES:
            raise ValidationError("Unsupported reflection scope.")
        if target_type not in REFLECTION_TARGET_TYPES:
            raise ValidationError("Unsupported reflection target type.")
        if trigger_source not in REFLECTION_TRIGGER_SOURCES:
            raise ValidationError("Unsupported reflection trigger source.")
        if primary_root_cause not in REFLECTION_ROOT_CAUSES:
            raise ValidationError("Unsupported primary reflection root cause.")
        invalid_secondary = [item for item in secondary_root_causes if item not in REFLECTION_ROOT_CAUSES]
        if invalid_secondary:
            raise ValidationError("Unsupported secondary reflection root cause.")
        if severity not in REFLECTION_SEVERITIES:
            raise ValidationError("Unsupported reflection severity.")
        if reflection_depth < 1:
            raise ValidationError("reflection_depth must be at least 1.")
        if confidence_score < 0 or confidence_score > 1:
            raise ValidationError("confidence_score must be between 0 and 1.")


@dataclass(frozen=True)
class ReflectionAction:
    id: str
    reflection_record_id: str
    action_type: str
    risk_level: str
    status: str
    approval_required: bool
    payload: dict[str, Any]
    execution_result: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None

    @classmethod
    def build(
        cls,
        *,
        reflection_record_id: str,
        action_type: str,
        risk_level: str,
        approval_required: bool,
        payload: dict[str, Any],
    ) -> "ReflectionAction":
        if action_type not in REFLECTION_ACTION_TYPES:
            raise ValidationError("Unsupported reflection action type.")
        if risk_level not in REFLECTION_SEVERITIES:
            raise ValidationError("Unsupported reflection action risk level.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            reflection_record_id=reflection_record_id,
            action_type=action_type,
            risk_level=risk_level,
            status="proposed",
            approval_required=approval_required,
            payload=dict(payload),
            execution_result={},
            created_at=now,
            updated_at=now,
            executed_at=None,
        )

    def with_status(self, status: str, *, execution_result: dict[str, Any] | None = None, executed: bool = False) -> "ReflectionAction":
        if status not in REFLECTION_ACTION_STATUSES:
            raise ValidationError("Unsupported reflection action status.")
        now = _utcnow()
        return ReflectionAction(
            id=self.id,
            reflection_record_id=self.reflection_record_id,
            action_type=self.action_type,
            risk_level=self.risk_level,
            status=status,
            approval_required=self.approval_required,
            payload=dict(self.payload),
            execution_result=dict(execution_result or self.execution_result),
            created_at=self.created_at,
            updated_at=now,
            executed_at=now if executed else self.executed_at,
        )
