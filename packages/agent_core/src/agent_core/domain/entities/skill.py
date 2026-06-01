from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError


SKILL_ARTIFACT_STATUSES = {"candidate", "staged", "active", "deprecated", "archived"}
SKILL_USAGE_SURFACES = {
    "chat",
    "hint",
    "quiz",
    "plan_generation",
    "review_scheduling",
    "assessment_generation",
    "replan",
}
SKILL_USAGE_OUTCOME_STATUSES = {"completed", "failed", "skipped"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_score(name: str, value: float) -> None:
    if value < 0 or value > 1:
        raise ValidationError(f"{name} must be between 0 and 1.")


@dataclass(frozen=True)
class SkillArtifact:
    id: str
    name: str
    version: str
    skill_type: str
    scope: str
    status: str
    description: str
    definition: dict[str, Any]
    runtime_directives: dict[str, Any]
    tool_plan: list[dict[str, Any]]
    source_reflection_ids: list[str]
    source_memory_ids: list[str]
    source_proposal_id: str | None
    quality_score: float
    created_by: str
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        name: str,
        version: str,
        skill_type: str,
        scope: str,
        status: str,
        description: str,
        definition: dict[str, Any] | None = None,
        runtime_directives: dict[str, Any] | None = None,
        tool_plan: list[dict[str, Any]] | None = None,
        source_reflection_ids: list[str] | None = None,
        source_memory_ids: list[str] | None = None,
        source_proposal_id: str | None = None,
        quality_score: float = 0.0,
        created_by: str = "system",
        approved_by: str | None = None,
        approved_at: datetime | None = None,
    ) -> "SkillArtifact":
        if not name.strip():
            raise ValidationError("skill artifact name is required.")
        if not version.strip():
            raise ValidationError("skill artifact version is required.")
        if status not in SKILL_ARTIFACT_STATUSES:
            raise ValidationError("Unsupported skill artifact status.")
        _validate_score("quality_score", quality_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            name=name,
            version=version,
            skill_type=skill_type,
            scope=scope,
            status=status,
            description=description,
            definition=dict(definition or {}),
            runtime_directives=dict(runtime_directives or {}),
            tool_plan=[dict(item) for item in tool_plan or []],
            source_reflection_ids=list(source_reflection_ids or []),
            source_memory_ids=list(source_memory_ids or []),
            source_proposal_id=source_proposal_id,
            quality_score=quality_score,
            created_by=created_by,
            approved_by=approved_by,
            approved_at=approved_at,
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class SkillUsageEvent:
    id: str
    skill_artifact_id: str | None
    skill_name: str
    skill_version: str | None
    learner_profile_id: str | None
    learner_goal_id: str | None
    session_id: str | None
    daily_task_id: str | None
    workflow_run_id: str | None
    surface: str
    topic_key: str | None
    trigger_source: str | None
    outcome_status: str
    latency_ms: int | None
    cost_units: float | None
    input_summary: str | None
    output_summary: str | None
    error_code: str | None
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        skill_artifact_id: str | None,
        skill_name: str,
        skill_version: str | None,
        surface: str,
        outcome_status: str,
        learner_profile_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        daily_task_id: str | None = None,
        workflow_run_id: str | None = None,
        topic_key: str | None = None,
        trigger_source: str | None = None,
        latency_ms: int | None = None,
        cost_units: float | None = None,
        input_summary: str | None = None,
        output_summary: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "SkillUsageEvent":
        if not skill_name.strip():
            raise ValidationError("skill_name is required.")
        if surface not in SKILL_USAGE_SURFACES:
            raise ValidationError("Unsupported skill usage surface.")
        if outcome_status not in SKILL_USAGE_OUTCOME_STATUSES:
            raise ValidationError("Unsupported skill usage outcome_status.")
        if latency_ms is not None and latency_ms < 0:
            raise ValidationError("latency_ms must be non-negative.")
        if cost_units is not None and cost_units < 0:
            raise ValidationError("cost_units must be non-negative.")
        return cls(
            id=str(uuid4()),
            skill_artifact_id=skill_artifact_id,
            skill_name=skill_name,
            skill_version=skill_version,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            surface=surface,
            topic_key=topic_key,
            trigger_source=trigger_source,
            outcome_status=outcome_status,
            latency_ms=latency_ms,
            cost_units=cost_units,
            input_summary=input_summary,
            output_summary=output_summary,
            error_code=error_code,
            metadata=dict(metadata or {}),
            created_at=_utcnow(),
        )
