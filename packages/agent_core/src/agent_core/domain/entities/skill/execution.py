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
class SkillResolution:
    skill_name: str
    surface: str
    artifact_id: str | None
    skill_version: str | None
    artifact_status: str | None
    resolver_status: str
    selection_reason: str
    implementation_binding: str

    @classmethod
    def build(
        cls,
        *,
        skill_name: str,
        surface: str,
        implementation_binding: str,
        artifact_id: str | None = None,
        skill_version: str | None = None,
        artifact_status: str | None = None,
        resolver_status: str = "resolved",
        selection_reason: str = "production_default",
    ) -> "SkillResolution":
        if not skill_name.strip():
            raise ValidationError("skill_name is required.")
        if surface not in SKILL_USAGE_SURFACES:
            raise ValidationError("Unsupported skill usage surface.")
        if not implementation_binding.strip():
            raise ValidationError("implementation_binding is required.")
        if resolver_status not in SKILL_RESOLVER_STATUSES:
            raise ValidationError("Unsupported skill resolver_status.")
        if selection_reason not in SKILL_SELECTION_REASONS:
            raise ValidationError("Unsupported skill selection_reason.")
        return cls(
            skill_name=skill_name,
            surface=surface,
            artifact_id=artifact_id,
            skill_version=skill_version,
            artifact_status=artifact_status,
            resolver_status=resolver_status,
            selection_reason=selection_reason,
            implementation_binding=implementation_binding,
        )


@dataclass(frozen=True)
class SkillExecutionPlan:
    resolution: SkillResolution
    execution_kind: str
    runtime_directives: dict[str, Any]
    tool_plan: list[dict[str, Any]]
    binding_metadata: dict[str, Any]

    @property
    def skill_name(self) -> str:
        return self.resolution.skill_name

    @property
    def surface(self) -> str:
        return self.resolution.surface

    @property
    def artifact_id(self) -> str | None:
        return self.resolution.artifact_id

    @property
    def skill_version(self) -> str | None:
        return self.resolution.skill_version

    @property
    def artifact_status(self) -> str | None:
        return self.resolution.artifact_status

    @property
    def resolver_status(self) -> str:
        return self.resolution.resolver_status

    @property
    def selection_reason(self) -> str:
        return self.resolution.selection_reason

    @property
    def implementation_binding(self) -> str:
        return self.resolution.implementation_binding
