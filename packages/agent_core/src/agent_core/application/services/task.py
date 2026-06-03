from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.chat import ChatService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding, GoalSkillBindingResolver
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE,
    LongTermMemoryMaterializationReplayExecutor,
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryReplayScheduleResult,
    long_term_memory_replay_backoff,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.quiz import QuizService
from agent_core.application.services.reflective_memory import ReflectiveMemoryService
from agent_core.application.services.reflection import ReflectionService, ReflectionTriggerRequest
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_proposal_rollouts import ReflectionProposalRolloutService
from agent_core.application.services.reflection_proposal_sandbox import ReflectionProposalSandboxService
from agent_core.application.services.session import SessionService
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.application.tools.registry import InternalToolRegistry
from agent_core.application.tools.registry import ToolExecutionRequest, ToolSpec
from agent_core.domain.entities.autonomy import (
    AUTONOMY_JOB_TYPES,
    AUTONOMY_REPLAN_MODES,
    GoalAutonomyState,
    LearnerAvailability,
    LearnerTopicMastery,
    ScheduledAutonomyJob,
    TaskAttempt,
    _UNSET as AUTONOMY_UNSET,
)
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import DailyTask, StudyPlan
from agent_core.domain.entities.skill import SkillResolution
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.planning import (
    DailyTaskResponse,
    ExecuteDailyTaskResponse,
    StudyPlanResponse,
    UpdateDailyTaskStatusRequest,
    WorkflowRunResponse,
)
from agent_core.domain.schemas.autonomy import (
    GoalAutonomyStateResponse,
    LearnerAvailabilityResponse,
    LearnerTopicMasteryResponse,
    ManualReplanRequest,
    UpdateLearnerAvailabilityRequest,
)
from agent_core.domain.schemas.quiz import GenerateQuizRequest
from agent_core.domain.schemas.session import CreateSessionRequest, MessageRequest
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerTopicMasteryRepository,
    PlanStageRepository,
    ScheduledAutonomyJobRepository,
    StudyPlanRepository,
    TaskAttemptRepository,
    WorkflowRunRepository,
)
from agent_core.infrastructure.observability.metrics import (
    observe_daily_task_status_transition,
    observe_long_term_memory_materialization,
)


class AutonomousTaskService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        plan_stage_repository: PlanStageRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None = None,
        autonomy_job_repository: ScheduledAutonomyJobRepository | None = None,
        learner_availability_repository: LearnerAvailabilityRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        task_attempt_repository: TaskAttemptRepository | None = None,
        planner_service: PlannerService,
        workflow_run_service: WorkflowRunService,
        session_service: SessionService,
        chat_service: ChatService,
        quiz_service: QuizService,
        autonomy_job_service: AutonomyJobService | None = None,
        reflection_service: ReflectionService | None = None,
        reflection_evidence_service: ReflectionEvidenceService | None = None,
        reflection_outcome_service: ReflectionOutcomeService | None = None,
        reflection_proposal_sandbox_service: ReflectionProposalSandboxService | None = None,
        reflection_proposal_rollout_service: ReflectionProposalRolloutService | None = None,
        rollout_resolver: ReflectionProposalRolloutResolver | None = None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
        strategy_card_service: StrategyCardService | None = None,
        reflective_memory_service: ReflectiveMemoryService | None = None,
        memory_service: MemoryService | None = None,
        long_term_memory_materialization_service: LongTermMemoryMaterializationService | None = None,
        long_term_memory_replay_executor: LongTermMemoryMaterializationReplayExecutor | None = None,
        internal_tool_registry: InternalToolRegistry | None = None,
        skill_usage_service: SkillUsageService | None = None,
        audit_service: AuditService,
    ) -> None:
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._study_plan_repository = study_plan_repository
        self._plan_stage_repository = plan_stage_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._autonomy_job_repository = autonomy_job_repository
        self._learner_availability_repository = learner_availability_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._task_attempt_repository = task_attempt_repository
        self._planner_service = planner_service
        self._workflow_run_service = workflow_run_service
        self._session_service = session_service
        self._chat_service = chat_service
        self._quiz_service = quiz_service
        self._autonomy_job_service = autonomy_job_service
        self._reflection_service = reflection_service
        self._reflection_evidence_service = reflection_evidence_service
        self._reflection_outcome_service = reflection_outcome_service
        self._reflection_proposal_sandbox_service = reflection_proposal_sandbox_service
        self._reflection_proposal_rollout_service = reflection_proposal_rollout_service
        self._rollout_resolver = rollout_resolver
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._strategy_card_service = strategy_card_service
        self._reflective_memory_service = reflective_memory_service
        self._memory_service = memory_service
        self._long_term_memory_materialization_service = long_term_memory_materialization_service
        self._long_term_memory_replay_scheduler = LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=autonomy_job_service
        )
        self._long_term_memory_replay_executor = long_term_memory_replay_executor
        self._internal_tool_registry = internal_tool_registry
        self._skill_usage_service = skill_usage_service
        self._audit_service = audit_service
        self._autonomy_jobs_running = False
        self._register_internal_tools()

    async def generate_plan(
        self,
        *,
        goal_id: str,
        trigger_source: str,
        commit: bool = True,
        scheduled_job_id: str | None = None,
    ) -> StudyPlanResponse:
        goal = await self._require_goal(goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is not None and trigger_source not in {"manual_replan", "task_failed", "task_skipped"}:
            raise ValidationError("An active study plan already exists for this goal.")
        version = 1 if active_plan is None else active_plan.version + 1
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_generation",
            trigger_source=trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id if active_plan is not None else None,
            daily_task_id=None,
            scheduled_job_id=scheduled_job_id,
        )
        try:
            memory_interpretation = None
            if self._memory_service is not None:
                memory_interpretation = await self._memory_service.build_interpretation(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    limit_per_type=4,
                )
            materialized = await self._planner_service.build_plan(
                goal=goal,
                version=version,
                trigger_source=trigger_source,
                supersedes_plan_id=active_plan.id if active_plan is not None else None,
                memory_interpretation=memory_interpretation,
            )
            if active_plan is not None:
                superseded = active_plan.with_status("superseded")
                await self._study_plan_repository.update(superseded)
                await self._daily_task_repository.bulk_mark_superseded(active_plan.id)
                await self._audit_service.record(
                    event_type="study_plan.superseded",
                    resource_type="study_plan",
                    resource_id=active_plan.id,
                    actor="system",
                    event_data={
                        "study_plan_id": active_plan.id,
                        "learner_goal_id": goal.id,
                        "superseded_by_plan_id": materialized.study_plan.id,
                    },
                )
            await self._study_plan_repository.create(materialized.study_plan)
            await self._plan_stage_repository.create_many(materialized.stages)
            await self._daily_task_repository.create_many(materialized.tasks)
            await self._audit_service.record(
                event_type="study_plan.generated" if active_plan is None else "study_plan.replanned",
                resource_type="study_plan",
                resource_id=materialized.study_plan.id,
                actor="system",
                event_data={
                    "learner_goal_id": goal.id,
                    "study_plan_id": materialized.study_plan.id,
                    "version": materialized.study_plan.version,
                    "trigger_source": trigger_source,
                    "task_count": len(materialized.tasks),
                    "fallback_used": materialized.llm_draft.fallback_used,
                },
            )
            for task in materialized.tasks:
                await self._audit_service.record(
                    event_type="daily_task.created",
                    resource_type="daily_task",
                    resource_id=task.id,
                    actor="system",
                    event_data={
                        "daily_task_id": task.id,
                        "learner_goal_id": task.learner_goal_id,
                        "study_plan_id": task.study_plan_id,
                        "task_type": task.task_type,
                        "scheduled_for": task.scheduled_for.isoformat(),
                    },
                )
            run = await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="study_plan",
                result_resource_ids=[materialized.study_plan.id, *[task.id for task in materialized.tasks]],
            )
            await self._sync_goal_state_after_plan(goal.id, materialized.study_plan.id, trigger_source=trigger_source)
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._workflow_run_service.fail_run(run=run, error_code=type(exc).__name__)
            await self._trigger_workflow_failure_reflection(
                goal_learner_profile_id=goal.learner_profile_id,
                goal_id=goal.id,
                workflow_run_id=run.id,
                study_plan_id=active_plan.id if active_plan is not None else None,
            )
            raise
        return await self.get_plan(materialized.study_plan.id)

    async def list_plans(self, goal_id: str) -> list[StudyPlanResponse]:
        await self._require_goal(goal_id)
        plans = await self._study_plan_repository.list_by_goal(goal_id)
        return [await self._to_plan_response(item) for item in plans]

    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        plan = await self._study_plan_repository.get_by_id(plan_id)
        if plan is None:
            raise NotFoundError(f"Study plan '{plan_id}' was not found.")
        return await self._to_plan_response(plan)

    async def list_tasks(
        self,
        goal_id: str,
        *,
        statuses: set[str] | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        task_type: str | None = None,
    ) -> list[DailyTaskResponse]:
        await self._require_goal(goal_id)
        if statuses is None and scheduled_from is None and scheduled_to is None and task_type is None:
            tasks = await self._daily_task_repository.list_by_goal(goal_id)
        else:
            tasks = await self._daily_task_repository.list_filtered(
                learner_goal_id=goal_id,
                statuses=statuses,
                scheduled_from=self._to_datetime(scheduled_from) if scheduled_from is not None else None,
                scheduled_to=self._to_datetime(scheduled_to) if scheduled_to is not None else None,
                task_type=task_type,
            )
        return [DailyTaskResponse.model_validate(item) for item in tasks]

    async def get_task(self, task_id: str) -> DailyTaskResponse:
        task = await self._daily_task_repository.get_by_id(task_id)
        if task is None:
            raise NotFoundError(f"Daily task '{task_id}' was not found.")
        return DailyTaskResponse.model_validate(task)

    async def execute_task(self, task_id: str) -> ExecuteDailyTaskResponse:
        task = await self._require_task(task_id)
        if task.status == "in_progress" and task.execution_session_id is not None and task.last_workflow_run_id is not None:
            await self._audit_service.record_durable(
                event_type="daily_task.execution.reused",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": task.last_workflow_run_id,
                    "execution_session_id": task.execution_session_id,
                    "task_type": task.task_type,
                    "execution_mode": task.execution_mode,
                },
            )
            return ExecuteDailyTaskResponse(
                task=DailyTaskResponse.model_validate(task),
                workflow_run_id=task.last_workflow_run_id,
                execution_session_id=task.execution_session_id,
                reused_existing_execution=True,
            )
        if task.status != "pending":
            raise ValidationError("Only pending tasks can be executed.")

        run = await self._workflow_run_service.create_run(
            workflow_type="task_execution",
            trigger_source="manual_execute",
            learner_goal_id=task.learner_goal_id,
            study_plan_id=task.study_plan_id,
            daily_task_id=task.id,
        )
        try:
            goal = await self._require_goal(task.learner_goal_id)
            session = await self._session_service.create_session(
                CreateSessionRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    title=task.title,
                    subject=goal.subject,
                ),
                daily_task_id=task.id,
                commit=False,
            )
            working_task = task.with_execution_session(
                execution_session_id=session.id,
                workflow_run_id=run.id,
            )
            await self._daily_task_repository.update(working_task)
            await self._audit_service.record(
                event_type="daily_task.execution.started",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "execution_session_id": session.id,
                    "execution_mode": task.execution_mode,
                },
            )
            if task.execution_mode == "chat":
                await self._chat_service.create_message(
                    session_id=session.id,
                    payload=MessageRequest(content=task.instructions, mode="chat"),
                    commit=False,
                )
            elif task.execution_mode == "quiz":
                await self._quiz_service.generate_quiz(
                    GenerateQuizRequest(
                        session_id=session.id,
                        topic=task.topic_focus,
                        difficulty=task.difficulty or "medium",
                        question_count=task.question_count or 3,
                    ),
                    commit=False,
                )
            else:
                raise ValidationError("Unsupported task execution mode.")
            run = await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="learning_session",
                result_resource_ids=[session.id],
            )
            await self._audit_service.record(
                event_type="daily_task.execution.completed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "execution_session_id": session.id,
                },
            )
            await self._db_session.commit()
            refreshed_task = await self._require_task(task.id)
            return ExecuteDailyTaskResponse(
                task=DailyTaskResponse.model_validate(refreshed_task),
                workflow_run_id=run.id,
                execution_session_id=session.id,
                reused_existing_execution=False,
            )
        except Exception as exc:
            await self._workflow_run_service.fail_run(run=run, error_code=type(exc).__name__)
            goal = await self._require_goal(task.learner_goal_id)
            await self._trigger_workflow_failure_reflection(
                goal_learner_profile_id=goal.learner_profile_id,
                goal_id=goal.id,
                daily_task_id=task.id,
                workflow_run_id=run.id,
                study_plan_id=task.study_plan_id,
            )
            await self._audit_service.record_durable(
                event_type="daily_task.execution.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            await self._db_session.rollback()
            raise

    async def update_task_status(
        self,
        *,
        task_id: str,
        payload: UpdateDailyTaskStatusRequest,
    ) -> DailyTaskResponse:
        if payload.status not in {"completed", "skipped", "failed"}:
            raise ValidationError("Only completed, skipped, or failed status updates are supported.")
        task = await self._require_task(task_id)
        if task.status not in {"pending", "in_progress"}:
            raise ValidationError("Only pending or in-progress tasks can be updated.")
        updated_task = task.with_status(payload.status, result_note=payload.result_note)
        inline_followups = self._autonomy_job_repository is None
        try:
            await self._daily_task_repository.update(updated_task)
            observe_daily_task_status_transition(
                from_status=task.status,
                to_status=updated_task.status,
                task_type=updated_task.task_type,
            )
            await self._audit_service.record(
                event_type="daily_task.status.updated",
                resource_type="daily_task",
                resource_id=task.id,
                actor="learner",
                event_data={
                    "daily_task_id": task.id,
                    "previous_status": task.status,
                    "new_status": updated_task.status,
                    "result_note": payload.result_note,
                },
            )
            attempt = await self._record_task_attempt(updated_task)
            await self._update_topic_mastery(updated_task)
            if self._long_term_memory_materialization_service is not None and attempt is not None:
                goal = await self._require_goal(updated_task.learner_goal_id)
                await self._materialize_task_outcome_isolated(
                    learner_profile_id=goal.learner_profile_id,
                    task=updated_task,
                    attempt=attempt,
                )
            await self._derive_task_evidence(updated_task)
            await self._enqueue_autonomy_followups(updated_task)
            if self._rollout_observation_scheduler is not None:
                await self._rollout_observation_scheduler.schedule_active(
                    learner_goal_id=updated_task.learner_goal_id,
                    surface="plan_generation",
                    trigger_source="task_status_updated",
                    source_ref=updated_task.id,
                )
            if self._reflection_service is not None:
                await self._trigger_post_task_reflection(updated_task)
                await self._evaluate_recent_reflection_outcomes(updated_task)
            if inline_followups:
                await self._run_inline_status_followups(updated_task)
            await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="daily_task.status.update.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="learner",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": task.last_workflow_run_id,
                    "previous_status": task.status,
                    "requested_status": payload.status,
                    "result_note": payload.result_note,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise
        return DailyTaskResponse.model_validate(await self._require_task(task.id))

    async def _run_inline_status_followups(self, task: DailyTask) -> None:
        if task.status == "completed":
            await self._schedule_review_tasks(task)
            await self._extend_active_plan(task.learner_goal_id)
            return
        await self.generate_plan(
            goal_id=task.learner_goal_id,
            trigger_source="task_failed" if task.status == "failed" else "task_skipped",
            commit=False,
        )

    async def _materialize_task_outcome_isolated(
        self,
        *,
        learner_profile_id: str,
        task: DailyTask,
        attempt: TaskAttempt,
    ) -> None:
        if self._long_term_memory_materialization_service is None:
            return
        try:
            begin_nested = getattr(self._db_session, "begin_nested", None)
            if begin_nested is None:
                await self._long_term_memory_materialization_service.materialize_from_task_outcome(
                    learner_profile_id=learner_profile_id,
                    task=task,
                    attempt=attempt,
                    persist_embeddings=True,
                )
            else:
                async with begin_nested():
                    await self._long_term_memory_materialization_service.materialize_from_task_outcome(
                        learner_profile_id=learner_profile_id,
                        task=task,
                        attempt=attempt,
                        persist_embeddings=True,
                    )
        except Exception as exc:
            observe_long_term_memory_materialization(
                source_type="task_outcome",
                status="failed",
                reason_code=type(exc).__name__,
            )
            replay = await self._schedule_task_materialization_replay(task=task, attempt=attempt)
            event_data = {
                "source_type": "task_outcome",
                "learner_profile_id": learner_profile_id,
                "learner_goal_id": task.learner_goal_id,
                "task_id": task.id,
                "attempt_id": attempt.id,
                "workflow_run_id": attempt.workflow_run_id,
                "session_id": attempt.execution_session_id,
                "outcome_status": attempt.outcome_status,
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
            event_data.update(replay.audit_payload())
            await self._audit_service.record_durable(
                event_type="long_term_memory.materialization.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data=event_data,
            )

    async def _schedule_task_materialization_replay(
        self,
        *,
        task: DailyTask,
        attempt: TaskAttempt,
    ) -> LongTermMemoryReplayScheduleResult:
        try:
            return await self._long_term_memory_replay_scheduler.schedule_task_outcome(
                learner_goal_id=task.learner_goal_id,
                task_id=task.id,
                attempt_id=attempt.id,
            )
        except Exception as replay_exc:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:task_outcome:{task.id}:{attempt.id}",
                due_at=None,
                skip_reason="replay_enqueue_failed",
                error_code=type(replay_exc).__name__,
                error=str(replay_exc),
            )

    async def list_workflow_runs(self, goal_id: str) -> list[WorkflowRunResponse]:
        await self._require_goal(goal_id)
        runs = await self._workflow_run_repository.list_by_goal(goal_id)
        return [WorkflowRunResponse.model_validate(item) for item in runs]

    async def get_workflow_run(self, run_id: str) -> WorkflowRunResponse:
        run = await self._workflow_run_repository.get_by_id(run_id)
        if run is None:
            raise NotFoundError(f"Workflow run '{run_id}' was not found.")
        return WorkflowRunResponse.model_validate(run)

    async def get_goal_autonomy_state(self, goal_id: str) -> GoalAutonomyStateResponse:
        state = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(state)

    async def update_goal_availability(
        self,
        *,
        goal_id: str,
        payload: UpdateLearnerAvailabilityRequest,
    ) -> LearnerAvailabilityResponse:
        goal = await self._require_goal(goal_id)
        if self._learner_availability_repository is None:
            raise ValidationError("Learner availability storage is not configured.")
        validated_timezone = self._validate_timezone(payload.timezone)
        availability = LearnerAvailability.build(
            learner_goal_id=goal.id,
            timezone=validated_timezone,
            available_days=payload.available_days,
            time_windows=payload.time_windows,
            max_daily_minutes=payload.max_daily_minutes,
            preferred_session_length_minutes=payload.preferred_session_length_minutes,
        )
        await self._learner_availability_repository.upsert(availability)
        await self._audit_service.record(
            event_type="learner_availability.updated",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={
                "learner_goal_id": goal.id,
                "timezone": validated_timezone,
                "available_days": payload.available_days,
                "max_daily_minutes": payload.max_daily_minutes,
                "preferred_session_length_minutes": payload.preferred_session_length_minutes,
            },
        )
        await self._sync_goal_state(goal.id, reason="availability_updated")
        await self._ensure_daily_materialization_job(goal.id, trigger_source="availability_updated")
        await self._db_session.commit()
        stored = await self._learner_availability_repository.get_by_goal(goal.id)
        if stored is None:
            raise NotFoundError(f"Learner availability for goal '{goal.id}' was not found.")
        return LearnerAvailabilityResponse.model_validate(stored)

    async def get_goal_availability(self, goal_id: str) -> LearnerAvailabilityResponse:
        await self._require_goal(goal_id)
        if self._learner_availability_repository is None:
            raise NotFoundError(f"Learner availability for goal '{goal_id}' was not found.")
        availability = await self._learner_availability_repository.get_by_goal(goal_id)
        if availability is None:
            raise NotFoundError(f"Learner availability for goal '{goal_id}' was not found.")
        return LearnerAvailabilityResponse.model_validate(availability)

    async def list_goal_mastery(self, goal_id: str) -> list[LearnerTopicMasteryResponse]:
        await self._require_goal(goal_id)
        if self._learner_topic_mastery_repository is None:
            return []
        masteries = await self._learner_topic_mastery_repository.list_by_goal(goal_id)
        return [LearnerTopicMasteryResponse.model_validate(item) for item in masteries]

    async def pause_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        goal = await self._require_goal(goal_id)
        await self._sync_goal_state(goal_id, phase="paused", reason=reason or "paused")
        await self._audit_service.record(
            event_type="autonomy.state.paused",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={"learner_goal_id": goal.id, "reason": reason},
        )
        await self._db_session.commit()
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def resume_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        goal = await self._require_goal(goal_id)
        await self._sync_goal_state(goal_id, phase="active", reason=reason or "resumed")
        await self._ensure_daily_materialization_job(goal.id, trigger_source="autonomy_resumed")
        await self._audit_service.record(
            event_type="autonomy.state.resumed",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={"learner_goal_id": goal.id, "reason": reason},
        )
        await self._db_session.commit()
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJob]:
        await self._require_goal(goal_id)
        if self._autonomy_job_repository is None:
            return []
        return await self._autonomy_job_repository.list_by_goal(goal_id)

    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse:
        await self._require_goal(goal_id)
        availability = await self._get_goal_availability_entity(goal_id)
        timezone_name = self._validate_timezone(availability.timezone if availability is not None else None) or "UTC"
        zone = ZoneInfo(timezone_name)
        target_day = datetime.now(zone).date()
        await self._schedule_autonomy_job(
            learner_goal_id=goal_id,
            job_type="daily_task_materialization",
            trigger_source="manual_materialize_today",
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"{goal_id}:manual_materialize_today:{datetime.now(timezone.utc).isoformat()}",
            payload={
                "window_days": 3,
                "target_local_date": target_day.isoformat(),
                "target_timezone": timezone_name,
                "scheduled_local_time": "manual",
            },
        )
        await self._db_session.commit()
        await self.run_due_autonomy_jobs(raise_on_error=True, lease_owner="manual-materialize")
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def manual_replan_goal(self, goal_id: str, payload: ManualReplanRequest) -> GoalAutonomyStateResponse:
        goal = await self._require_goal(goal_id)
        if payload.mode not in AUTONOMY_REPLAN_MODES:
            raise ValidationError("Unsupported autonomy replan mode.")
        job = await self._schedule_autonomy_job(
            learner_goal_id=goal.id,
            job_type="replan",
            trigger_source=payload.trigger_source,
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"{goal.id}:manual_replan:{payload.mode}:{payload.source_task_id or 'latest'}",
            payload={
                "mode": payload.mode,
                "source_task_id": payload.source_task_id or "",
            },
        )
        await self._sync_goal_state(goal.id, phase="replanning", next_due_at=datetime.now(timezone.utc), reason="manual_replan_requested")
        await self._audit_service.record(
            event_type="autonomy.replan.requested",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={
                "learner_goal_id": goal.id,
                "trigger_source": payload.trigger_source,
                "mode": payload.mode,
                "source_task_id": payload.source_task_id,
            },
        )
        await self._db_session.commit()
        await self.run_due_autonomy_jobs(raise_on_error=True, lease_owner="manual-replan")
        refreshed = await self._require_goal_autonomy_state(goal.id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def run_periodic_goal_reflection(self, goal_id: str) -> GoalAutonomyStateResponse:
        goal = await self._require_goal(goal_id)
        if self._reflection_service is not None:
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="goal",
                    target_type="learner_goal",
                    target_id=goal.id,
                    trigger_source="plan_replanned",
                    reflection_depth=1,
                    source_attempt_id=f"{goal.id}:{date.today().isoformat()}",
                )
            )
        await self._sync_goal_state(goal.id, phase="active", reason="periodic_goal_reflection")
        await self._db_session.commit()
        refreshed = await self._require_goal_autonomy_state(goal.id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def run_due_autonomy_jobs(
        self,
        *,
        raise_on_error: bool = True,
        lease_owner: str = "inline",
        limit: int = 20,
    ) -> int:
        if self._autonomy_job_repository is None:
            return 0
        if self._autonomy_jobs_running:
            return 0
        self._autonomy_jobs_running = True
        try:
            processed = 0
            while processed < limit:
                due_jobs = await self._autonomy_job_repository.list_due(
                    now=datetime.now(timezone.utc),
                    limit=limit - processed,
                )
                if not due_jobs:
                    break
                for job in due_jobs:
                    claimed = await self._autonomy_job_repository.claim(job, lease_owner=lease_owner, lease_seconds=300)
                    await self._audit_service.record(
                        event_type="autonomy.job.claimed",
                        resource_type="autonomy_job",
                        resource_id=claimed.id,
                        actor="system",
                        event_data={
                            "autonomy_job_id": claimed.id,
                            "learner_goal_id": claimed.learner_goal_id,
                            "job_type": claimed.job_type,
                            "trigger_source": claimed.trigger_source,
                            "attempt_count": claimed.attempt_count,
                        },
                    )
                    await self._db_session.commit()
                    try:
                        workflow_run_id = await self._process_autonomy_job(claimed)
                        completed = claimed.complete(workflow_run_id=workflow_run_id)
                        await self._autonomy_job_repository.update(completed)
                        await self._audit_service.record(
                            event_type="autonomy.job.completed",
                            resource_type="autonomy_job",
                            resource_id=completed.id,
                            actor="system",
                            event_data={
                                "autonomy_job_id": completed.id,
                                "learner_goal_id": completed.learner_goal_id,
                                "job_type": completed.job_type,
                                "workflow_run_id": workflow_run_id,
                            },
                        )
                        await self._db_session.commit()
                        processed += 1
                    except Exception as exc:
                        if claimed.job_type == LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE and claimed.attempt_count < claimed.max_attempts:
                            retry_due_at = datetime.now(timezone.utc) + long_term_memory_replay_backoff(claimed.attempt_count)
                            retry = claimed.retry(due_at=retry_due_at)
                            await self._autonomy_job_repository.update(retry)
                            await self._audit_service.record_durable(
                                event_type="long_term_memory.materialization.replay_retry_scheduled",
                                resource_type="autonomy_job",
                                resource_id=retry.id,
                                actor="system",
                                event_data={
                                    "autonomy_job_id": retry.id,
                                    "learner_goal_id": retry.learner_goal_id,
                                    "job_type": retry.job_type,
                                    "attempt_count": retry.attempt_count,
                                    "max_attempts": retry.max_attempts,
                                    "retry_due_at": retry.due_at.isoformat(),
                                    "error_code": type(exc).__name__,
                                    "error": str(exc),
                                },
                            )
                            await self._db_session.commit()
                            processed += 1
                            continue
                        failed = claimed.fail(error_code=type(exc).__name__)
                        await self._autonomy_job_repository.update(failed)
                        if claimed.job_type == LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE:
                            await self._audit_service.record_durable(
                                event_type="long_term_memory.materialization.replay_exhausted",
                                resource_type="autonomy_job",
                                resource_id=failed.id,
                                actor="system",
                                event_data={
                                    "autonomy_job_id": failed.id,
                                    "learner_goal_id": failed.learner_goal_id,
                                    "job_type": failed.job_type,
                                    "attempt_count": failed.attempt_count,
                                    "max_attempts": failed.max_attempts,
                                    "error_code": type(exc).__name__,
                                    "error": str(exc),
                                },
                            )
                        await self._audit_service.record_durable(
                            event_type="autonomy.job.failed",
                            resource_type="autonomy_job",
                            resource_id=failed.id,
                            actor="system",
                            event_data={
                                "autonomy_job_id": failed.id,
                                "learner_goal_id": failed.learner_goal_id,
                                "job_type": failed.job_type,
                                "error_code": type(exc).__name__,
                                "error": str(exc),
                            },
                        )
                        await self._db_session.commit()
                        if raise_on_error:
                            raise
            return processed
        finally:
            self._autonomy_jobs_running = False

    async def _process_autonomy_job(self, job: ScheduledAutonomyJob) -> str | None:
        if job.job_type == "review_scheduling":
            workflow_run_id = await self._process_review_scheduling_job(job)
        elif job.job_type == "daily_task_materialization":
            workflow_run_id = await self._process_daily_task_materialization_job(job)
        elif job.job_type == "plan_extension":
            workflow_run_id = await self._process_plan_extension_job(job)
        elif job.job_type == "replan":
            workflow_run_id = await self._process_replan_job(job)
        elif job.job_type == "assessment_generation":
            workflow_run_id = await self._process_assessment_generation_job(job)
        elif job.job_type == "milestone_generation":
            workflow_run_id = await self._process_milestone_generation_job(job)
        elif job.job_type == "mastery_refresh":
            workflow_run_id = await self._process_mastery_refresh_job(job)
        elif job.job_type == "goal_reflection_periodic":
            workflow_run_id = await self._process_periodic_goal_reflection_job(job)
        elif job.job_type == "reflection_outcome_evaluation":
            workflow_run_id = await self._process_reflection_outcome_evaluation_job(job)
        elif job.job_type == "reflection_proposal_evaluation":
            workflow_run_id = await self._process_reflection_proposal_evaluation_job(job)
        elif job.job_type == "reflection_proposal_rollout_observation":
            workflow_run_id = await self._process_reflection_proposal_rollout_observation_job(job)
        elif job.job_type == LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE:
            workflow_run_id = await self._process_long_term_memory_materialization_replay_job(job)
        else:
            raise ValidationError("Unsupported autonomy job type.")
        await self._db_session.commit()
        return workflow_run_id

    async def _process_long_term_memory_materialization_replay_job(self, job: ScheduledAutonomyJob) -> str | None:
        if self._long_term_memory_replay_executor is None:
            raise ValidationError("Long-term memory materialization replay executor is not configured.")
        begin_nested = getattr(self._db_session, "begin_nested", None)
        if begin_nested is None:
            await self._long_term_memory_replay_executor.replay(job)
        else:
            async with begin_nested():
                await self._long_term_memory_replay_executor.replay(job)
        return None

    async def _process_review_scheduling_job(self, job: ScheduledAutonomyJob) -> str | None:
        source_task_id = str(job.payload.get("source_task_id") or "")
        if not source_task_id:
            raise ValidationError("Missing source_task_id for review scheduling job.")
        source_task = await self._require_task(source_task_id)
        goal = await self._require_goal(source_task.learner_goal_id)
        if source_task.task_type == "review":
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="review_scheduling",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=source_task.study_plan_id,
            daily_task_id=source_task.id,
            scheduled_job_id=job.id,
        )
        mastery = await self._get_topic_mastery(goal.id, source_task.topic_focus)
        review_tasks: list[DailyTask] = []
        if self._internal_tool_registry is not None:
            result = await self._internal_tool_registry.execute(
                ToolExecutionRequest(
                    name="review_scheduling",
                    payload={"source_task_id": source_task.id},
                    actor="system",
                    resource_id=source_task.id,
                )
            )
            created_ids = [str(item) for item in (result or {}).get("created_task_ids", [])]
            review_tasks = [await self._require_task(task_id) for task_id in created_ids]
        else:
            existing_reviews = await self._daily_task_repository.list_by_source_task(source_task.id)
            existing_due_dates = {task.scheduled_for for task in existing_reviews}
            intervals = await self._review_intervals(goal.id, mastery)
            for offset in intervals:
                scheduled_for = source_task.due_on + timedelta(days=offset)
                if scheduled_for > goal.deadline_date or scheduled_for in existing_due_dates:
                    continue
                review_tasks.append(
                    DailyTask.build(
                        learner_goal_id=goal.id,
                        study_plan_id=source_task.study_plan_id,
                        plan_stage_id=source_task.plan_stage_id,
                        task_origin="review_scheduler",
                        task_type="review",
                        execution_mode="quiz",
                        title=f"Review: {source_task.topic_focus}",
                        instructions=f"Review {source_task.topic_focus} and reinforce the key idea.",
                        topic_focus=source_task.topic_focus,
                        difficulty=source_task.difficulty or "medium",
                        question_count=source_task.question_count or 3,
                        estimated_minutes=max(15, source_task.estimated_minutes // 2),
                        scheduled_for=scheduled_for,
                        due_on=scheduled_for,
                        source_task_id=source_task.id,
                    )
                )
            if review_tasks:
                await self._daily_task_repository.create_many(review_tasks)
            for task in review_tasks:
                await self._audit_service.record(
                    event_type="daily_task.created",
                    resource_type="daily_task",
                    resource_id=task.id,
                    actor="system",
                    event_data={
                        "daily_task_id": task.id,
                        "learner_goal_id": goal.id,
                        "study_plan_id": task.study_plan_id,
                        "task_type": task.task_type,
                        "scheduled_for": task.scheduled_for.isoformat(),
                        "source_task_id": source_task.id,
                    },
                )
        await self._audit_service.record(
            event_type="review.tasks.scheduled",
            resource_type="daily_task",
            resource_id=source_task.id,
            actor="system",
            event_data={
                "source_daily_task_id": source_task.id,
                "created_review_task_ids": [task.id for task in review_tasks],
                "mastery_score": mastery.mastery_score if mastery is not None else None,
            },
        )
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[task.id for task in review_tasks],
        )
        await self._sync_goal_state(goal.id, phase="active", next_due_at=self._to_datetime(review_tasks[0].scheduled_for) if review_tasks else None, reason="review_scheduled")
        return run.id

    async def _process_reflection_proposal_evaluation_job(self, job: ScheduledAutonomyJob) -> str | None:
        if self._reflection_proposal_sandbox_service is None:
            raise ValidationError("Reflection proposal sandbox service is not configured.")
        proposal_id = str(job.payload.get("proposal_id") or "")
        if not proposal_id:
            raise ValidationError("Missing proposal_id for reflection proposal evaluation job.")
        sandbox_run = await self._reflection_proposal_sandbox_service.execute(proposal_id=proposal_id)
        return sandbox_run.id

    async def _process_reflection_proposal_rollout_observation_job(self, job: ScheduledAutonomyJob) -> str | None:
        if self._reflection_proposal_rollout_service is None:
            raise ValidationError("Reflection proposal rollout service is not configured.")
        rollout_id = str(job.payload.get("rollout_id") or "")
        if not rollout_id:
            raise ValidationError("Missing rollout_id for reflection proposal rollout observation job.")
        observation = await self._reflection_proposal_rollout_service.observe(
            rollout_id=rollout_id,
            trigger_source=job.trigger_source,
        )
        return observation.id

    async def _process_plan_extension_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_extension",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            daily_task_id=None,
            scheduled_job_id=job.id,
        )
        stages = await self._plan_stage_repository.list_by_plan(active_plan.id)
        tasks = await self._daily_task_repository.list_by_goal(goal.id)
        stage_map = {stage.position: stage.id for stage in stages}
        blocked_stage_position = await self._blocked_stage_position(active_plan.id, goal.id)
        new_tasks, target_until = await self._planner_service.extend_plan_window(
            goal=goal,
            active_plan=active_plan,
            existing_tasks=tasks,
            stage_id_by_position=stage_map,
        )
        if blocked_stage_position is not None:
            allowed_stage_ids = {stage.id for stage in stages if stage.position <= blocked_stage_position}
            new_tasks = [task for task in new_tasks if task.plan_stage_id is None or task.plan_stage_id in allowed_stage_ids]
            await self._suppress_downstream_stage_tasks(goal.id, active_plan.id, blocked_after_position=blocked_stage_position)
        if new_tasks:
            await self._daily_task_repository.create_many(new_tasks)
            for task in new_tasks:
                await self._audit_service.record(
                    event_type="daily_task.created",
                    resource_type="daily_task",
                    resource_id=task.id,
                    actor="system",
                    event_data={
                        "daily_task_id": task.id,
                        "learner_goal_id": goal.id,
                        "study_plan_id": task.study_plan_id,
                        "task_type": task.task_type,
                        "scheduled_for": task.scheduled_for.isoformat(),
                    },
                )
        if target_until != active_plan.materialized_until_date:
            await self._study_plan_repository.update(active_plan.with_materialized_until(target_until))
        await self._audit_service.record(
            event_type="study_plan.window.extended",
            resource_type="study_plan",
            resource_id=active_plan.id,
            actor="system",
            event_data={
                "study_plan_id": active_plan.id,
                "target_until": target_until.isoformat() if target_until is not None else None,
                "created_task_count": len(new_tasks),
            },
        )
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[task.id for task in new_tasks],
        )
        await self._sync_goal_state(
            goal.id,
            phase="assessment_due" if blocked_stage_position is not None else "active",
            next_due_at=self._to_datetime(new_tasks[0].scheduled_for) if new_tasks else None,
            reason="plan_extended",
        )
        return run.id

    async def _process_replan_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        mode = str(job.payload.get("mode") or "partial")
        if mode not in AUTONOMY_REPLAN_MODES:
            raise ValidationError("Unsupported autonomy replan mode.")
        if mode == "full":
            await self.generate_plan(
                goal_id=goal.id,
                trigger_source=job.trigger_source,
                commit=False,
                scheduled_job_id=job.id,
            )
            await self._sync_goal_state(goal.id, phase="active", reason="full_replan")
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="goal",
                    target_type="learner_goal",
                    target_id=goal.id,
                    trigger_source="plan_replanned",
                    reflection_depth=1,
                    source_attempt_id=job.id,
                )
            )
            return None
        source_task_id = str(job.payload.get("source_task_id") or "")
        source_task = None
        if source_task_id:
            source_task = await self._require_task(source_task_id)
        else:
            recent_tasks = await self._daily_task_repository.list_by_goal(goal.id)
            if recent_tasks:
                source_task = recent_tasks[-1]
        if source_task is None:
            await self.generate_plan(
                goal_id=goal.id,
                trigger_source=job.trigger_source,
                commit=False,
                scheduled_job_id=job.id,
            )
            await self._sync_goal_state(goal.id, phase="active", reason="fallback_full_replan")
            return None
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            await self.generate_plan(
                goal_id=goal.id,
                trigger_source=job.trigger_source,
                commit=False,
                scheduled_job_id=job.id,
            )
            await self._sync_goal_state(goal.id, phase="active", reason="fallback_full_replan")
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_extension",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            daily_task_id=source_task.id,
            scheduled_job_id=job.id,
        )
        scheduled_for = max(date.today() + timedelta(days=1), source_task.due_on + timedelta(days=1))
        if self._internal_tool_registry is not None:
            result = await self._internal_tool_registry.execute(
                ToolExecutionRequest(
                    name="partial_replan",
                    payload={"source_task_id": source_task.id},
                    actor="system",
                    resource_id=source_task.id,
                )
            )
            created_ids = [str(item) for item in (result or {}).get("created_task_ids", [])]
            if not created_ids:
                return None
            repair_task = await self._require_task(created_ids[0])
            if source_task.task_type == "milestone":
                superseded = source_task.with_status("superseded", result_note=source_task.result_note)
                await self._daily_task_repository.update(superseded)
        else:
            repair_task = DailyTask.build(
                learner_goal_id=goal.id,
                study_plan_id=active_plan.id,
                plan_stage_id=source_task.plan_stage_id,
                task_origin="replan_scheduler",
                task_type="repair",
                execution_mode=source_task.execution_mode,
                title=f"Repair: {source_task.topic_focus}",
                instructions=f"Repair the gap around {source_task.topic_focus}.",
                topic_focus=source_task.topic_focus,
                difficulty=source_task.difficulty or "medium",
                question_count=source_task.question_count,
                estimated_minutes=max(15, source_task.estimated_minutes),
                scheduled_for=scheduled_for,
                due_on=scheduled_for,
                source_task_id=source_task.id,
            )
            await self._daily_task_repository.create_many([repair_task])
        await self._audit_service.record(
            event_type="daily_task.created",
            resource_type="daily_task",
            resource_id=repair_task.id,
            actor="system",
            event_data={
                "daily_task_id": repair_task.id,
                "learner_goal_id": goal.id,
                "study_plan_id": repair_task.study_plan_id,
                "task_type": repair_task.task_type,
                "scheduled_for": repair_task.scheduled_for.isoformat(),
                "source_task_id": source_task.id,
            },
        )
        await self._audit_service.record(
            event_type="study_plan.replanned.partial",
            resource_type="study_plan",
            resource_id=active_plan.id,
            actor="system",
            event_data={
                "study_plan_id": active_plan.id,
                "source_task_id": source_task.id,
                "repair_task_id": repair_task.id,
            },
        )
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[repair_task.id],
        )
        await self._sync_goal_state(goal.id, phase="active", next_due_at=self._to_datetime(repair_task.scheduled_for), reason="partial_replan")
        await self._reflection_service.trigger_reflection(
            ReflectionTriggerRequest(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                scope="goal",
                target_type="learner_goal",
                target_id=goal.id,
                trigger_source="plan_replanned",
                reflection_depth=1,
                daily_task_id=repair_task.id,
                workflow_run_id=run.id,
                study_plan_id=active_plan.id,
                source_attempt_id=job.id,
            )
        )
        return run.id

    async def _process_assessment_generation_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        topic_key = str(job.payload.get("topic_focus") or goal.subject)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="assessment_generation",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            daily_task_id=None,
            scheduled_job_id=job.id,
        )
        scheduled_for = date.today() + timedelta(days=1)
        if self._internal_tool_registry is not None:
            result = await self._internal_tool_registry.execute(
                ToolExecutionRequest(
                    name="assessment_generation",
                    payload={"learner_goal_id": goal.id, "topic_focus": topic_key},
                    actor="system",
                    resource_id=goal.id,
                )
            )
            created_ids = [str(item) for item in (result or {}).get("created_task_ids", [])]
            if not created_ids:
                return None
            assessment_task = await self._require_task(created_ids[0])
        else:
            assessment_task = DailyTask.build(
                learner_goal_id=goal.id,
                study_plan_id=active_plan.id,
                plan_stage_id=None,
                task_origin="assessment_scheduler",
                task_type="assessment",
                execution_mode="quiz",
                title=f"Assessment: {topic_key}",
                instructions=f"Assess mastery of {topic_key}.",
                topic_focus=topic_key,
                difficulty="medium",
                question_count=5,
                estimated_minutes=30,
                scheduled_for=scheduled_for,
                due_on=scheduled_for,
            )
            await self._daily_task_repository.create_many([assessment_task])
        await self._audit_service.record(
            event_type="assessment.task.created",
            resource_type="daily_task",
            resource_id=assessment_task.id,
            actor="system",
            event_data={
                "daily_task_id": assessment_task.id,
                "learner_goal_id": goal.id,
                "study_plan_id": assessment_task.study_plan_id,
                "topic_focus": topic_key,
                "scheduled_for": assessment_task.scheduled_for.isoformat(),
            },
        )
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[assessment_task.id],
        )
        await self._sync_goal_state(goal.id, phase="active", next_due_at=self._to_datetime(assessment_task.scheduled_for), reason="assessment_scheduled")
        return run.id

    async def _process_daily_task_materialization_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_extension",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            daily_task_id=None,
            scheduled_job_id=job.id,
        )
        target_day, target_timezone = await self._resolve_materialization_target(goal.id, job)
        gate_stage_position = await self._blocked_stage_position(active_plan.id, goal.id)
        if gate_stage_position is not None:
            await self._suppress_downstream_stage_tasks(goal.id, active_plan.id, blocked_after_position=gate_stage_position)
        today = target_day
        window_end = today + timedelta(days=2)
        pending_tasks = await self._daily_task_repository.list_filtered(
            learner_goal_id=goal.id,
            statuses={"pending", "in_progress"},
            scheduled_from=self._to_datetime(today),
            scheduled_to=self._to_datetime(window_end),
        )
        availability = (
            await self._learner_availability_repository.get_by_goal(goal.id)
            if self._learner_availability_repository is not None
            else None
        )
        daily_budget = availability.max_daily_minutes if availability is not None and availability.max_daily_minutes is not None else 90
        preferred_session = (
            availability.preferred_session_length_minutes
            if availability is not None and availability.preferred_session_length_minutes is not None
            else 45
        )
        created_tasks: list[DailyTask] = []
        scheduled_minutes = sum(task.estimated_minutes for task in pending_tasks if task.scheduled_for == today and task.status == "pending")
        if scheduled_minutes < daily_budget:
            stages = await self._plan_stage_repository.list_by_plan(active_plan.id)
            stage_id_by_position = {stage.position: stage.id for stage in stages}
            all_tasks = await self._daily_task_repository.list_by_goal(goal.id)
            existing_keys = {(task.scheduled_for, task.task_type, task.topic_focus) for task in all_tasks}
            blueprint_tasks = sorted(
                list(active_plan.blueprint_payload.get("tasks") or []),
                key=lambda item: (str(item["scheduled_for"]), str(item["task_type"]), str(item["topic_focus"])),
            )
            remaining_minutes = max(daily_budget - scheduled_minutes, 0)
            stage_position_by_id = {stage.id: stage.position for stage in stages}
            for item in blueprint_tasks:
                scheduled_for = self._planner_service._parse_date(item["scheduled_for"])  # noqa: SLF001
                if scheduled_for != today:
                    continue
                stage_position = int(item["stage_position"])
                if gate_stage_position is not None and stage_position > gate_stage_position:
                    continue
                task_key = (scheduled_for, str(item["task_type"]), str(item["topic_focus"]))
                if task_key in existing_keys:
                    continue
                estimated_minutes = min(int(item["estimated_minutes"]), preferred_session)
                if remaining_minutes < min(estimated_minutes, 20):
                    continue
                created = DailyTask.build(
                    learner_goal_id=goal.id,
                    study_plan_id=active_plan.id,
                    plan_stage_id=stage_id_by_position.get(int(item["stage_position"])),
                    task_origin="planner",
                    task_type=str(item["task_type"]),
                    execution_mode=str(item["execution_mode"]),
                    title=str(item["title"]),
                    instructions=str(item["instructions"]),
                    topic_focus=str(item["topic_focus"]),
                    difficulty=str(item["difficulty"]) if item.get("difficulty") is not None else None,
                    question_count=int(item["question_count"]) if item.get("question_count") is not None else None,
                    estimated_minutes=estimated_minutes,
                    scheduled_for=scheduled_for,
                    due_on=self._planner_service._parse_date(item["due_on"]),  # noqa: SLF001
                )
                created_tasks.append(created)
                existing_keys.add(task_key)
                remaining_minutes -= estimated_minutes
        if created_tasks:
            await self._daily_task_repository.create_many(created_tasks)
            for task in created_tasks:
                await self._audit_service.record(
                    event_type="daily_task.created",
                    resource_type="daily_task",
                    resource_id=task.id,
                    actor="system",
                    event_data={
                        "daily_task_id": task.id,
                        "learner_goal_id": goal.id,
                        "study_plan_id": task.study_plan_id,
                        "task_type": task.task_type,
                        "scheduled_for": task.scheduled_for.isoformat(),
                        "trigger_source": job.trigger_source,
                    },
                )
        if active_plan.materialized_until_date is None or active_plan.materialized_until_date < today + timedelta(days=7):
            stages = await self._plan_stage_repository.list_by_plan(active_plan.id)
            stage_id_by_position = {stage.position: stage.id for stage in stages}
            existing_tasks = await self._daily_task_repository.list_by_goal(goal.id)
            new_tasks, target_until = await self._planner_service.extend_plan_window(
                goal=goal,
                active_plan=active_plan,
                existing_tasks=existing_tasks,
                stage_id_by_position=stage_id_by_position,
            )
            if gate_stage_position is not None:
                new_tasks = [
                    task
                    for task in new_tasks
                    if task.plan_stage_id is None or stage_id_by_position.get(gate_stage_position) is None or task.plan_stage_id in {
                        stage.id for stage in stages if stage.position <= gate_stage_position
                    }
                ]
            if new_tasks:
                await self._daily_task_repository.create_many(new_tasks)
                created_tasks.extend(new_tasks)
            if target_until != active_plan.materialized_until_date:
                await self._study_plan_repository.update(active_plan.with_materialized_until(target_until))
        await self._ensure_milestone_jobs(goal.id, active_plan.id)
        await self._ensure_daily_materialization_job(goal.id, trigger_source="daily_task_materialized", days_offset=1)
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[item.id for item in created_tasks],
        )
        await self._sync_goal_state(
            goal.id,
            phase="assessment_due" if gate_stage_position is not None else "active",
            next_due_at=self._to_datetime(today if created_tasks else today + timedelta(days=1)),
            reason="daily_materialized",
        )
        await self._audit_service.record(
            event_type="daily_tasks.materialized",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="system",
            event_data={
                "learner_goal_id": goal.id,
                "created_task_ids": [item.id for item in created_tasks],
                "daily_budget_minutes": daily_budget,
                "target_local_date": target_day.isoformat(),
                "target_timezone": target_timezone,
                "milestone_gate_position": gate_stage_position,
            },
        )
        return run.id

    async def _process_milestone_generation_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            return None
        stage_id = str(job.payload.get("stage_id") or "")
        if not stage_id:
            raise ValidationError("Missing stage_id for milestone generation job.")
        stages = await self._plan_stage_repository.list_by_plan(active_plan.id)
        stage = next((item for item in stages if item.id == stage_id), None)
        if stage is None:
            return None
        existing = await self._daily_task_repository.list_by_goal(goal.id)
        if any(task.task_type == "milestone" and task.plan_stage_id == stage.id and task.status != "superseded" for task in existing):
            return None
        run = await self._workflow_run_service.create_run(
            workflow_type="assessment_generation",
            trigger_source=job.trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            daily_task_id=None,
            scheduled_job_id=job.id,
        )
        milestone = DailyTask.build(
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            plan_stage_id=stage.id,
            task_origin="assessment_scheduler",
            task_type="milestone",
            execution_mode="quiz",
            title=f"Milestone: {stage.title}",
            instructions=f"Stage gate milestone for {stage.title}.",
            topic_focus=stage.focus_topics[0] if stage.focus_topics else goal.subject,
            difficulty="medium",
            question_count=max(5, len(stage.focus_topics) * 2),
            estimated_minutes=30,
            scheduled_for=max(date.today(), stage.end_date),
            due_on=max(date.today(), stage.end_date),
        )
        await self._daily_task_repository.create_many([milestone])
        await self._audit_service.record(
            event_type="milestone.task.created",
            resource_type="daily_task",
            resource_id=milestone.id,
            actor="system",
            event_data={
                "daily_task_id": milestone.id,
                "learner_goal_id": goal.id,
                "study_plan_id": active_plan.id,
                "plan_stage_id": stage.id,
            },
        )
        run = await self._workflow_run_service.complete_run(
            run=run,
            result_resource_type="daily_task",
            result_resource_ids=[milestone.id],
        )
        await self._sync_goal_state(
            goal.id,
            phase="assessment_due",
            next_due_at=self._to_datetime(milestone.scheduled_for),
            reason="milestone_scheduled",
        )
        return run.id

    async def _process_mastery_refresh_job(self, job: ScheduledAutonomyJob) -> str | None:
        goal = await self._require_goal(job.learner_goal_id)
        await self._refresh_goal_mastery_snapshot(goal.id)
        await self._sync_goal_state(goal.id, phase="active", reason="mastery_refreshed")
        return None

    async def _process_periodic_goal_reflection_job(self, job: ScheduledAutonomyJob) -> str | None:
        await self.run_periodic_goal_reflection(job.learner_goal_id)
        await self._schedule_periodic_goal_reflection_job(
            job.learner_goal_id,
            trigger_source="periodic_goal_reflection_completed",
        )
        return None

    async def _process_reflection_outcome_evaluation_job(self, job: ScheduledAutonomyJob) -> str | None:
        if self._reflection_service is None or self._reflection_outcome_service is None:
            return None
        pending = await self._reflection_outcome_service.list_pending(learner_goal_id=job.learner_goal_id, limit=10)
        for evaluation in pending:
            reflection = await self._reflection_service.get_record(evaluation.reflection_record_id)
            refreshed = await self._reflection_outcome_service.evaluate(
                reflection=reflection,
                topic_key=evaluation.topic_key,
            )
            await self._reflection_service.apply_outcome_feedback(
                reflection=reflection,
                evaluation=refreshed,
            )
        return None

    async def _sync_goal_state(
        self,
        goal_id: str,
        *,
        phase: str | None = None,
        current_plan_id: str | None | object = AUTONOMY_UNSET,
        next_due_at: datetime | None | object = AUTONOMY_UNSET,
        reason: str | None = None,
    ) -> None:
        if self._goal_autonomy_state_repository is None:
            return
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            state = GoalAutonomyState.build(learner_goal_id=goal_id)
            await self._goal_autonomy_state_repository.create(state)
        await self._goal_autonomy_state_repository.update(
            state.with_transition(
                phase=phase,
                current_plan_id=current_plan_id,
                next_due_at=next_due_at,
                mastery_snapshot=await self._build_mastery_snapshot(goal_id),
                reason=reason,
            )
        )

    async def _sync_goal_state_after_plan(self, goal_id: str, plan_id: str, *, trigger_source: str) -> None:
        await self._sync_goal_state(goal_id, phase="active", current_plan_id=plan_id, reason=trigger_source)
        await self._ensure_daily_materialization_job(goal_id, trigger_source=trigger_source)
        await self._schedule_periodic_goal_reflection_job(goal_id, trigger_source=trigger_source)

    async def _record_task_attempt(self, task: DailyTask) -> TaskAttempt | None:
        if self._task_attempt_repository is None:
            return None
        attempt = TaskAttempt.build(
            learner_goal_id=task.learner_goal_id,
            daily_task_id=task.id,
            workflow_run_id=task.last_workflow_run_id,
            execution_session_id=task.execution_session_id,
            task_type=task.task_type,
            topic_focus=task.topic_focus,
            outcome_status=task.status,
            score=self._attempt_score(task.status),
            result_note=task.result_note,
        )
        await self._task_attempt_repository.create(attempt)
        return attempt

    async def _update_topic_mastery(self, task: DailyTask) -> None:
        if self._learner_topic_mastery_repository is None:
            return
        current = await self._learner_topic_mastery_repository.get_by_goal_and_topic(task.learner_goal_id, task.topic_focus)
        mastery = current or LearnerTopicMastery.build(learner_goal_id=task.learner_goal_id, topic_key=task.topic_focus)
        updated = mastery.update_from_attempt(outcome_status=task.status, task_type=task.task_type)
        await self._learner_topic_mastery_repository.upsert(updated)
        await self._refresh_goal_mastery_snapshot(task.learner_goal_id)

    async def _refresh_goal_mastery_snapshot(self, goal_id: str) -> None:
        if self._goal_autonomy_state_repository is None:
            return
        snapshot = await self._build_mastery_snapshot(goal_id)
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            return
        await self._goal_autonomy_state_repository.update(
            state.with_transition(mastery_snapshot=snapshot, reason=state.last_transition_reason)
        )

    async def _build_mastery_snapshot(self, goal_id: str) -> dict[str, object]:
        if self._learner_topic_mastery_repository is None:
            return {}
        masteries = await self._learner_topic_mastery_repository.list_by_goal(goal_id)
        return {
            "topics": [
                {
                    "topic_key": mastery.topic_key,
                    "mastery_score": mastery.mastery_score,
                    "confidence": mastery.confidence,
                    "evidence_count": mastery.evidence_count,
                }
                for mastery in masteries
            ]
        }

    async def _enqueue_autonomy_followups(self, task: DailyTask) -> None:
        if self._autonomy_job_repository is None:
            return
        now = datetime.now(timezone.utc)
        if task.status == "completed":
            if task.task_type == "milestone":
                await self._sync_goal_state(task.learner_goal_id, phase="active", next_due_at=now, reason="milestone_completed")
                await self._ensure_daily_materialization_job(task.learner_goal_id, trigger_source="milestone_completed")
                await self._schedule_outcome_evaluation_job(task.learner_goal_id, trigger_source="milestone_completed")
                return
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="review_scheduling",
                trigger_source="task_completed",
                due_at=now,
                idempotency_key=f"{task.id}:review_scheduling",
                payload={"source_task_id": task.id},
            )
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="plan_extension",
                trigger_source="task_completed",
                due_at=now,
                idempotency_key=f"{task.id}:plan_extension",
                payload={"source_task_id": task.id},
            )
            await self._ensure_daily_materialization_job(task.learner_goal_id, trigger_source="task_completed")
            if await self._should_schedule_assessment(task):
                await self._schedule_autonomy_job(
                    learner_goal_id=task.learner_goal_id,
                    job_type="assessment_generation",
                    trigger_source="task_completed",
                    due_at=now,
                    idempotency_key=f"{task.id}:assessment_generation",
                    payload={"topic_focus": task.topic_focus, "source_task_id": task.id},
                )
            await self._schedule_outcome_evaluation_job(task.learner_goal_id, trigger_source="task_completed")
        else:
            if task.task_type == "milestone":
                await self._schedule_autonomy_job(
                    learner_goal_id=task.learner_goal_id,
                    job_type="replan",
                    trigger_source="milestone_failed" if task.status == "failed" else "milestone_skipped",
                    due_at=now,
                    idempotency_key=f"{task.id}:replan:partial",
                    payload={"mode": "partial", "source_task_id": task.id, "topic_focus": task.topic_focus},
                )
                await self._sync_goal_state(
                    task.learner_goal_id,
                    phase="assessment_due",
                    next_due_at=now,
                    reason=f"milestone_{task.status}",
                )
                await self._schedule_outcome_evaluation_job(task.learner_goal_id, trigger_source=f"milestone_{task.status}")
                return
            mode = await self._derive_replan_mode(task)
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="replan",
                trigger_source="task_failed" if task.status == "failed" else "task_skipped",
                due_at=now,
                idempotency_key=f"{task.id}:replan:{mode}",
                payload={"mode": mode, "source_task_id": task.id, "topic_focus": task.topic_focus},
            )
            await self._sync_goal_state(task.learner_goal_id, phase="replanning", next_due_at=now, reason=f"task_{task.status}")
            await self._schedule_outcome_evaluation_job(task.learner_goal_id, trigger_source=f"task_{task.status}")

    async def _schedule_autonomy_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_service is None:
            if self._autonomy_job_repository is None:
                return None
            job = await self._autonomy_job_repository.create(
                ScheduledAutonomyJob.build(
                    learner_goal_id=learner_goal_id,
                    job_type=job_type,
                    trigger_source=trigger_source,
                    due_at=due_at,
                    idempotency_key=idempotency_key,
                    payload=dict(payload or {}),
                )
            )
            await self._audit_service.record(
                event_type="autonomy.job.created",
                resource_type="autonomy_job",
                resource_id=job.id,
                actor="system",
                event_data={
                    "autonomy_job_id": job.id,
                    "learner_goal_id": learner_goal_id,
                    "job_type": job_type,
                    "trigger_source": trigger_source,
                    "due_at": due_at.isoformat(),
                    "idempotency_key": idempotency_key,
                },
            )
            return job
        return await self._autonomy_job_service.create_job(
            learner_goal_id=learner_goal_id,
            job_type=job_type,
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload=dict(payload or {}),
        )

    async def _trigger_post_task_reflection(self, task: DailyTask) -> None:
        if self._reflection_service is None:
            return
        goal = await self._require_goal(task.learner_goal_id)
        if task.status in {"failed", "skipped"}:
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="task",
                    target_type="daily_task",
                    target_id=task.id,
                    trigger_source="task_failed" if task.status == "failed" else "task_skipped",
                    reflection_depth=1,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    study_plan_id=task.study_plan_id,
                    source_attempt_id=task.id,
                )
            )
            if await self._has_consecutive_topic_failures(task):
                await self._reflection_service.trigger_reflection(
                    ReflectionTriggerRequest(
                        learner_profile_id=goal.learner_profile_id,
                        learner_goal_id=goal.id,
                        scope="goal",
                        target_type="learner_goal",
                        target_id=goal.id,
                        trigger_source="consecutive_failure_pattern",
                        reflection_depth=1,
                        daily_task_id=task.id,
                        workflow_run_id=task.last_workflow_run_id,
                        study_plan_id=task.study_plan_id,
                        source_attempt_id=task.id,
                    )
                )
        elif task.status == "completed" and task.task_type == "assessment":
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="task",
                    target_type="daily_task",
                    target_id=task.id,
                    trigger_source="assessment_completed",
                    reflection_depth=1,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    study_plan_id=task.study_plan_id,
                    source_attempt_id=task.id,
                )
            )
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="goal",
                    target_type="learner_goal",
                    target_id=goal.id,
                    trigger_source="assessment_completed",
                    reflection_depth=1,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    study_plan_id=task.study_plan_id,
                    source_attempt_id=task.id,
                )
            )

    async def _has_consecutive_topic_failures(self, task: DailyTask) -> bool:
        if self._task_attempt_repository is None:
            return False
        attempts = await self._task_attempt_repository.list_recent_by_goal(task.learner_goal_id, limit=5)
        topic_attempts = [item for item in attempts if item.topic_focus == task.topic_focus][:3]
        return len([item for item in topic_attempts if item.outcome_status in {"failed", "skipped"}]) >= 2

    async def _trigger_workflow_failure_reflection(
        self,
        *,
        goal_learner_profile_id: str,
        goal_id: str,
        workflow_run_id: str,
        daily_task_id: str | None = None,
        study_plan_id: str | None = None,
    ) -> None:
        if self._reflection_service is None:
            return
        await self._reflection_service.trigger_reflection(
            ReflectionTriggerRequest(
                learner_profile_id=goal_learner_profile_id,
                learner_goal_id=goal_id,
                scope="task" if daily_task_id is not None else "goal",
                target_type="workflow_run",
                target_id=workflow_run_id,
                trigger_source="workflow_failed",
                reflection_depth=1,
                daily_task_id=daily_task_id,
                workflow_run_id=workflow_run_id,
                study_plan_id=study_plan_id,
                source_attempt_id=workflow_run_id,
            )
        )

    async def _derive_replan_mode(self, task: DailyTask) -> str:
        skill_binding = await self._get_skill_binding(task.learner_goal_id, "replan", topic_key=task.topic_focus, task_type=task.task_type)
        if skill_binding is not None and skill_binding.runtime_directives.get("replan_bias") in {"normal", "aggressive"}:
            return "full" if str(skill_binding.runtime_directives["replan_bias"]) == "aggressive" else "partial"
        rollout_overlay = await self._get_rollout_overlay_payload(task.learner_goal_id, "replan")
        if rollout_overlay is not None and rollout_overlay.get("replan_bias") in {"normal", "aggressive"}:
            if str(rollout_overlay["replan_bias"]) == "aggressive":
                return "full"
            return "partial"
        if self._strategy_card_service is not None:
            strategy = await self._strategy_card_service.get_active(task.learner_goal_id)
            if strategy is not None:
                if strategy.replan_bias == "conservative":
                    return "partial"
                if strategy.replan_bias == "aggressive":
                    return "full"
        return "full"

    async def _should_schedule_assessment(self, task: DailyTask) -> bool:
        if task.task_type == "assessment":
            return False
        mastery = await self._get_topic_mastery(task.learner_goal_id, task.topic_focus)
        if mastery is None:
            return False
        skill_binding = await self._get_skill_binding(task.learner_goal_id, "assessment_generation", topic_key=task.topic_focus, task_type=task.task_type)
        if skill_binding is not None:
            assessment_bias = skill_binding.runtime_directives.get("assessment_bias")
            if assessment_bias == "early":
                return mastery.mastery_score < 0.8 or mastery.evidence_count % 3 == 0
            if assessment_bias == "standard":
                return mastery.mastery_score < 0.7 or mastery.evidence_count % 4 == 0
        rollout_overlay = await self._get_rollout_overlay_payload(task.learner_goal_id, "assessment_generation")
        if rollout_overlay is not None:
            if rollout_overlay.get("assessment_bias") == "early":
                return mastery.mastery_score < 0.8 or mastery.evidence_count % 3 == 0
            if rollout_overlay.get("assessment_bias") == "standard":
                return mastery.mastery_score < 0.7 or mastery.evidence_count % 4 == 0
        if self._strategy_card_service is not None:
            strategy = await self._strategy_card_service.get_active(task.learner_goal_id)
            if strategy is not None:
                if strategy.assessment_bias == "early":
                    return mastery.mastery_score < 0.8 or mastery.evidence_count % 3 == 0
                if strategy.assessment_bias == "delayed":
                    return mastery.mastery_score < 0.6 or mastery.evidence_count % 5 == 0
        return mastery.mastery_score < 0.7 or mastery.evidence_count % 4 == 0

    async def _get_topic_mastery(self, learner_goal_id: str, topic_key: str) -> LearnerTopicMastery | None:
        if self._learner_topic_mastery_repository is None:
            return None
        return await self._learner_topic_mastery_repository.get_by_goal_and_topic(learner_goal_id, topic_key)

    async def _review_intervals(self, learner_goal_id: str, mastery: LearnerTopicMastery | None) -> list[int]:
        score = mastery.mastery_score if mastery is not None else 0.5
        confidence = mastery.confidence if mastery is not None else 0.5
        evidence_count = mastery.evidence_count if mastery is not None else 0
        recent_failures = await self._recent_topic_failure_count(
            learner_goal_id=learner_goal_id,
            topic_key=mastery.topic_key if mastery is not None else None,
        )
        tier_order = ["remedial", "reinforced", "standard", "stable", "relaxed"]
        tier_to_intervals = {
            "remedial": [1, 2, 3],
            "reinforced": [1, 2, 5],
            "standard": [1, 3, 7],
            "stable": [2, 5, 10],
            "relaxed": [3, 7, 14],
        }
        tier = "standard"
        if recent_failures >= 2 or score < 0.45 or confidence < 0.45:
            tier = "remedial"
        elif recent_failures >= 1 or score < 0.65:
            tier = "reinforced"
        elif score >= 0.85 and confidence >= 0.75 and evidence_count >= 4 and recent_failures == 0:
            tier = "relaxed"
        elif score >= 0.75 and confidence >= 0.65:
            tier = "stable"
        skill_binding = await self._get_skill_binding(
            learner_goal_id,
            "review_scheduling",
            topic_key=mastery.topic_key if mastery is not None else None,
            task_type="review",
        )
        if skill_binding is not None and skill_binding.runtime_directives.get("review_bias") == "intensive":
            tier = tier_order[max(0, tier_order.index(tier) - 1)]
        rollout_overlay = await self._get_rollout_overlay_payload(learner_goal_id, "review_scheduling")
        if rollout_overlay is not None:
            if rollout_overlay.get("review_bias") == "intensive":
                tier = tier_order[max(0, tier_order.index(tier) - 1)]
            if rollout_overlay.get("review_bias") == "normal":
                tier = tier
        if self._strategy_card_service is not None:
            strategy = await self._strategy_card_service.get_active(learner_goal_id)
            if strategy is not None:
                if strategy.review_bias == "intensive":
                    tier = tier_order[max(0, tier_order.index(tier) - 1)]
                if strategy.review_bias == "light":
                    tier = tier_order[min(len(tier_order) - 1, tier_order.index(tier) + 1)]
        return tier_to_intervals[tier]

    async def _get_rollout_overlay_payload(self, learner_goal_id: str, surface: str) -> dict[str, object] | None:
        if self._rollout_resolver is None:
            return None
        overlay = await self._rollout_resolver.get_active_overlay(
            learner_goal_id=learner_goal_id,
            surface=surface,
            include_staged=True,
        )
        if overlay is None:
            return None
        return dict(overlay.payload)

    async def _get_skill_binding(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        topic_key: str | None,
        task_type: str | None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> ActiveGoalSkillBinding | None:
        if self._goal_skill_binding_resolver is None:
            return None
        return await self._goal_skill_binding_resolver.get_active_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    async def _ensure_daily_materialization_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
        days_offset: int = 0,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        availability = await self._get_goal_availability_entity(learner_goal_id)
        timezone_name = self._validate_timezone(availability.timezone if availability is not None else None) or "UTC"
        zone = ZoneInfo(timezone_name)
        now_local = datetime.now(zone)
        target_day = now_local.date() + timedelta(days=days_offset)
        idempotency_key = f"{learner_goal_id}:daily_task_materialization:{target_day.isoformat()}:{timezone_name}"
        existing = await self._autonomy_job_repository.list_active_by_goal(learner_goal_id, job_types={"daily_task_materialization"})
        for job in existing:
            if job.idempotency_key == idempotency_key:
                return job
        for job in existing:
            cancelled = job.cancel(error_code="rescheduled")
            await self._autonomy_job_repository.update(cancelled)
            await self._audit_service.record(
                event_type="autonomy.job.cancelled",
                resource_type="autonomy_job",
                resource_id=cancelled.id,
                actor="system",
                event_data={
                    "autonomy_job_id": cancelled.id,
                    "learner_goal_id": learner_goal_id,
                    "job_type": cancelled.job_type,
                    "reason": "rescheduled",
                },
            )
        due_at, scheduled_local_time = self._compute_materialization_due_at(
            availability=availability,
            timezone_name=timezone_name,
            target_day=target_day,
        )
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="daily_task_materialization",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload={
                "window_days": 3,
                "target_local_date": target_day.isoformat(),
                "target_timezone": timezone_name,
                "scheduled_local_time": scheduled_local_time,
            },
        )

    async def _ensure_milestone_jobs(self, learner_goal_id: str, study_plan_id: str) -> None:
        if self._autonomy_job_repository is None:
            return
        stages = await self._plan_stage_repository.list_by_plan(study_plan_id)
        tasks = await self._daily_task_repository.list_by_goal(learner_goal_id)
        for stage in stages:
            stage_tasks = [
                task
                for task in tasks
                if task.plan_stage_id == stage.id and task.task_type in {"lesson", "practice", "repair"}
            ]
            if not stage_tasks:
                continue
            completed_count = len([task for task in stage_tasks if task.status == "completed"])
            if completed_count < max(1, ceil(len(stage_tasks) / 2)) and date.today() < stage.end_date:
                continue
            if any(task.task_type == "milestone" and task.plan_stage_id == stage.id and task.status != "superseded" for task in tasks):
                continue
            existing_attempts = len(
                [task for task in tasks if task.task_type == "milestone" and task.plan_stage_id == stage.id]
            )
            due_day = date.today() if completed_count >= max(1, ceil(len(stage_tasks) / 2)) else max(date.today(), stage.end_date)
            await self._schedule_autonomy_job(
                learner_goal_id=learner_goal_id,
                job_type="milestone_generation",
                trigger_source="stage_progress",
                due_at=datetime.combine(due_day, datetime.min.time(), tzinfo=timezone.utc),
                idempotency_key=f"{learner_goal_id}:milestone:{stage.id}:attempt:{existing_attempts + 1}",
                payload={"stage_id": stage.id, "attempt_index": existing_attempts + 1},
            )

    async def _derive_task_evidence(self, task: DailyTask) -> None:
        if self._reflection_evidence_service is None:
            return
        goal = await self._require_goal(task.learner_goal_id)
        attempt = None
        if self._task_attempt_repository is not None:
            attempts = await self._task_attempt_repository.list_recent_by_goal(task.learner_goal_id, limit=3)
            attempt = next((item for item in attempts if item.daily_task_id == task.id), None)
        await self._reflection_evidence_service.derive_from_task(
            learner_profile_id=goal.learner_profile_id,
            learner_goal_id=goal.id,
            task=task,
            attempt=attempt,
        )

    async def _evaluate_recent_reflection_outcomes(self, task: DailyTask) -> None:
        if self._reflection_service is None or self._reflection_outcome_service is None:
            return
        reflections = await self._reflection_service.list_task_reflections(task_id=task.id, limit=5, offset=0)
        for item in reflections.items:
            record = await self._reflection_service.get_record(item.id)
            topic_key = str((record.evidence_payload.get("task") or {}).get("topic_focus") or "") or None
            evaluation = await self._reflection_outcome_service.evaluate(
                reflection=record,
                topic_key=topic_key,
            )
            await self._reflection_service.apply_outcome_feedback(
                reflection=record,
                evaluation=evaluation,
            )

    def _register_internal_tools(self) -> None:
        if self._internal_tool_registry is None:
            return
        self._internal_tool_registry.register(
            ToolSpec(
                name="review_scheduling",
                description="Create spaced review tasks for a completed task.",
                risk_level="low",
                handler=self._tool_review_scheduling,
            )
        )
        self._internal_tool_registry.register(
            ToolSpec(
                name="assessment_generation",
                description="Create an assessment task for a goal/topic.",
                risk_level="low",
                handler=self._tool_assessment_generation,
            )
        )
        self._internal_tool_registry.register(
            ToolSpec(
                name="partial_replan",
                description="Create a repair task from a source task.",
                risk_level="medium",
                handler=self._tool_partial_replan,
            )
        )

    async def _tool_review_scheduling(self, payload: dict[str, object]) -> dict[str, object] | None:
        source_task_id = str(payload.get("source_task_id") or "")
        if not source_task_id:
            raise ValidationError("Missing source_task_id for review_scheduling tool.")
        source_task = await self._require_task(source_task_id)
        goal = await self._require_goal(source_task.learner_goal_id)
        existing_reviews = await self._daily_task_repository.list_by_source_task(source_task.id)
        existing_due_dates = {task.scheduled_for for task in existing_reviews}
        mastery = await self._get_topic_mastery(goal.id, source_task.topic_focus)
        intervals = await self._review_intervals(goal.id, mastery)
        review_tasks: list[DailyTask] = []
        for offset in intervals:
            scheduled_for = source_task.due_on + timedelta(days=offset)
            if scheduled_for > goal.deadline_date or scheduled_for in existing_due_dates:
                continue
            review_tasks.append(
                DailyTask.build(
                    learner_goal_id=goal.id,
                    study_plan_id=source_task.study_plan_id,
                    plan_stage_id=source_task.plan_stage_id,
                    task_origin="review_scheduler",
                    task_type="review",
                    execution_mode="quiz",
                    title=f"Review: {source_task.topic_focus}",
                    instructions=f"Review {source_task.topic_focus} and reinforce the key idea.",
                    topic_focus=source_task.topic_focus,
                    difficulty=source_task.difficulty or "medium",
                    question_count=source_task.question_count or 3,
                    estimated_minutes=max(15, source_task.estimated_minutes // 2),
                    scheduled_for=scheduled_for,
                    due_on=scheduled_for,
                    source_task_id=source_task.id,
                )
            )
        if review_tasks:
            await self._daily_task_repository.create_many(review_tasks)
        return {"created_task_ids": [task.id for task in review_tasks]}

    async def _tool_assessment_generation(self, payload: dict[str, object]) -> dict[str, object] | None:
        learner_goal_id = str(payload.get("learner_goal_id") or "")
        topic_focus = str(payload.get("topic_focus") or "")
        if not learner_goal_id:
            raise ValidationError("Missing learner_goal_id for assessment_generation tool.")
        goal = await self._require_goal(learner_goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is None:
            return None
        assessment_task = DailyTask.build(
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id,
            plan_stage_id=None,
            task_origin="assessment_scheduler",
            task_type="assessment",
            execution_mode="quiz",
            title=f"Assessment: {topic_focus or goal.subject}",
            instructions=f"Assess mastery of {topic_focus or goal.subject}.",
            topic_focus=topic_focus or goal.subject,
            difficulty="medium",
            question_count=5,
            estimated_minutes=30,
            scheduled_for=date.today() + timedelta(days=1),
            due_on=date.today() + timedelta(days=1),
        )
        await self._daily_task_repository.create_many([assessment_task])
        return {"created_task_ids": [assessment_task.id]}

    async def _tool_partial_replan(self, payload: dict[str, object]) -> dict[str, object] | None:
        source_task_id = str(payload.get("source_task_id") or "")
        if not source_task_id:
            raise ValidationError("Missing source_task_id for partial_replan tool.")
        source_task = await self._require_task(source_task_id)
        repair_task = DailyTask.build(
            learner_goal_id=source_task.learner_goal_id,
            study_plan_id=source_task.study_plan_id,
            plan_stage_id=source_task.plan_stage_id,
            task_origin="replan_scheduler",
            task_type="repair",
            execution_mode=source_task.execution_mode,
            title=f"Repair: {source_task.topic_focus}",
            instructions=f"Repair the gap around {source_task.topic_focus}.",
            topic_focus=source_task.topic_focus,
            difficulty=source_task.difficulty or "medium",
            question_count=source_task.question_count,
            estimated_minutes=max(15, source_task.estimated_minutes),
            scheduled_for=max(date.today() + timedelta(days=1), source_task.due_on + timedelta(days=1)),
            due_on=max(date.today() + timedelta(days=1), source_task.due_on + timedelta(days=1)),
            source_task_id=source_task.id,
        )
        await self._daily_task_repository.create_many([repair_task])
        return {"created_task_ids": [repair_task.id]}

    async def _get_goal_availability_entity(self, goal_id: str) -> LearnerAvailability | None:
        if self._learner_availability_repository is None:
            return None
        return await self._learner_availability_repository.get_by_goal(goal_id)

    async def _recent_topic_failure_count(self, *, learner_goal_id: str, topic_key: str | None) -> int:
        if self._task_attempt_repository is None or not topic_key:
            return 0
        attempts = await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=10)
        topic_attempts = [item for item in attempts if item.topic_focus == topic_key][:3]
        return len([item for item in topic_attempts if item.outcome_status in {"failed", "skipped"}])

    async def _resolve_materialization_target(self, learner_goal_id: str, job: ScheduledAutonomyJob) -> tuple[date, str]:
        payload_date = str(job.payload.get("target_local_date") or "")
        payload_timezone = self._validate_timezone(str(job.payload.get("target_timezone") or "") or None)
        if payload_date:
            return date.fromisoformat(payload_date), payload_timezone or "UTC"
        availability = await self._get_goal_availability_entity(learner_goal_id)
        timezone_name = payload_timezone or self._validate_timezone(availability.timezone if availability is not None else None) or "UTC"
        zone = ZoneInfo(timezone_name)
        return datetime.now(zone).date(), timezone_name

    def _compute_materialization_due_at(
        self,
        *,
        availability: LearnerAvailability | None,
        timezone_name: str,
        target_day: date,
    ) -> tuple[datetime, str]:
        zone = ZoneInfo(timezone_name)
        local_due = datetime.combine(target_day, datetime.min.time(), tzinfo=zone).replace(hour=0, minute=5)
        scheduled_local_time = "00:05"
        if availability is not None:
            for item in availability.time_windows:
                start = str(item.get("start") or "").strip()
                if len(start) == 5 and start[2] == ":":
                    hour = int(start[:2])
                    minute = int(start[3:])
                    local_due = datetime.combine(target_day, datetime.min.time(), tzinfo=zone).replace(
                        hour=hour,
                        minute=minute,
                    ) - timedelta(minutes=30)
                    scheduled_local_time = f"{hour:02d}:{minute:02d}"
                    break
        now_local = datetime.now(zone)
        if target_day == now_local.date() and local_due < now_local:
            local_due = now_local
        return local_due.astimezone(timezone.utc), scheduled_local_time

    async def _blocked_stage_position(self, study_plan_id: str, learner_goal_id: str) -> int | None:
        stages = await self._plan_stage_repository.list_by_plan(study_plan_id)
        tasks = await self._daily_task_repository.list_by_goal(learner_goal_id)
        stage_position_by_id = {stage.id: stage.position for stage in stages}
        blocked_positions = [
            stage_position_by_id[task.plan_stage_id]
            for task in tasks
            if task.task_type == "milestone"
            and task.plan_stage_id in stage_position_by_id
            and task.status not in {"completed", "superseded"}
        ]
        return min(blocked_positions) if blocked_positions else None

    async def _suppress_downstream_stage_tasks(
        self,
        goal_id: str,
        study_plan_id: str,
        *,
        blocked_after_position: int,
    ) -> None:
        stages = await self._plan_stage_repository.list_by_plan(study_plan_id)
        stage_position_by_id = {stage.id: stage.position for stage in stages}
        tasks = await self._daily_task_repository.list_by_goal(goal_id)
        for task in tasks:
            if task.plan_stage_id is None:
                continue
            if stage_position_by_id.get(task.plan_stage_id, 0) <= blocked_after_position:
                continue
            if task.status not in {"pending", "in_progress"}:
                continue
            superseded = task.with_status("superseded", result_note="blocked_by_milestone_gate")
            await self._daily_task_repository.update(superseded)
            await self._audit_service.record(
                event_type="daily_task.superseded",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "learner_goal_id": goal_id,
                    "reason": "blocked_by_milestone_gate",
                },
            )

    async def _schedule_periodic_goal_reflection_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id,
            job_types={"goal_reflection_periodic"},
        )
        if existing:
            return existing[0]
        due_at = datetime.now(timezone.utc) + timedelta(days=2)
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="goal_reflection_periodic",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=f"{learner_goal_id}:goal_reflection_periodic:{due_at.date().isoformat()}",
            payload={"cooldown_days": 2},
        )

    async def _schedule_outcome_evaluation_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id,
            job_types={"reflection_outcome_evaluation"},
        )
        if existing:
            return existing[0]
        due_at = datetime.now(timezone.utc)
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="reflection_outcome_evaluation",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=f"{learner_goal_id}:reflection_outcome_evaluation:{due_at.isoformat()}",
            payload={},
        )

    @staticmethod
    def _validate_timezone(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Unsupported learner timezone.") from exc
        return normalized

    @staticmethod
    def _attempt_score(status: str) -> float:
        if status == "completed":
            return 1.0
        if status == "skipped":
            return 0.4
        if status == "failed":
            return 0.0
        return 0.5

    @staticmethod
    def _to_datetime(value: date) -> datetime:
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

    async def _schedule_review_tasks(self, source_task: DailyTask) -> None:
        if source_task.task_type == "review":
            return
        goal = await self._require_goal(source_task.learner_goal_id)
        skill_resolution = await self._resolve_review_skill_for_runtime(
            goal=goal,
            source_task=source_task,
        )
        skill_binding = await self._get_skill_binding(
            goal.id,
            "review_scheduling",
            topic_key=source_task.topic_focus,
            task_type="review",
            trigger_source="task_completed",
            include_staged=True,
        )
        run = await self._workflow_run_service.create_run(
            workflow_type="review_scheduling",
            trigger_source="task_completed",
            learner_goal_id=goal.id,
            study_plan_id=source_task.study_plan_id,
            daily_task_id=source_task.id,
        )
        try:
            existing_reviews = await self._daily_task_repository.list_by_source_task(source_task.id)
            existing_due_dates = {task.scheduled_for for task in existing_reviews}
            review_tasks: list[DailyTask] = []
            for offset in (1, 3, 7):
                scheduled_for = source_task.due_on + timedelta(days=offset)
                if scheduled_for > goal.deadline_date or scheduled_for in existing_due_dates:
                    continue
                review_tasks.append(
                    DailyTask.build(
                        learner_goal_id=goal.id,
                        study_plan_id=source_task.study_plan_id,
                        plan_stage_id=source_task.plan_stage_id,
                        task_origin="review_scheduler",
                        task_type="review",
                        execution_mode="quiz",
                        title=f"Review: {source_task.topic_focus}",
                        instructions=f"Review {source_task.topic_focus} and reinforce the key idea.",
                        topic_focus=source_task.topic_focus,
                        difficulty=source_task.difficulty or "medium",
                        question_count=source_task.question_count or 3,
                        estimated_minutes=max(15, source_task.estimated_minutes // 2),
                        scheduled_for=scheduled_for,
                        due_on=scheduled_for,
                        source_task_id=source_task.id,
                    )
                )
            if review_tasks:
                await self._daily_task_repository.create_many(review_tasks)
                for task in review_tasks:
                    await self._audit_service.record(
                        event_type="daily_task.created",
                        resource_type="daily_task",
                        resource_id=task.id,
                        actor="system",
                        event_data={
                            "daily_task_id": task.id,
                            "learner_goal_id": goal.id,
                            "study_plan_id": task.study_plan_id,
                            "task_type": task.task_type,
                            "scheduled_for": task.scheduled_for.isoformat(),
                            "source_task_id": source_task.id,
                        },
                    )
            await self._audit_service.record(
                event_type="review.tasks.scheduled",
                resource_type="daily_task",
                resource_id=source_task.id,
                actor="system",
                event_data={
                    "source_daily_task_id": source_task.id,
                    "created_review_task_ids": [task.id for task in review_tasks],
                },
            )
            await self._record_review_skill_usage(
                goal=goal,
                source_task=source_task,
                workflow_run_id=run.id,
                outcome_status="completed",
                output_summary=f"{len(review_tasks)} review tasks",
                resolution=skill_resolution,
                metadata=(
                    skill_binding.with_usage_metadata(
                        {"created_review_task_ids": [task.id for task in review_tasks]},
                        skill_name="schedule_review",
                    )
                    if skill_binding is not None
                    else {"created_review_task_ids": [task.id for task in review_tasks]}
                ),
            )
            run = await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="daily_task",
                result_resource_ids=[task.id for task in review_tasks],
            )
        except Exception as exc:
            await self._record_review_skill_usage(
                goal=goal,
                source_task=source_task,
                workflow_run_id=run.id,
                outcome_status="failed",
                error_code=type(exc).__name__,
                resolution=skill_resolution,
                metadata=(
                    skill_binding.with_usage_metadata(
                        {"error": str(exc)},
                        skill_name="schedule_review",
                    )
                    if skill_binding is not None
                    else {"error": str(exc)}
                ),
            )
            await self._workflow_run_service.fail_run(run=run, error_code=type(exc).__name__)
            raise

    async def _resolve_review_skill_for_runtime(
        self,
        *,
        goal: LearnerGoal,
        source_task: DailyTask,
    ) -> SkillResolution | None:
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name="schedule_review",
            surface="review_scheduling",
            resource_id=source_task.id or goal.id,
        )

    async def _record_review_skill_usage(
        self,
        *,
        goal: LearnerGoal,
        source_task: DailyTask,
        workflow_run_id: str,
        outcome_status: str,
        output_summary: str | None = None,
        error_code: str | None = None,
        resolution: SkillResolution | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self._skill_usage_service is None:
            return
        await self._skill_usage_service.record_usage(
            skill_name="schedule_review",
            surface="review_scheduling",
            outcome_status=outcome_status,
            learner_profile_id=goal.learner_profile_id,
            learner_goal_id=goal.id,
            daily_task_id=source_task.id,
            workflow_run_id=workflow_run_id,
            topic_key=source_task.topic_focus,
            trigger_source="task_completed",
            input_summary=source_task.topic_focus,
            output_summary=output_summary,
            error_code=error_code,
            resolution=resolution,
            metadata=metadata,
        )

    async def _extend_active_plan(self, goal_id: str) -> None:
        goal = await self._require_goal(goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal_id)
        if active_plan is None:
            return
        stages = await self._plan_stage_repository.list_by_plan(active_plan.id)
        tasks = await self._daily_task_repository.list_by_goal(goal_id)
        stage_map = {stage.position: stage.id for stage in stages}
        new_tasks, target_until = await self._planner_service.extend_plan_window(
            goal=goal,
            active_plan=active_plan,
            existing_tasks=tasks,
            stage_id_by_position=stage_map,
        )
        if not new_tasks and target_until == active_plan.materialized_until_date:
            return
        if new_tasks:
            await self._daily_task_repository.create_many(new_tasks)
            for task in new_tasks:
                await self._audit_service.record(
                    event_type="daily_task.created",
                    resource_type="daily_task",
                    resource_id=task.id,
                    actor="system",
                    event_data={
                        "daily_task_id": task.id,
                        "learner_goal_id": goal.id,
                        "study_plan_id": task.study_plan_id,
                        "task_type": task.task_type,
                        "scheduled_for": task.scheduled_for.isoformat(),
                    },
                )
        if target_until != active_plan.materialized_until_date:
            await self._study_plan_repository.update(active_plan.with_materialized_until(target_until))

    async def _require_goal(self, goal_id: str):
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    async def _require_task(self, task_id: str):
        task = await self._daily_task_repository.get_by_id(task_id)
        if task is None:
            raise NotFoundError(f"Daily task '{task_id}' was not found.")
        return task

    async def _require_goal_autonomy_state(self, goal_id: str) -> GoalAutonomyState:
        if self._goal_autonomy_state_repository is None:
            raise NotFoundError(f"Autonomy state for goal '{goal_id}' was not found.")
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            raise NotFoundError(f"Autonomy state for goal '{goal_id}' was not found.")
        return state

    async def _to_plan_response(self, plan: StudyPlan) -> StudyPlanResponse:
        stages = await self._plan_stage_repository.list_by_plan(plan.id)
        return StudyPlanResponse.model_validate(
            {
                "id": plan.id,
                "learner_goal_id": plan.learner_goal_id,
                "version": plan.version,
                "status": plan.status,
                "trigger_source": plan.trigger_source,
                "plan_summary": plan.plan_summary,
                "blueprint_payload": plan.blueprint_payload,
                "materialized_until_date": plan.materialized_until_date,
                "supersedes_plan_id": plan.supersedes_plan_id,
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
                "stages": [
                    {
                        "id": stage.id,
                        "study_plan_id": stage.study_plan_id,
                        "position": stage.position,
                        "title": stage.title,
                        "objective": stage.objective,
                        "focus_topics": stage.focus_topics,
                        "start_date": stage.start_date,
                        "end_date": stage.end_date,
                    }
                    for stage in stages
                ],
            }
        )
