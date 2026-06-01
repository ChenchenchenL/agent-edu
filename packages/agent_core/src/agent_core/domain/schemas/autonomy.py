from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class UpdateLearnerAvailabilityRequest(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    available_days: list[str] = Field(default_factory=list)
    time_windows: list[dict[str, str]] = Field(default_factory=list)
    max_daily_minutes: int | None = Field(default=None, ge=1, le=1440)
    preferred_session_length_minutes: int | None = Field(default=None, ge=1, le=480)


class LearnerAvailabilityResponse(BaseModel):
    id: str
    learner_goal_id: str
    timezone: str | None
    available_days: list[str]
    time_windows: list[dict[str, str]]
    max_daily_minutes: int | None
    preferred_session_length_minutes: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LearnerTopicMasteryResponse(BaseModel):
    id: str
    learner_goal_id: str
    topic_key: str
    mastery_score: float
    confidence: float
    evidence_count: int
    last_attempt_status: str | None
    last_assessed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoalAutonomyStateResponse(BaseModel):
    id: str
    learner_goal_id: str
    phase: str
    current_plan_id: str | None
    next_due_at: datetime | None
    availability_snapshot: dict
    mastery_snapshot: dict
    last_transition_reason: str | None
    last_transition_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduledAutonomyJobResponse(BaseModel):
    id: str
    learner_goal_id: str
    job_type: str
    status: str
    trigger_source: str
    due_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    idempotency_key: str
    payload: dict
    workflow_run_id: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ManualReplanRequest(BaseModel):
    trigger_source: str = Field(default="manual_replan", min_length=1, max_length=64)
    mode: str = Field(default="partial", min_length=1, max_length=16)
    source_task_id: str | None = Field(default=None, max_length=36)


class PauseAutonomyRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
