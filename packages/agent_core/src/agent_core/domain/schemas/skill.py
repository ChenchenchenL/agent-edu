from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, Field


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

    model_config = {"from_attributes": True}


class CreateSkillCandidateFromProposalRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=36)


class StageSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ActivateSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class DeactivateSkillArtifactRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
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

    model_config = {"from_attributes": True}
