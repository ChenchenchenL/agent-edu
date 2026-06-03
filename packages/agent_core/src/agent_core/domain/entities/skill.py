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

    def mark_deprecated(self) -> "SkillArtifact":
        if self.status != "active":
            raise ValidationError("Only active skill artifacts can be deprecated.")
        return replace(self, status="deprecated", updated_at=_utcnow())


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
