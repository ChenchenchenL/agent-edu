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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
        if recommendation_type in {"patch_needed", "merge_candidate"} and recommended_action != "none":
            raise ValidationError("Patch and merge recommendations are non-executable in v1.")

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
