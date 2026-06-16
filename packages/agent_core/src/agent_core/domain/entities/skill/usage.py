from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError


SKILL_ARTIFACT_STATUSES = {
    "candidate",
    "staged",
    "active",
    "stable",
    "deprecated",
    "archived",
    "rejected",
    "suppressed",
}
SKILL_SELECTABLE_ARTIFACT_STATUSES = {"active", "stable"}
SKILL_TYPES = {"baseline", "learned", "curated", "operator_defined"}
SKILL_USAGE_SURFACES = {
    "chat",
    "hint",
    "quiz",
    "plan_generation",
    "review_scheduling",
    "assessment_generation",
    "replan",
}
SKILL_SCOPES = set(SKILL_USAGE_SURFACES)
SKILL_USAGE_OUTCOME_STATUSES = {
    "completed",
    "partial_success",
    "failed",
    "skipped",
    "aborted",
    "unknown",
}
SKILL_RESOLVER_STATUSES = {"resolved", "missing_artifact", "blocked", "incompatible"}
SKILL_SELECTION_REASONS = {
    "production_default",
    "artifact_missing_static_fallback",
    "suppressed_artifact",
    "contract_incompatible",
    "runtime_resolution_failed",
}
SKILL_OUTCOME_SIGNAL_KEYS = {
    "accepted_by_user",
    "user_correction_requested",
    "downstream_task_completed",
    "safety_refusal",
    "validation_error",
    "score_delta",
    "confidence",
}
SKILL_CURATOR_RECOMMENDATION_TYPES = {
    "activate_candidate",
    "promote_candidate",
    "patch_needed",
    "replace_candidate",
    "merge_candidate",
    "archive_candidate",
    "rollback_review",
    "flag_for_review",
    "restore_candidate",
}
SKILL_CURATOR_RECOMMENDED_ACTIONS = {
    "none",
    "activate_staged",
    "stabilize_active",
    "suppress_selectable",
    "deactivate_active",
    "restore_suppressed",
    "replace_selectable",
    "archive_deprecated",
}
SKILL_CURATOR_RECOMMENDATION_STATUSES = {
    "pending",
    "accepted",
    "dismissed",
    "superseded",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_score(name: str, value: float) -> None:
    if value < 0 or value > 1:
        raise ValidationError(f"{name} must be between 0 and 1.")


@dataclass(kw_only=True)
class SkillUsageEvent:
    id: str
    skill_artifact_id: str | None
    skill_name: str
    skill_version: str | None
    skill_status_at_use: str | None
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
    input_fingerprint: str | None
    output_summary: str | None
    output_fingerprint: str | None
    error_code: str | None
    resolver_status: str
    selection_reason: str
    outcome_signals: dict[str, Any]
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
        skill_status_at_use: str | None = None,
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
        input_fingerprint: str | None = None,
        output_summary: str | None = None,
        output_fingerprint: str | None = None,
        error_code: str | None = None,
        resolver_status: str = "resolved",
        selection_reason: str = "production_default",
        outcome_signals: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "SkillUsageEvent":
        if not skill_name.strip():
            raise ValidationError("skill_name is required.")
        if surface not in SKILL_USAGE_SURFACES:
            raise ValidationError("Unsupported skill usage surface.")
        if outcome_status not in SKILL_USAGE_OUTCOME_STATUSES:
            raise ValidationError("Unsupported skill usage outcome_status.")
        if skill_status_at_use is not None and skill_status_at_use not in SKILL_ARTIFACT_STATUSES:
            raise ValidationError("Unsupported skill_status_at_use.")
        if resolver_status not in SKILL_RESOLVER_STATUSES:
            raise ValidationError("Unsupported skill resolver_status.")
        if selection_reason not in SKILL_SELECTION_REASONS:
            raise ValidationError("Unsupported skill selection_reason.")
        if latency_ms is not None and latency_ms < 0:
            raise ValidationError("latency_ms must be non-negative.")
        if cost_units is not None and cost_units < 0:
            raise ValidationError("cost_units must be non-negative.")
        normalized_signals = cls._normalize_outcome_signals(outcome_signals)
        return cls(
            id=str(uuid4()),
            skill_artifact_id=skill_artifact_id,
            skill_name=skill_name,
            skill_version=skill_version,
            skill_status_at_use=skill_status_at_use,
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
            input_fingerprint=input_fingerprint,
            output_summary=output_summary,
            output_fingerprint=output_fingerprint,
            error_code=error_code,
            resolver_status=resolver_status,
            selection_reason=selection_reason,
            outcome_signals=normalized_signals,
            metadata=dict(metadata or {}),
            created_at=_utcnow(),
        )

    @staticmethod
    def _normalize_outcome_signals(outcome_signals: dict[str, Any] | None) -> dict[str, Any]:
        signals = dict(outcome_signals or {})
        unsupported = set(signals) - SKILL_OUTCOME_SIGNAL_KEYS
        if unsupported:
            raise ValidationError("Unsupported skill outcome signal.")
        for key, value in signals.items():
            if isinstance(value, (dict, list)):
                raise ValidationError("Skill outcome signals must be scalar values.")
            if isinstance(value, str) and len(value) > 128:
                raise ValidationError("Skill outcome signal strings must be 128 characters or fewer.")
            if key in {"score_delta", "confidence"} and value is not None:
                if not isinstance(value, (int, float)):
                    raise ValidationError("Numeric outcome signals must be numbers.")
                if key == "confidence":
                    _validate_score("confidence", float(value))
        return signals
