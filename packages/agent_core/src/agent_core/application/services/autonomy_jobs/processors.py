"""Autonomy job processors.

Each processor handles a specific autonomy job type.  Processors depend
on a :class:`TaskJobProcessingFacade` protocol rather than on
``AutonomousTaskService`` directly, which breaks the legacy private-
method dependency that the old handler layer had.
"""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.entities.autonomy import ScheduledAutonomyJob


class TaskJobProcessingFacade(Protocol):
    """Public interface for autonomy job processing.

    Implemented by ``AutonomousTaskService``.  Processors depend on this
    protocol instead of the concrete class so that handlers are decoupled
    from the legacy core.
    """

    async def process_long_term_memory_materialization_replay_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_review_scheduling_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_reflection_proposal_evaluation_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_reflection_skill_evolution_curator_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_skill_replacement_auto_execution_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_reflection_proposal_rollout_observation_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_reflection_proposal_rollout_decision_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_plan_extension_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_replan_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_assessment_generation_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_daily_task_materialization_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_milestone_generation_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_mastery_refresh_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_periodic_goal_reflection_job(self, job: ScheduledAutonomyJob) -> str | None: ...
    async def process_reflection_outcome_evaluation_job(self, job: ScheduledAutonomyJob) -> str | None: ...


class AutonomyJobHandler:
    """Protocol for autonomy job handlers."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        """Execute the job and return the workflow run id or None."""
        ...


class _BaseProcessor:
    def __init__(self, *, facade: TaskJobProcessingFacade) -> None:
        self._facade = facade


class LongTermMemoryMaterializationReplayJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_long_term_memory_materialization_replay_job(job)


class ReviewSchedulingJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_review_scheduling_job(job)


class ReplanJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_replan_job(job)


class AssessmentGenerationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_assessment_generation_job(job)


class DailyTaskMaterializationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_daily_task_materialization_job(job)


class ReflectionSkillEvolutionCuratorJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_reflection_skill_evolution_curator_job(job)


class SkillReplacementAutoExecutionJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_skill_replacement_auto_execution_job(job)


class ReflectionProposalEvaluationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_reflection_proposal_evaluation_job(job)


class ReflectionProposalRolloutObservationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_reflection_proposal_rollout_observation_job(job)


class ReflectionProposalRolloutDecisionJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_reflection_proposal_rollout_decision_job(job)


class PlanExtensionJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_plan_extension_job(job)


class MilestoneGenerationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_milestone_generation_job(job)


class MasteryRefreshJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_mastery_refresh_job(job)


class PeriodicGoalReflectionJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_periodic_goal_reflection_job(job)


class ReflectionOutcomeEvaluationJobProcessor(_BaseProcessor):
    async def process(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._facade.process_reflection_outcome_evaluation_job(job)
