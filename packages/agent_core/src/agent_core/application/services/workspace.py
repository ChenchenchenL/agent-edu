from __future__ import annotations

from datetime import date, datetime, timezone

from agent_core.application.services.memory import MemoryService
from agent_core.application.services.task_autonomy_scheduling import TaskAutonomySchedulingService
from agent_core.application.services.task_plan_lifecycle import TaskPlanLifecycleService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import StudyPlan
from agent_core.domain.errors import NotFoundError
from agent_core.domain.schemas.autonomy import GoalAutonomyStateResponse
from agent_core.domain.schemas.autonomy import ScheduledAutonomyJobResponse
from agent_core.domain.schemas.goal import LearnerGoalResponse, LearnerProfileResponse
from agent_core.domain.schemas.memory import (
    BehaviorMemoryBrowseItemResponse,
    KnowledgeMemoryBrowseItemResponse,
)
from agent_core.domain.schemas.planning import DailyTaskResponse, StudyPlanResponse, WorkflowRunResponse
from agent_core.domain.schemas.session import SessionResponse
from agent_core.domain.schemas.workspace import WorkspaceMemorySummaryResponse, WorkspaceSummaryResponse
from agent_core.infrastructure.db.repositories import (
    GoalAutonomyStateRepository,
    LearnerGoalRepository,
    LearnerProfileRepository,
    SessionRepository,
    StudyPlanRepository,
    WorkflowRunRepository,
)


class WorkspaceService:
    def __init__(
        self,
        *,
        learner_profile_repository: LearnerProfileRepository,
        learner_goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        session_repository: SessionRepository,
        workflow_run_repository: WorkflowRunRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository,
        task_plan_lifecycle_service: TaskPlanLifecycleService,
        task_autonomy_scheduling_service: TaskAutonomySchedulingService,
        memory_service: MemoryService,
    ) -> None:
        self._learner_profile_repository = learner_profile_repository
        self._learner_goal_repository = learner_goal_repository
        self._study_plan_repository = study_plan_repository
        self._session_repository = session_repository
        self._workflow_run_repository = workflow_run_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._task_plan_lifecycle_service = task_plan_lifecycle_service
        self._task_autonomy_scheduling_service = task_autonomy_scheduling_service
        self._memory_service = memory_service

    async def get_workspace_summary(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
    ) -> WorkspaceSummaryResponse:
        profile = await self._learner_profile_repository.get_by_id(learner_profile_id)
        if profile is None:
            raise NotFoundError(f"Learner profile '{learner_profile_id}' was not found.")

        goal = await self._resolve_goal(learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id)
        if goal is None:
            return WorkspaceSummaryResponse(
                learner_profile=LearnerProfileResponse.model_validate(profile),
                learner_goal=None,
                active_plan=None,
                today_tasks=[],
                review_tasks=[],
                milestone_tasks=[],
                recent_workflow_runs=[],
                recent_sessions=[],
                autonomy_state=None,
                autonomy_jobs=[],
                memory_summary=WorkspaceMemorySummaryResponse(
                    knowledge_items=[],
                    behavior_items=[],
                    knowledge_count=0,
                    behavior_count=0,
                ),
                generated_at=datetime.now(timezone.utc),
            )

        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        today = date.today()
        today_tasks = await self._task_plan_lifecycle_service.list_tasks(
            goal.id,
            statuses={"pending", "in_progress"},
            scheduled_to=today,
        )
        review_tasks = await self._task_plan_lifecycle_service.list_tasks(
            goal.id,
            statuses={"pending", "in_progress"},
            task_type="review",
        )
        milestone_tasks = await self._task_plan_lifecycle_service.list_tasks(
            goal.id,
            statuses={"pending", "in_progress"},
            task_type="milestone",
        )
        workflow_runs = [
            WorkflowRunResponse.model_validate(item)
            for item in await self._workflow_run_repository.list_recent_by_goal(goal.id, limit=5)
        ]
        recent_sessions = [
            SessionResponse.model_validate(item)
            for item in await self._session_repository.list_by_goal(goal.id, limit=5)
        ]
        autonomy_state = await self._goal_autonomy_state_repository.get_by_goal(goal.id)
        autonomy_jobs = [
            ScheduledAutonomyJobResponse.model_validate(item)
            for item in await self._task_autonomy_scheduling_service.list_autonomy_jobs(goal.id)
        ]
        knowledge_memories = await self._memory_service.browse_knowledge_memories(
            learner_profile_id=learner_profile_id,
            learner_goal_id=goal.id,
            statuses={"candidate", "active", "stable"},
            limit=5,
            offset=0,
        )
        behavior_memories = await self._memory_service.browse_behavior_memories(
            learner_profile_id=learner_profile_id,
            learner_goal_id=goal.id,
            statuses={"candidate", "active", "stable"},
            limit=5,
            offset=0,
        )
        knowledge_items = [
            KnowledgeMemoryBrowseItemResponse.model_validate(await self._memory_service.describe_knowledge_memory(item))
            for item in knowledge_memories.items
        ]
        behavior_items = [
            BehaviorMemoryBrowseItemResponse.model_validate(await self._memory_service.describe_behavior_memory(item))
            for item in behavior_memories.items
        ]
        return WorkspaceSummaryResponse(
            learner_profile=LearnerProfileResponse.model_validate(profile),
            learner_goal=LearnerGoalResponse.model_validate(goal),
            active_plan=await self._to_plan_response(active_plan),
            today_tasks=today_tasks,
            review_tasks=review_tasks[:5],
            milestone_tasks=milestone_tasks[:5],
            recent_workflow_runs=workflow_runs,
            recent_sessions=recent_sessions,
            autonomy_state=(
                GoalAutonomyStateResponse.model_validate(autonomy_state) if autonomy_state is not None else None
            ),
            autonomy_jobs=autonomy_jobs[:5],
            memory_summary=WorkspaceMemorySummaryResponse(
                knowledge_items=knowledge_items,
                behavior_items=behavior_items,
                knowledge_count=knowledge_memories.total,
                behavior_count=behavior_memories.total,
            ),
            generated_at=datetime.now(timezone.utc),
        )

    async def _resolve_goal(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
    ) -> LearnerGoal | None:
        if learner_goal_id is not None:
            goal = await self._learner_goal_repository.get_by_id(learner_goal_id)
            if goal is None or goal.learner_profile_id != learner_profile_id:
                raise NotFoundError(f"Learner goal '{learner_goal_id}' was not found.")
            return goal
        goals = await self._learner_goal_repository.list_by_profile(learner_profile_id)
        if not goals:
            return None
        for item in goals:
            if item.status == "active":
                return item
        return goals[0]

    async def _to_plan_response(self, active_plan: StudyPlan | None) -> StudyPlanResponse | None:
        if active_plan is None:
            return None
        return await self._task_plan_lifecycle_service.get_plan(active_plan.id)
