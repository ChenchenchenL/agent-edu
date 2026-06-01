from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from agent_core.domain.schemas.autonomy import GoalAutonomyStateResponse
from agent_core.domain.schemas.autonomy import ScheduledAutonomyJobResponse
from agent_core.domain.schemas.goal import LearnerGoalResponse, LearnerProfileResponse
from agent_core.domain.schemas.memory import (
    BehaviorMemoryBrowseItemResponse,
    KnowledgeMemoryBrowseItemResponse,
)
from agent_core.domain.schemas.planning import DailyTaskResponse, StudyPlanResponse, WorkflowRunResponse
from agent_core.domain.schemas.session import SessionResponse


class WorkspaceMemorySummaryResponse(BaseModel):
    knowledge_items: list[KnowledgeMemoryBrowseItemResponse]
    behavior_items: list[BehaviorMemoryBrowseItemResponse]
    knowledge_count: int
    behavior_count: int


class WorkspaceSummaryResponse(BaseModel):
    learner_profile: LearnerProfileResponse
    learner_goal: LearnerGoalResponse | None
    active_plan: StudyPlanResponse | None
    today_tasks: list[DailyTaskResponse]
    review_tasks: list[DailyTaskResponse]
    milestone_tasks: list[DailyTaskResponse]
    recent_workflow_runs: list[WorkflowRunResponse]
    recent_sessions: list[SessionResponse]
    autonomy_state: GoalAutonomyStateResponse | None
    autonomy_jobs: list[ScheduledAutonomyJobResponse]
    memory_summary: WorkspaceMemorySummaryResponse
    generated_at: datetime
