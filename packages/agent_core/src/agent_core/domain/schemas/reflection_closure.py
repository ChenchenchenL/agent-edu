from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ReflectionProposalResponse(BaseModel):
    id: str
    reflection_record_id: str
    learner_goal_id: str
    proposal_type: str
    target_scope: str
    status: str
    priority_score: float
    hypothesis: str
    change_summary: str
    structured_patch_payload: dict
    expected_improvement: str
    risk_level: str
    evidence_snapshot: dict
    auto_sandbox_eligible: bool = False
    admission_mode: str = "manual"
    rollout_eligible: bool = False
    activation_surface: str | None = None
    evaluation_status: str
    evaluation_summary: str | None
    latest_sandbox_run_id: str | None
    approved_at: datetime | None
    approved_by: str | None
    approval_reason_code: str | None
    approval_note: str | None
    proposal_bundle_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalEvaluationResponse(BaseModel):
    id: str
    proposal_id: str
    evaluation_status: str
    comparison_window_size: int
    baseline_policy_snapshot: dict
    candidate_policy_snapshot: dict
    simulated_outcome_summary: dict
    score_delta: float
    evaluator_type: str
    sandbox_run_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalQueueItemResponse(BaseModel):
    id: str
    reflection_record_id: str
    learner_goal_id: str
    proposal_type: str
    target_scope: str
    status: str
    priority_score: float
    risk_level: str
    auto_sandbox_eligible: bool = False
    admission_mode: str = "manual"
    rollout_eligible: bool = False
    activation_surface: str | None = None
    evaluation_status: str
    change_summary: str
    latest_sandbox_run_id: str | None
    proposal_bundle_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalQueueResponse(BaseModel):
    items: list[ReflectionProposalQueueItemResponse]
    total: int
    limit: int
    offset: int


class ReflectionProposalSandboxRunResponse(BaseModel):
    id: str
    proposal_id: str
    learner_goal_id: str
    status: str
    sample_source_type: str
    sample_count: int
    provider: str | None
    model: str | None
    evaluator_type: str
    baseline_snapshot: dict
    candidate_snapshot: dict
    result_summary: dict
    score_delta: float
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalApprovalDecisionResponse(BaseModel):
    id: str
    proposal_id: str
    decision_type: str
    previous_status: str
    new_status: str
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalRolloutResponse(BaseModel):
    id: str
    proposal_id: str
    learner_goal_id: str
    surface: str
    status: str
    baseline_snapshot: dict
    runtime_overlay_payload: dict
    latest_observation_id: str | None
    staged_plan_id: str | None
    rollback_restored_plan_id: str | None
    activated_by: str
    activated_at: datetime
    promoted_at: datetime | None
    rolled_back_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalRolloutObservationResponse(BaseModel):
    id: str
    rollout_id: str
    proposal_id: str
    learner_goal_id: str
    surface: str
    recommendation: str
    observed_sample_count: int
    positive_score: float
    negative_score: float
    signal_summary: dict
    reason_codes: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectionProposalRolloutDecisionResponse(BaseModel):
    id: str
    rollout_id: str
    proposal_id: str
    decision_type: str
    previous_status: str
    new_status: str
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GoalSkillBindingResponse(BaseModel):
    id: str
    proposal_id: str
    rollout_id: str
    learner_goal_id: str
    surface: str
    status: str
    priority_score: float
    match_rules: dict
    runtime_directives: dict
    tool_plan: list[dict]
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    rolled_back_at: datetime | None

    model_config = {"from_attributes": True}


class ReviewReflectionProposalRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class EnqueueReflectionProposalSandboxRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ApproveReflectionProposalRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class RejectReflectionProposalRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ActivateReflectionProposalRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class PromoteReflectionProposalRolloutRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class RollbackReflectionProposalRolloutRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)


class ObserveReflectionProposalRolloutRequest(BaseModel):
    reason_code: str = Field(default="manual_observe", min_length=1, max_length=128)
    reason_note: str | None = Field(default=None, max_length=2000)
