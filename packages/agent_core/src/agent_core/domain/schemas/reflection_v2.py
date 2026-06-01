from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReflectionEvidenceSignalResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str
    session_id: str | None
    daily_task_id: str | None
    workflow_run_id: str | None
    source_type: str
    signal_code: str
    topic_key: str | None
    severity_score: float
    confidence_score: float
    payload: dict
    observed_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectionOutcomeEvaluationResponse(BaseModel):
    id: str
    reflection_record_id: str
    learner_goal_id: str
    topic_key: str | None
    evaluation_status: str
    window_size: int
    observed_attempt_count: int
    baseline_snapshot: dict
    outcome_snapshot: dict
    improvement_score: float
    evaluation_note: str
    evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionReviewDecisionResponse(BaseModel):
    id: str
    reflection_record_id: str
    decision_type: str
    previous_status: str | None
    new_status: str | None
    previous_root_cause: str | None
    new_root_cause: str | None
    previous_action_payload: dict | None
    new_action_payload: dict | None
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LearnerGoalStrategyCardResponse(BaseModel):
    id: str
    learner_goal_id: str
    version: int
    status: str
    source_reflection_ids: list[str]
    primary_instruction_mode: str
    difficulty_bias: str
    review_bias: str
    replan_bias: str
    assessment_bias: str
    intervention_policy: dict
    rationale: str
    confidence_score: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectiveMemoryResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    reflection_record_id: str
    memory_key: str
    title: str
    summary: str
    details: str
    memory_level: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    evidence_count: int
    status: str
    source_reflection_ids: list[str]
    source_action_ids: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectiveMemorySummaryResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    memory_key: str
    title: str
    summary: str
    memory_level: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    evidence_count: int
    status: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionReviewQueueItemResponse(BaseModel):
    reflection_id: str
    learner_goal_id: str
    learner_profile_id: str
    status: str
    scope: str
    trigger_source: str
    primary_root_cause: str
    severity: str
    confidence_score: float
    priority_score: float
    duplicate_count: int
    summary: str
    created_at: datetime
    last_duplicate_at: datetime | None


class ReflectionReviewQueueResponse(BaseModel):
    items: list[ReflectionReviewQueueItemResponse]
    total: int
    limit: int
    offset: int


class ReviewReflectionRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ResolveReflectionRequest(BaseModel):
    new_status: str = Field(min_length=1, max_length=32)
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class OverrideReflectionRootCauseRequest(BaseModel):
    new_root_cause: str = Field(min_length=1, max_length=64)
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class OverrideReflectionActionRequest(BaseModel):
    action_type: str = Field(min_length=1, max_length=64)
    payload: dict
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)
