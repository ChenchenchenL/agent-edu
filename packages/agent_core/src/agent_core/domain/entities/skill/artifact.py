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
class SkillArtifact:
    id: str
    name: str
    version: str
    lineage_id: str
    parent_artifact_id: str | None
    supersedes_artifact_id: str | None
    skill_type: str
    scope: str
    status: str
    description: str
    definition: dict[str, Any]
    runtime_directives: dict[str, Any]
    tool_plan: list[dict[str, Any]]
    compatibility_contract: dict[str, Any]
    source_reflection_ids: list[str]
    source_memory_ids: list[str]
    source_proposal_id: str | None
    quality_score: float
    created_by: str
    approved_by: str | None
    approved_at: datetime | None
    deprecated_by: str | None
    deprecated_at: datetime | None
    suppressed_reason_code: str | None
    suppressed_reason_note: str | None
    suppressed_by: str | None
    suppressed_at: datetime | None
    suppressed_previous_status: str | None
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
        lineage_id: str | None = None,
        parent_artifact_id: str | None = None,
        supersedes_artifact_id: str | None = None,
        definition: dict[str, Any] | None = None,
        runtime_directives: dict[str, Any] | None = None,
        tool_plan: list[dict[str, Any]] | None = None,
        compatibility_contract: dict[str, Any] | None = None,
        source_reflection_ids: list[str] | None = None,
        source_memory_ids: list[str] | None = None,
        source_proposal_id: str | None = None,
        quality_score: float = 0.0,
        created_by: str = "system",
        approved_by: str | None = None,
        approved_at: datetime | None = None,
        deprecated_by: str | None = None,
        deprecated_at: datetime | None = None,
        suppressed_reason_code: str | None = None,
        suppressed_reason_note: str | None = None,
        suppressed_by: str | None = None,
        suppressed_at: datetime | None = None,
        suppressed_previous_status: str | None = None,
    ) -> "SkillArtifact":
        if not name.strip():
            raise ValidationError("skill artifact name is required.")
        if not version.strip():
            raise ValidationError("skill artifact version is required.")
        if skill_type not in SKILL_TYPES:
            raise ValidationError("Unsupported skill artifact type.")
        if scope not in SKILL_SCOPES:
            raise ValidationError("Unsupported skill artifact scope.")
        if status not in SKILL_ARTIFACT_STATUSES:
            raise ValidationError("Unsupported skill artifact status.")
        _validate_score("quality_score", quality_score)
        normalized_contract = cls._normalize_contract(
            compatibility_contract=compatibility_contract,
            scope=scope,
            implementation_binding=name,
        )
        now = _utcnow()
        artifact_id = str(uuid4())
        return cls(
            id=artifact_id,
            name=name,
            version=version,
            lineage_id=lineage_id or artifact_id,
            parent_artifact_id=parent_artifact_id,
            supersedes_artifact_id=supersedes_artifact_id,
            skill_type=skill_type,
            scope=scope,
            status=status,
            description=description,
            definition=dict(definition or {}),
            runtime_directives=dict(runtime_directives or {}),
            tool_plan=[dict(item) for item in tool_plan or []],
            compatibility_contract=normalized_contract,
            source_reflection_ids=list(source_reflection_ids or []),
            source_memory_ids=list(source_memory_ids or []),
            source_proposal_id=source_proposal_id,
            quality_score=quality_score,
            created_by=created_by,
            approved_by=approved_by,
            approved_at=approved_at,
            deprecated_by=deprecated_by,
            deprecated_at=deprecated_at,
            suppressed_reason_code=suppressed_reason_code,
            suppressed_reason_note=suppressed_reason_note,
            suppressed_by=suppressed_by,
            suppressed_at=suppressed_at,
            suppressed_previous_status=suppressed_previous_status,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _normalize_contract(
        *,
        compatibility_contract: dict[str, Any] | None,
        scope: str,
        implementation_binding: str,
    ) -> dict[str, Any]:
        contract = dict(compatibility_contract or {})
        surfaces = contract.get("surfaces")
        if surfaces is None:
            contract["surfaces"] = [scope]
        elif not isinstance(surfaces, list) or not all(isinstance(item, str) for item in surfaces):
            raise ValidationError("compatibility_contract.surfaces must be a list of strings.")
        if not contract["surfaces"]:
            raise ValidationError("compatibility_contract.surfaces cannot be empty.")
        if any(surface not in SKILL_USAGE_SURFACES for surface in contract["surfaces"]):
            raise ValidationError("compatibility_contract contains unsupported surface.")
        if contract["surfaces"] != [scope]:
            raise ValidationError("In V2, artifact surfaces must exactly match artifact scope.")
        binding = contract.get("implementation_binding")
        if binding is None:
            contract["implementation_binding"] = implementation_binding
        elif not isinstance(binding, str) or not binding.strip():
            raise ValidationError("compatibility_contract.implementation_binding must be a non-empty string.")
        contract.setdefault("input_schema_version", "1.0")
        contract.setdefault("output_schema_version", "1.0")
        if "dynamic_execution" in contract and contract["dynamic_execution"] is not False:
            raise ValidationError("compatibility_contract.dynamic_execution must be false.")
        contract["dynamic_execution"] = False
        return contract

    def mark_staged(self) -> "SkillArtifact":
        if self.status != "candidate":
            raise ValidationError("Only candidate skill artifacts can be staged.")
        return replace(self, status="staged", updated_at=_utcnow())

    def mark_active(self, *, operator_id: str) -> "SkillArtifact":
        if self.status != "staged":
            raise ValidationError("Only staged skill artifacts can be activated.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(
            self,
            status="active",
            approved_by=operator_id,
            approved_at=now,
            updated_at=now,
        )

    def mark_replacement_active(self, *, operator_id: str, superseded_artifact: "SkillArtifact") -> "SkillArtifact":
        if self.status != "staged":
            raise ValidationError("Only staged skill artifacts can replace a selectable artifact.")
        if superseded_artifact.status not in {"active", "stable"}:
            raise ValidationError("Only active or stable skill artifacts can be superseded.")
        if self.id == superseded_artifact.id:
            raise ValidationError("A skill artifact cannot replace itself.")
        if self.name != superseded_artifact.name or self.scope != superseded_artifact.scope:
            raise ValidationError("Replacement skill artifact must match superseded name and scope.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(
            self,
            lineage_id=superseded_artifact.lineage_id,
            parent_artifact_id=superseded_artifact.id,
            supersedes_artifact_id=superseded_artifact.id,
            status="active",
            approved_by=operator_id,
            approved_at=now,
            updated_at=now,
        )

    def mark_stable(self, *, operator_id: str) -> "SkillArtifact":
        if self.status != "active":
            raise ValidationError("Only active skill artifacts can be stabilized.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(
            self,
            status="stable",
            approved_by=operator_id,
            approved_at=now,
            updated_at=now,
        )

    def mark_deprecated(self, *, operator_id: str) -> "SkillArtifact":
        """Deprecate a production artifact.

        Business policy allows active, stable, and suppressed production
        artifacts to be deprecated, but candidate and staged artifacts must use
        their own lifecycle paths.
        """
        if self.status not in {"active", "stable", "suppressed"}:
            raise ValidationError("Only active, stable, or suppressed skill artifacts can be deprecated.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(
            self,
            status="deprecated",
            deprecated_by=operator_id,
            deprecated_at=now,
            suppressed_reason_code=None,
            suppressed_reason_note=None,
            suppressed_by=None,
            suppressed_at=None,
            suppressed_previous_status=None,
            updated_at=now,
        )

    def mark_suppressed(
        self,
        *,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> "SkillArtifact":
        if self.status not in {"active", "stable"}:
            raise ValidationError("Only active or stable skill artifacts can be suppressed.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        now = _utcnow()
        return replace(
            self,
            status="suppressed",
            suppressed_reason_code=reason_code,
            suppressed_reason_note=reason_note,
            suppressed_by=operator_id,
            suppressed_at=now,
            suppressed_previous_status=self.status,
            updated_at=now,
        )

    def restore_suppressed(self, *, operator_id: str) -> "SkillArtifact":
        if self.status != "suppressed":
            raise ValidationError("Only suppressed skill artifacts can be restored.")
        if self.suppressed_previous_status not in {"active", "stable"}:
            raise ValidationError("Suppressed skill artifact is missing a restorable previous status.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(
            self,
            status=self.suppressed_previous_status,
            suppressed_reason_code=None,
            suppressed_reason_note=None,
            suppressed_by=None,
            suppressed_at=None,
            suppressed_previous_status=None,
            updated_at=now,
        )

    def mark_archived(self, *, operator_id: str) -> "SkillArtifact":
        if self.status != "deprecated":
            raise ValidationError("Only deprecated skill artifacts can be archived.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        return replace(self, status="archived", updated_at=_utcnow())
