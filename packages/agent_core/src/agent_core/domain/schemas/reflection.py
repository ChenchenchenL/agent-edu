from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ReflectionActionResponse(BaseModel):
    id: str
    reflection_record_id: str
    action_type: str
    risk_level: str
    status: str
    approval_required: bool
    payload: dict
    execution_result: dict
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None

    model_config = {"from_attributes": True}


class ReflectionRecordListItemResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str
    daily_task_id: str | None
    workflow_run_id: str | None
    study_plan_id: str | None
    scope: str
    target_type: str
    target_id: str
    trigger_source: str
    status: str
    reflection_depth: int
    aggregation_key: str
    duplicate_count: int
    priority_score: float
    last_duplicate_at: datetime | None
    primary_root_cause: str
    secondary_root_causes: list[str]
    severity: str
    confidence_score: float
    verdict_code: str
    verdict_confidence: float
    summary: str
    recommended_next_step: str
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


class ReflectionRecordDetailResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str
    daily_task_id: str | None
    workflow_run_id: str | None
    study_plan_id: str | None
    scope: str
    target_type: str
    target_id: str
    trigger_source: str
    status: str
    reflection_depth: int
    dedupe_key: str
    aggregation_key: str
    duplicate_count: int
    priority_score: float
    last_duplicate_at: datetime | None
    cooldown_until: datetime | None
    primary_root_cause: str
    secondary_root_causes: list[str]
    severity: str
    confidence_score: float
    verdict_code: str
    verdict_confidence: float
    summary: str
    evidence_summary: str
    recommended_next_step: str
    evidence_payload: dict
    evidence_breakdown: dict
    memory_implications: list[dict]
    strategy_implications: dict
    session_signal_summary: dict
    llm_provider: str | None
    llm_model: str | None
    llm_latency_ms: int | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None
    actions: list[ReflectionActionResponse]
    routing_evidence: dict | None = None
    template_evidence: dict | None = None
    governance_evidence: dict | None = None

    model_config = {"from_attributes": True}


class ReflectionListResponse(BaseModel):
    items: list[ReflectionRecordListItemResponse]
    total: int
    limit: int
    offset: int
