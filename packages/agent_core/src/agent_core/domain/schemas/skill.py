from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field


SKILL_DEACTIVATION_REASON_CODES = (
    "rollout_rollback",
    "quality_regression",
    "safety_risk",
    "superseded",
    "operator_request",
)
SkillDeactivationReasonCode = Literal[
    "rollout_rollback",
    "quality_regression",
    "safety_risk",
    "superseded",
    "operator_request",
]
SkillSuppressionReasonCode = Literal[
    "safety_risk",
    "quality_regression",
    "policy_violation",
    "operator_request",
]
SkillRestoreReasonCode = Literal[
    "operator_restore",
    "risk_mitigated",
    "false_positive",
]
SkillArchiveReasonCode = Literal[
    "stale_deprecated",
    "operator_request",
    "cleanup",
]
SkillCuratorRecommendationType = Literal[
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
]
SkillCuratorRecommendedAction = Literal[
    "none",
    "activate_staged",
    "stabilize_active",
    "suppress_selectable",
    "deactivate_active",
    "restore_suppressed",
    "replace_selectable",
    "archive_deprecated",
]
SkillCuratorRecommendationStatus = Literal[
    "pending",
    "accepted",
    "dismissed",
    "superseded",
]


class SkillDescriptorResponse(BaseModel):
    name: str
    description: str

    model_config = {"from_attributes": True}


class SkillArtifactResponse(BaseModel):
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
    plan_templates: list[dict[str, Any]] = Field(default_factory=list)
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

    model_config = {"from_attributes": True}


class CreateSkillCandidateFromProposalRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=36)


class StageSkillReplacementFromProposalRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=36)
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class StageSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ActivateSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class StabilizeSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class SuppressSkillArtifactRequest(BaseModel):
    reason_code: SkillSuppressionReasonCode
    reason_note: str | None = Field(default=None, max_length=2000)


class RestoreSkillArtifactRequest(BaseModel):
    reason_code: SkillRestoreReasonCode
    reason_note: str | None = Field(default=None, max_length=2000)


class ArchiveSkillArtifactRequest(BaseModel):
    reason_code: SkillArchiveReasonCode
    reason_note: str | None = Field(default=None, max_length=2000)


class ReplaceSkillArtifactRequest(BaseModel):
    reason_code: SkillDeactivationReasonCode
    reason_note: str | None = Field(default=None, max_length=2000)


class DeactivateSkillArtifactRequest(BaseModel):
    reason_code: SkillDeactivationReasonCode
    reason_note: str | None = Field(default=None, max_length=2000)


class SkillUsageEventResponse(BaseModel):
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
    metadata: dict[str, Any] = Field(validation_alias=AliasChoices("usage_metadata", "metadata"))
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillResolutionResponse(BaseModel):
    skill_name: str
    surface: str
    artifact_id: str | None
    skill_version: str | None
    artifact_status: str | None
    resolver_status: str
    selection_reason: str
    implementation_binding: str
    requested_capability: str | None = None
    selected_capability: str | None = None
    resolution_mode: str | None = None

    model_config = {"from_attributes": True}


class SkillCuratorRecommendationResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class SkillReplacementReadinessSourceAnchorResponse(BaseModel):
    source_artifact_id: str | None
    source_lineage_id: str | None
    current_source_status: str | None
    current_selectable_artifact_id: str | None
    anchor_status: str

    model_config = {"from_attributes": True}


class SkillReplacementReadinessRolloutEvidenceResponse(BaseModel):
    rollout_id: str | None
    binding_id: str | None
    latest_observation_id: str | None
    promote_observation_ids: list[str]

    model_config = {"from_attributes": True}


class SkillReplacementReadinessUsageEvidenceResponse(BaseModel):
    matched_count: int
    successful_count: int
    negative_count: int
    negative_usage_rate: float
    matched_usage_event_ids: list[str]
    successful_usage_event_ids: list[str]
    negative_usage_event_ids: list[str]

    model_config = {"from_attributes": True}


class SkillReplacementReadinessActionResponse(BaseModel):
    status: str
    reason_codes: list[str]

    model_config = {"from_attributes": True}


class SkillReplacementReadinessThresholdsResponse(BaseModel):
    promote_observation_min: int
    successful_usage_min: int
    max_negative_usage_rate: float

    model_config = {"from_attributes": True}


class SkillReplacementReadinessResponse(BaseModel):
    artifact_id: str
    skill_name: str
    scope: str
    proposal_id: str | None
    proposal_source: str | None
    recommended_action: str | None
    source_anchor: SkillReplacementReadinessSourceAnchorResponse
    rollout_evidence: SkillReplacementReadinessRolloutEvidenceResponse
    usage_evidence: SkillReplacementReadinessUsageEvidenceResponse
    activate_readiness: SkillReplacementReadinessActionResponse
    replace_readiness: SkillReplacementReadinessActionResponse
    thresholds: SkillReplacementReadinessThresholdsResponse
    checked_at: datetime

    model_config = {"from_attributes": True}


class AcceptSkillCuratorRecommendationRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class DismissSkillCuratorRecommendationRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class RuntimeBindingExplainResponse(BaseModel):
    skill_name: str
    surface: str
    source_summary: dict[str, Any]
    resolution_summary: dict[str, Any]
    binding_summary: dict[str, Any] | None
    rollout_summary: dict[str, Any] | None
    tool_plan_summary: dict[str, Any] | None
    blocked_reason_codes: list[str]
    fallback_reason_codes: list[str]
    requested_capability: str | None = None
    selected_capability: str | None = None
    resolution_mode: str | None = None
    confidence: float | None = None
    fallback_chain: list[str] | None = None
    candidate_count: int | None = None
    routing_mode: str | None = None

    model_config = {"from_attributes": True}


class ImportSkillPackageRequest(BaseModel):
    name: str
    provider: str
    version: str
    manifest: dict[str, Any]
    signature_hash: str
    signature_algorithm: str = "sha256"
    provenance_url: str | None = None
    sandbox_eval_bundle: dict[str, Any] | None = None


class RejectSkillPackageRequest(BaseModel):
    reason_code: str


class SkillPackageResponse(BaseModel):
    id: str
    name: str
    provider: str
    version: str
    provenance_url: str | None
    signature_hash: str
    signature_algorithm: str
    manifest: dict[str, Any]
    status: str
    sandbox_eval_bundle: dict[str, Any]
    kill_switch: bool
    imported_by: str
    imported_at: datetime
    verified_at: datetime | None
    rejected_at: datetime | None
    rejected_reason_code: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class InstallSkillPackageRequest(BaseModel):
    learner_profile_id: str


class SuppressInstallationRequest(BaseModel):
    reason_code: str


class TenantSkillPackageInstallationResponse(BaseModel):
    id: str
    learner_profile_id: str
    package_id: str
    status: str
    installed_by: str
    installed_at: datetime
    suppressed_at: datetime | None
    suppressed_reason_code: str | None
    suppressed_by: str | None
    uninstalled_at: datetime | None
    uninstalled_by: str | None
    rolled_back_at: datetime | None
    rolled_back_by: str | None
    rollback_source_installation_id: str | None
    created_artifact_ids: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RouterCandidateExplain(BaseModel):
    candidate_id: str
    source_type: str
    skill_name: str
    artifact_id: str | None
    artifact_status: str
    total_score: float
    sub_scores: dict[str, float]
    trust_level: int
    failure_rate: float
    rollback_pressure: float
    artifact_quality: float
    eligible: bool
    ineligible_reason_codes: list[str]
    reason_codes: list[str]


class RouterExplainResponse(BaseModel):
    request: dict[str, Any]
    bridge: dict[str, Any]
    selection: dict[str, Any] | None
    router_decision: dict[str, Any] | None


class ArtifactTimelineEvent(BaseModel):
    event_type: str
    resource_type: str
    actor: str
    event_data: dict[str, Any]
    created_at: datetime


class ArtifactTimelineResponse(BaseModel):
    artifact_id: str
    artifact_summary: dict[str, Any]
    lifecycle_events: list[ArtifactTimelineEvent]
    usage_summary: dict[str, Any]
    quality_history: list[dict[str, Any]]
    related_proposal_ids: list[str]
    suppression_history: list[dict[str, Any]]
    recommendation_history: list[dict[str, Any]]


class RolloutDrillDownResponse(BaseModel):
    rollout_id: str
    proposal_summary: dict[str, Any]
    observation_timeline: list[dict[str, Any]]
    decision_timeline: list[dict[str, Any]]
    usage_attribution: dict[str, Any]
    signal_trend: dict[str, Any]
    current_status: str
    duration_days: float


class FallbackTraceEntry(BaseModel):
    usage_event_id: str
    fallback_chain: list[str]
    confidence: float | None
    resolver_status: str
    selection_reason: str
    created_at: datetime


class FallbackTraceResponse(BaseModel):
    skill_name: str
    surface: str
    total_events: int
    fallback_history: list[FallbackTraceEntry]
    fallback_rate: float
    baseline_reliance_rate: float
    common_failure_reasons: list[dict[str, Any]]
