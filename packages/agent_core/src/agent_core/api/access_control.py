from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.memory import MemoryService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import LearnerGoalRepository
from agent_core.infrastructure.db.repositories import DailyTaskRepository
from agent_core.infrastructure.db.repositories import ReflectionProposalRepository
from agent_core.infrastructure.db.repositories import ReflectionRecordRepository
from agent_core.infrastructure.db.repositories import StudyPlanRepository
from agent_core.infrastructure.db.repositories import WorkflowRunRepository


@dataclass(frozen=True)
class AccessContext:
    actor_type: Literal["learner", "operator"]
    learner_profile_id: str | None
    actor_id: str | None = None


def require_profile_access(profile_id: str, context: AccessContext) -> None:
    if context.actor_type == "operator":
        return
    if context.learner_profile_id != profile_id:
        raise NotFoundError(f"Learner profile '{profile_id}' was not found.")


async def require_goal_access(
    goal_id: str,
    context: AccessContext,
    session: AsyncSession,
    *,
    expected_profile_id: str | None = None,
) -> LearnerGoal:
    goal = await LearnerGoalRepository(session).get_by_id(goal_id)
    if goal is None:
        raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
    if expected_profile_id is not None and goal.learner_profile_id != expected_profile_id:
        raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
    if context.actor_type == "learner" and context.learner_profile_id != goal.learner_profile_id:
        raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
    return goal


async def require_plan_access(plan_id: str, context: AccessContext, session: AsyncSession) -> str:
    plan = await StudyPlanRepository(session).get_by_id(plan_id)
    if plan is None:
        raise NotFoundError(f"Study plan '{plan_id}' was not found.")
    await require_goal_access(plan.learner_goal_id, context, session)
    return plan.learner_goal_id


async def require_task_access(task_id: str, context: AccessContext, session: AsyncSession) -> str:
    task = await DailyTaskRepository(session).get_by_id(task_id)
    if task is None:
        raise NotFoundError(f"Daily task '{task_id}' was not found.")
    await require_goal_access(task.learner_goal_id, context, session)
    return task.learner_goal_id


async def require_workflow_run_access(run_id: str, context: AccessContext, session: AsyncSession) -> str | None:
    run = await WorkflowRunRepository(session).get_by_id(run_id)
    if run is None:
        raise NotFoundError(f"Workflow run '{run_id}' was not found.")
    if run.learner_goal_id is not None:
        await require_goal_access(run.learner_goal_id, context, session)
    elif context.actor_type != "operator":
        raise NotFoundError(f"Workflow run '{run_id}' was not found.")
    return run.learner_goal_id


async def require_reflection_access(reflection_id: str, context: AccessContext, session: AsyncSession) -> str:
    reflection = await ReflectionRecordRepository(session).get_by_id(reflection_id)
    if reflection is None:
        raise NotFoundError(f"Reflection '{reflection_id}' was not found.")
    await require_goal_access(reflection.learner_goal_id, context, session)
    return reflection.learner_goal_id


async def require_reflection_proposal_access(
    proposal_id: str,
    context: AccessContext,
    session: AsyncSession,
) -> str:
    proposal = await ReflectionProposalRepository(session).get_by_id(proposal_id)
    if proposal is None:
        raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
    await require_goal_access(proposal.learner_goal_id, context, session)
    return proposal.learner_goal_id


async def require_memory_access(
    memory_type: str,
    memory_id: str,
    context: AccessContext,
    memory_service: MemoryService,
) -> KnowledgeMemory | BehaviorMemory:
    if memory_type == "knowledge":
        memory: KnowledgeMemory | BehaviorMemory = await memory_service.get_knowledge_memory(memory_id)
    elif memory_type == "behavior":
        memory = await memory_service.get_behavior_memory(memory_id)
    else:
        raise ValidationError("Unsupported memory type.")

    if context.actor_type == "learner" and context.learner_profile_id != memory.learner_profile_id:
        raise NotFoundError(f"{memory_type.capitalize()} memory '{memory_id}' was not found.")
    return memory
