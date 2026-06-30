from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

AUTONOMY_PHASES = {
    "active",
    "assessment_due",
    "archived",
    "completed",
    "paused",
    "replanning",
    "review_due",
}
AUTONOMY_JOB_STATUSES = {"scheduled", "claimed", "completed", "failed", "cancelled"}
AUTONOMY_JOB_TYPES = {
    "assessment_generation",
    "daily_task_materialization",
    "goal_reflection_periodic",
    "goal_reflection",
    "long_term_memory_materialization_replay",
    "mastery_refresh",
    "milestone_generation",
    "plan_extension",
    "replan",
    "reflection_outcome_evaluation",
    "reflection_proposal_evaluation",
    "reflection_skill_evolution_curator",
    "skill_replacement_auto_execution",
    "reflection_proposal_rollout_decision",
    "reflection_proposal_rollout_observation",
    "review_scheduling",
    "task_reflection",
}
AUTONOMY_REPLAN_MODES = {"partial", "full"}
_UNSET = object()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class GoalAutonomyState:
    id: str
    learner_goal_id: str
    phase: str
    current_plan_id: str | None
    next_due_at: datetime | None
    availability_snapshot: dict[str, Any]
    mastery_snapshot: dict[str, Any]
    last_transition_reason: str | None
    last_transition_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, *, learner_goal_id: str) -> "GoalAutonomyState":
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            phase="active",
            current_plan_id=None,
            next_due_at=None,
            availability_snapshot={},
            mastery_snapshot={},
            last_transition_reason="goal_created",
            last_transition_at=now,
            created_at=now,
            updated_at=now,
        )

    def with_transition(
        self,
        *,
        phase: str | None = None,
        current_plan_id: str | None | object = _UNSET,
        next_due_at: datetime | None | object = _UNSET,
        availability_snapshot: dict[str, Any] | None | object = _UNSET,
        mastery_snapshot: dict[str, Any] | None | object = _UNSET,
        reason: str | None = None,
    ) -> "GoalAutonomyState":
        if phase is not None and phase not in AUTONOMY_PHASES:
            raise ValidationError("Unsupported autonomy phase.")
        new_phase = phase or self.phase
        if not self._transition_allowed(self.phase, new_phase):
            raise ValidationError("Unsupported autonomy phase transition.")
        return GoalAutonomyState(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            phase=new_phase,
            current_plan_id=self.current_plan_id if current_plan_id is _UNSET else current_plan_id,
            next_due_at=self.next_due_at if next_due_at is _UNSET else next_due_at,
            availability_snapshot=self.availability_snapshot
            if availability_snapshot is _UNSET
            else availability_snapshot,
            mastery_snapshot=self.mastery_snapshot if mastery_snapshot is _UNSET else mastery_snapshot,
            last_transition_reason=reason,
            last_transition_at=_utcnow(),
            created_at=self.created_at,
            updated_at=_utcnow(),
        )

    @staticmethod
    def _transition_allowed(previous: str, new: str) -> bool:
        if previous == new:
            return True
        allowed = {
            "active": {"assessment_due", "paused", "replanning", "review_due", "completed", "archived"},
            "assessment_due": {"active", "paused", "replanning", "completed", "archived"},
            "paused": {"active", "archived", "completed"},
            "replanning": {"active", "paused", "archived", "completed"},
            "review_due": {"active", "paused", "assessment_due", "completed", "archived"},
            "completed": {"archived"},
            "archived": set(),
        }
        return new in allowed.get(previous, set())


@dataclass(frozen=True)
class ScheduledAutonomyJob:
    id: str
    learner_goal_id: str
    job_type: str
    status: str
    trigger_source: str
    due_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    idempotency_key: str
    payload: dict[str, Any]
    workflow_run_id: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> "ScheduledAutonomyJob":
        if job_type not in AUTONOMY_JOB_TYPES:
            raise ValidationError("Unsupported autonomy job type.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            job_type=job_type,
            status="scheduled",
            trigger_source=trigger_source,
            due_at=due_at,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=0,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            payload=payload or {},
            workflow_run_id=None,
            error_code=None,
            created_at=now,
            updated_at=now,
        )

    def claim(self, *, lease_owner: str, lease_seconds: int) -> "ScheduledAutonomyJob":
        now = _utcnow()
        if self.status == "scheduled":
            pass
        elif self.status == "claimed" and self.lease_expires_at is not None and self.lease_expires_at <= now:
            pass
        else:
            raise ValidationError("Only due scheduled jobs can be claimed.")
        return ScheduledAutonomyJob(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            job_type=self.job_type,
            status="claimed",
            trigger_source=self.trigger_source,
            due_at=self.due_at,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=max(lease_seconds, 1)),
            attempt_count=self.attempt_count + 1,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            workflow_run_id=self.workflow_run_id,
            error_code=None,
            created_at=self.created_at,
            updated_at=now,
        )

    def complete(self, *, workflow_run_id: str | None = None) -> "ScheduledAutonomyJob":
        now = _utcnow()
        return ScheduledAutonomyJob(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            job_type=self.job_type,
            status="completed",
            trigger_source=self.trigger_source,
            due_at=self.due_at,
            lease_owner=self.lease_owner,
            lease_expires_at=self.lease_expires_at,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            workflow_run_id=workflow_run_id or self.workflow_run_id,
            error_code=None,
            created_at=self.created_at,
            updated_at=now,
        )

    def fail(self, *, error_code: str | None) -> "ScheduledAutonomyJob":
        now = _utcnow()
        return ScheduledAutonomyJob(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            job_type=self.job_type,
            status="failed",
            trigger_source=self.trigger_source,
            due_at=self.due_at,
            lease_owner=self.lease_owner,
            lease_expires_at=self.lease_expires_at,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            workflow_run_id=self.workflow_run_id,
            error_code=error_code,
            created_at=self.created_at,
            updated_at=now,
        )

    def retry(self, *, due_at: datetime) -> "ScheduledAutonomyJob":
        now = _utcnow()
        return ScheduledAutonomyJob(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            job_type=self.job_type,
            status="scheduled",
            trigger_source=self.trigger_source,
            due_at=due_at,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            workflow_run_id=self.workflow_run_id,
            error_code=self.error_code,
            created_at=self.created_at,
            updated_at=now,
        )

    def cancel(self, *, error_code: str | None = None) -> "ScheduledAutonomyJob":
        now = _utcnow()
        return ScheduledAutonomyJob(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            job_type=self.job_type,
            status="cancelled",
            trigger_source=self.trigger_source,
            due_at=self.due_at,
            lease_owner=self.lease_owner,
            lease_expires_at=self.lease_expires_at,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            payload=self.payload,
            workflow_run_id=self.workflow_run_id,
            error_code=error_code,
            created_at=self.created_at,
            updated_at=now,
        )


@dataclass(frozen=True)
class LearnerAvailability:
    id: str
    learner_goal_id: str
    timezone: str | None
    available_days: list[str]
    time_windows: list[dict[str, str]]
    max_daily_minutes: int | None
    preferred_session_length_minutes: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        timezone: str | None = None,
        available_days: list[str] | None = None,
        time_windows: list[dict[str, str]] | None = None,
        max_daily_minutes: int | None = None,
        preferred_session_length_minutes: int | None = None,
    ) -> "LearnerAvailability":
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            timezone=timezone,
            available_days=available_days or [],
            time_windows=time_windows or [],
            max_daily_minutes=max_daily_minutes,
            preferred_session_length_minutes=preferred_session_length_minutes,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class LearnerTopicMastery:
    id: str
    learner_goal_id: str
    topic_key: str
    mastery_score: float
    confidence: float
    evidence_count: int
    last_attempt_status: str | None
    last_assessed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, *, learner_goal_id: str, topic_key: str) -> "LearnerTopicMastery":
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            topic_key=topic_key,
            mastery_score=0.5,
            confidence=0.2,
            evidence_count=0,
            last_attempt_status=None,
            last_assessed_at=None,
            created_at=now,
            updated_at=now,
        )

    def update_from_attempt(self, *, outcome_status: str, task_type: str) -> "LearnerTopicMastery":
        outcome_map = {"completed": 0.86, "failed": 0.24, "skipped": 0.42}
        base_score = outcome_map.get(outcome_status, 0.5)
        if task_type == "assessment" and outcome_status == "completed":
            base_score = min(1.0, base_score + 0.08)
        if task_type == "review" and outcome_status == "completed":
            base_score = min(1.0, base_score + 0.04)
        blended = self.mastery_score if self.evidence_count == 0 else (self.mastery_score * 0.65 + base_score * 0.35)
        confidence = min(1.0, 0.2 + (self.evidence_count + 1) * 0.12)
        return LearnerTopicMastery(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            topic_key=self.topic_key,
            mastery_score=round(max(0.0, min(1.0, blended)), 3),
            confidence=round(confidence, 3),
            evidence_count=self.evidence_count + 1,
            last_attempt_status=outcome_status,
            last_assessed_at=_utcnow(),
            created_at=self.created_at,
            updated_at=_utcnow(),
        )


@dataclass(frozen=True)
class TaskAttempt:
    id: str
    learner_goal_id: str
    daily_task_id: str
    workflow_run_id: str | None
    execution_session_id: str | None
    task_type: str
    topic_focus: str
    outcome_status: str
    score: float
    result_note: str | None
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        daily_task_id: str,
        workflow_run_id: str | None,
        execution_session_id: str | None,
        task_type: str,
        topic_focus: str,
        outcome_status: str,
        score: float,
        result_note: str | None,
    ) -> "TaskAttempt":
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            execution_session_id=execution_session_id,
            task_type=task_type,
            topic_focus=topic_focus,
            outcome_status=outcome_status,
            score=score,
            result_note=result_note,
            created_at=_utcnow(),
        )
