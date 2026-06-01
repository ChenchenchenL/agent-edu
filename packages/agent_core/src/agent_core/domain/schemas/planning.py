from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CreateStudyPlanRequest(BaseModel):
    trigger_source: str = Field(default="initial", min_length=1, max_length=64)


class PlanStageResponse(BaseModel):
    id: str
    study_plan_id: str
    position: int
    title: str
    objective: str
    focus_topics: list[str]
    start_date: date
    end_date: date

    model_config = {"from_attributes": True}


class StudyPlanResponse(BaseModel):
    id: str
    learner_goal_id: str
    version: int
    status: str
    trigger_source: str
    plan_summary: str
    blueprint_payload: dict
    materialized_until_date: date | None
    supersedes_plan_id: str | None
    created_at: datetime
    updated_at: datetime
    stages: list[PlanStageResponse] = Field(default_factory=list)


class DailyTaskResponse(BaseModel):
    id: str
    learner_goal_id: str
    study_plan_id: str
    plan_stage_id: str | None
    task_origin: str
    task_type: str
    execution_mode: str
    title: str
    instructions: str
    topic_focus: str
    difficulty: str | None
    question_count: int | None
    estimated_minutes: int
    scheduled_for: date
    due_on: date
    status: str
    source_task_id: str | None
    execution_session_id: str | None
    last_workflow_run_id: str | None
    result_note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExecuteDailyTaskResponse(BaseModel):
    task: DailyTaskResponse
    workflow_run_id: str
    execution_session_id: str
    reused_existing_execution: bool


class UpdateDailyTaskStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)
    result_note: str | None = Field(default=None, max_length=2000)


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_type: str
    status: str
    trigger_source: str
    learner_goal_id: str | None
    study_plan_id: str | None
    daily_task_id: str | None
    result_resource_type: str | None
    result_resource_ids: list[str]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}
