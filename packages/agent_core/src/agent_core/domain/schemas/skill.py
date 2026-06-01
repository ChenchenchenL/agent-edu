from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SkillDescriptorResponse(BaseModel):
    name: str
    description: str

    model_config = {"from_attributes": True}


class SkillArtifactResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class SkillUsageEventResponse(BaseModel):
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

    model_config = {"from_attributes": True}
