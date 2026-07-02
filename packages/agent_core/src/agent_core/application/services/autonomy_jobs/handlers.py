"""Autonomy job execution handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.autonomy import ScheduledAutonomyJob

if TYPE_CHECKING:
    from agent_core.application.services.autonomy_jobs.processors import (
        AutonomyJobHandler,
        TaskJobProcessingFacade,
    )


class _ProcessorBackedHandler:
    """Handler that delegates to a processor backed by a facade."""

    def __init__(self, *, processor: object) -> None:
        self._processor = processor

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._processor.process(job)


def review_scheduling_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReviewSchedulingJobProcessor
    return _ProcessorBackedHandler(processor=ReviewSchedulingJobProcessor(facade=facade))


def replan_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReplanJobProcessor
    return _ProcessorBackedHandler(processor=ReplanJobProcessor(facade=facade))


def assessment_generation_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import AssessmentGenerationJobProcessor
    return _ProcessorBackedHandler(processor=AssessmentGenerationJobProcessor(facade=facade))


def daily_task_materialization_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import DailyTaskMaterializationJobProcessor
    return _ProcessorBackedHandler(processor=DailyTaskMaterializationJobProcessor(facade=facade))


def reflection_skill_evolution_curator_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReflectionSkillEvolutionCuratorJobProcessor
    return _ProcessorBackedHandler(processor=ReflectionSkillEvolutionCuratorJobProcessor(facade=facade))


def skill_replacement_auto_execution_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import SkillReplacementAutoExecutionJobProcessor
    return _ProcessorBackedHandler(processor=SkillReplacementAutoExecutionJobProcessor(facade=facade))


def long_term_memory_replay_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import LongTermMemoryMaterializationReplayJobProcessor
    return _ProcessorBackedHandler(processor=LongTermMemoryMaterializationReplayJobProcessor(facade=facade))


def reflection_proposal_evaluation_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReflectionProposalEvaluationJobProcessor
    return _ProcessorBackedHandler(processor=ReflectionProposalEvaluationJobProcessor(facade=facade))


def reflection_proposal_rollout_observation_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReflectionProposalRolloutObservationJobProcessor
    return _ProcessorBackedHandler(processor=ReflectionProposalRolloutObservationJobProcessor(facade=facade))


def reflection_proposal_rollout_decision_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReflectionProposalRolloutDecisionJobProcessor
    return _ProcessorBackedHandler(processor=ReflectionProposalRolloutDecisionJobProcessor(facade=facade))


def plan_extension_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import PlanExtensionJobProcessor
    return _ProcessorBackedHandler(processor=PlanExtensionJobProcessor(facade=facade))


def milestone_generation_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import MilestoneGenerationJobProcessor
    return _ProcessorBackedHandler(processor=MilestoneGenerationJobProcessor(facade=facade))


def mastery_refresh_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import MasteryRefreshJobProcessor
    return _ProcessorBackedHandler(processor=MasteryRefreshJobProcessor(facade=facade))


def periodic_goal_reflection_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import PeriodicGoalReflectionJobProcessor
    return _ProcessorBackedHandler(processor=PeriodicGoalReflectionJobProcessor(facade=facade))


def reflection_outcome_evaluation_handler(facade: TaskJobProcessingFacade) -> _ProcessorBackedHandler:
    from agent_core.application.services.autonomy_jobs.processors import ReflectionOutcomeEvaluationJobProcessor
    return _ProcessorBackedHandler(processor=ReflectionOutcomeEvaluationJobProcessor(facade=facade))
