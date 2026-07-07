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
    "baseline",
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
    "mastery_before",
    "mastery_after",
    "mastery_delta",
    "answer_correctness_delta",
    "hint_dependency_delta",
    "misconception_reduction",
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
    "patch_routing_policy",
    "patch_template_policy",
    "patch_skill_package",
    "select_replacement_skill_package",
    "demote_candidate",
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
    "demote_active",
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
class SkillCuratorRecommendation:
    id: str
    artifact_id: str | None
    skill_name: str
    skill_version: str | None
    artifact_status: str | None
    lineage_id: str | None
    scope: str
    surface: str
    recommendation_type: str
    recommended_action: str
    status: str
    reason_code: str
    reason_note: str | None
    evidence_snapshot: dict[str, Any]
    metrics_snapshot: dict[str, Any]
    related_artifact_ids: list[str]
    source_job_id: str | None
    created_by: str
    accepted_by: str | None
    accepted_at: datetime | None
    dismissed_by: str | None
    dismissed_at: datetime | None
    decision_reason_code: str | None
    decision_reason_note: str | None
    action_result: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        skill_name: str,
        scope: str,
        surface: str,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
        created_by: str,
        artifact_id: str | None = None,
        skill_version: str | None = None,
        artifact_status: str | None = None,
        lineage_id: str | None = None,
        reason_note: str | None = None,
        evidence_snapshot: dict[str, Any] | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        related_artifact_ids: list[str] | None = None,
        source_job_id: str | None = None,
    ) -> "SkillCuratorRecommendation":
        if not skill_name.strip():
            raise ValidationError("skill_name is required.")
        if scope not in SKILL_SCOPES:
            raise ValidationError("Unsupported skill recommendation scope.")
        if surface not in SKILL_USAGE_SURFACES:
            raise ValidationError("Unsupported skill recommendation surface.")
        if recommendation_type not in SKILL_CURATOR_RECOMMENDATION_TYPES:
            raise ValidationError("Unsupported skill curator recommendation_type.")
        if recommended_action not in SKILL_CURATOR_RECOMMENDED_ACTIONS:
            raise ValidationError("Unsupported skill curator recommended_action.")
        if artifact_status is not None and artifact_status not in SKILL_ARTIFACT_STATUSES:
            raise ValidationError("Unsupported recommendation artifact_status.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        if not created_by.strip():
            raise ValidationError("created_by is required.")
        if evidence_snapshot is not None and not isinstance(evidence_snapshot, dict):
            raise ValidationError("evidence_snapshot must be an object.")
        if metrics_snapshot is not None and not isinstance(metrics_snapshot, dict):
            raise ValidationError("metrics_snapshot must be an object.")
        cls._validate_action(
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            artifact_id=artifact_id,
        )
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            artifact_id=artifact_id,
            skill_name=skill_name.strip(),
            skill_version=skill_version,
            artifact_status=artifact_status,
            lineage_id=lineage_id,
            scope=scope,
            surface=surface,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            status="pending",
            reason_code=reason_code,
            reason_note=reason_note,
            evidence_snapshot=dict(evidence_snapshot or {}),
            metrics_snapshot=dict(metrics_snapshot or {}),
            related_artifact_ids=list(related_artifact_ids or []),
            source_job_id=source_job_id,
            created_by=created_by,
            accepted_by=None,
            accepted_at=None,
            dismissed_by=None,
            dismissed_at=None,
            decision_reason_code=None,
            decision_reason_note=None,
            action_result={},
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _validate_action(
        *,
        recommendation_type: str,
        recommended_action: str,
        artifact_id: str | None,
    ) -> None:
        if recommended_action != "none" and artifact_id is None:
            raise ValidationError("Executable skill curator recommendations require artifact_id.")
        if recommendation_type == "activate_candidate" and recommended_action != "activate_staged":
            raise ValidationError("activate_candidate recommendations must use activate_staged.")
        if recommendation_type == "promote_candidate" and recommended_action != "stabilize_active":
            raise ValidationError("promote_candidate recommendations must use stabilize_active.")
        if recommendation_type == "replace_candidate" and recommended_action != "replace_selectable":
            raise ValidationError("replace_candidate recommendations must use replace_selectable.")
        if recommendation_type == "restore_candidate" and recommended_action != "restore_suppressed":
            raise ValidationError("restore_candidate recommendations must use restore_suppressed.")
        if recommended_action == "archive_deprecated" and recommendation_type != "archive_candidate":
            raise ValidationError("archive_deprecated requires archive_candidate recommendation.")
        if recommendation_type == "archive_candidate" and recommended_action not in {"none", "archive_deprecated"}:
            raise ValidationError("archive_candidate recommendations must use archive_deprecated or none.")
        if recommendation_type in {
            "patch_needed",
            "merge_candidate",
            "patch_routing_policy",
            "patch_template_policy",
            "patch_skill_package",
            "select_replacement_skill_package",
        } and recommended_action != "none":
            raise ValidationError("Patch, merge, routing, and template recommendations are non-executable in v1.")

    def accept(
        self,
        *,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        action_result: dict[str, Any] | None = None,
    ) -> "SkillCuratorRecommendation":
        if self.status != "pending":
            raise ValidationError("Only pending skill curator recommendations can be accepted.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        now = _utcnow()
        return replace(
            self,
            status="accepted",
            accepted_by=operator_id,
            accepted_at=now,
            decision_reason_code=reason_code,
            decision_reason_note=reason_note,
            action_result=dict(action_result or {}),
            updated_at=now,
        )

    def dismiss(
        self,
        *,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> "SkillCuratorRecommendation":
        if self.status != "pending":
            raise ValidationError("Only pending skill curator recommendations can be dismissed.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        now = _utcnow()
        return replace(
            self,
            status="dismissed",
            dismissed_by=operator_id,
            dismissed_at=now,
            decision_reason_code=reason_code,
            decision_reason_note=reason_note,
            updated_at=now,
        )
