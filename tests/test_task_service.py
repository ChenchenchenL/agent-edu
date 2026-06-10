from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import httpx

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.reflective_memory import ReflectiveMemoryService
from agent_core.application.services.reflection import ReflectionService
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_governance import ReflectionGovernanceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.session import SessionService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.task import AutonomousTaskService
from agent_core.application.services.tool_plan_runtime import ToolPlanRuntimeExecutor
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.application.tools.registry import HttpToolSpec, InternalToolRegistry, ToolExecutionRequest
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.planning import DailyTask, PlanStage, StudyPlan, WorkflowRun
from agent_core.domain.entities.autonomy import GoalAutonomyState, LearnerAvailability, LearnerTopicMastery, ScheduledAutonomyJob
from agent_core.domain.entities.reflection_closure import ReflectionProposal, ReflectionProposalEvaluation, ReflectionProposalRollout
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.domain.schemas.planning import UpdateDailyTaskStatusRequest
from agent_core.infrastructure.llm.mock_provider import MockLLMProvider


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.nested_transactions = 0

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1

    def begin_nested(self):
        self.nested_transactions += 1
        return FakeTransaction()


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubReflectionRecordRepository:
    def __init__(self):
        self.records: dict[str, ReflectionRecord] = {}

    async def create(self, entity: ReflectionRecord):
        self.records[entity.id] = entity
        return entity

    async def get_by_dedupe_key(self, dedupe_key: str):
        for item in self.records.values():
            if item.dedupe_key == dedupe_key:
                return item
        return None

    async def get_by_id(self, reflection_id: str):
        return self.records.get(reflection_id)

    async def update(self, entity: ReflectionRecord):
        self.records[entity.id] = entity

    async def get_latest_by_aggregation_key(self, aggregation_key: str):
        matches = [item for item in self.records.values() if item.aggregation_key == aggregation_key]
        return matches[-1] if matches else None

    async def list_by_goal(self, learner_goal_id: str, **kwargs):
        return [item for item in self.records.values() if item.learner_goal_id == learner_goal_id]

    async def count_by_goal(self, learner_goal_id: str, **kwargs):
        return len([item for item in self.records.values() if item.learner_goal_id == learner_goal_id])

    async def list_by_task(self, daily_task_id: str, **kwargs):
        return [item for item in self.records.values() if item.daily_task_id == daily_task_id]

    async def count_by_task(self, daily_task_id: str, **kwargs):
        return len([item for item in self.records.values() if item.daily_task_id == daily_task_id])

    async def list_review_queue(self, **kwargs):
        return list(self.records.values())

    async def count_review_queue(self, **kwargs):
        return len(self.records)


class StubReflectionActionRepository:
    def __init__(self):
        self.actions: dict[str, ReflectionAction] = {}

    async def create(self, entity: ReflectionAction):
        self.actions[entity.id] = entity

    async def update(self, entity: ReflectionAction):
        self.actions[entity.id] = entity

    async def list_by_reflection(self, reflection_record_id: str):
        return [item for item in self.actions.values() if item.reflection_record_id == reflection_record_id]


class StubReviewDecisionRepository:
    def __init__(self):
        self.items = []

    async def create(self, entity):
        self.items.append(entity)

    async def list_by_reflection(self, reflection_record_id: str):
        return [item for item in self.items if item.reflection_record_id == reflection_record_id]


class StubOutcomeRepository:
    def __init__(self):
        self.items = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_reflection(self, reflection_record_id: str):
        for item in self.items.values():
            if item.reflection_record_id == reflection_record_id:
                return item
        return None

    async def update(self, entity):
        self.items[entity.id] = entity

    async def list_pending(self, *, learner_goal_id: str | None = None, limit: int = 20):
        items = [
            item
            for item in self.items.values()
            if item.evaluation_status == "pending"
            and (learner_goal_id is None or item.learner_goal_id == learner_goal_id)
        ]
        return items[:limit]


class StubStrategyCardRepository:
    def __init__(self):
        self.cards = {}

    async def create(self, entity):
        self.cards[entity.id] = entity

    async def get_active_by_goal(self, learner_goal_id: str):
        active = [item for item in self.cards.values() if item.learner_goal_id == learner_goal_id and item.status == "active"]
        return active[-1] if active else None

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.cards.values() if item.learner_goal_id == learner_goal_id]

    async def update(self, entity):
        self.cards[entity.id] = entity


class StubReflectiveMemoryRepository:
    def __init__(self):
        self.items = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def list_by_goal(self, learner_goal_id: str, **kwargs):
        return [item for item in self.items.values() if item.learner_goal_id == learner_goal_id]

    async def update(self, entity):
        self.items[entity.id] = entity


class StubReflectionEvidenceRepository:
    def __init__(self):
        self.items = []

    async def create(self, entity):
        self.items.append(entity)

    async def list_by_goal(self, learner_goal_id: str, **kwargs):
        return [item for item in self.items if item.learner_goal_id == learner_goal_id]


class StubLearnerProfileRepository:
    def __init__(self, profiles: list[LearnerProfile]):
        self.profiles = {item.id: item for item in profiles}

    async def create(self, entity):
        self.profiles[entity.id] = entity

    async def get_by_id(self, profile_id: str):
        return self.profiles.get(profile_id)


class StubGoalRepository:
    def __init__(self, goal: LearnerGoal):
        self.goal = goal

    async def get_by_id(self, goal_id: str):
        if self.goal.id == goal_id:
            return self.goal
        return None


class StubStudyPlanRepository:
    def __init__(self):
        self.plans: dict[str, StudyPlan] = {}

    async def create(self, entity: StudyPlan):
        self.plans[entity.id] = entity

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.plans.values() if item.learner_goal_id == learner_goal_id]

    async def get_by_id(self, plan_id: str):
        return self.plans.get(plan_id)

    async def get_active_by_goal(self, learner_goal_id: str):
        for item in sorted(self.plans.values(), key=lambda plan: plan.version, reverse=True):
            if item.learner_goal_id == learner_goal_id and item.status == "active":
                return item
        return None

    async def update(self, entity: StudyPlan):
        self.plans[entity.id] = entity


class StubPlanStageRepository:
    def __init__(self):
        self.stages: dict[str, PlanStage] = {}

    async def create_many(self, entities: list[PlanStage]):
        for item in entities:
            self.stages[item.id] = item

    async def list_by_plan(self, study_plan_id: str):
        return [item for item in self.stages.values() if item.study_plan_id == study_plan_id]


class StubDailyTaskRepository:
    def __init__(self):
        self.tasks: dict[str, DailyTask] = {}

    async def create_many(self, entities: list[DailyTask]):
        for item in entities:
            self.tasks[item.id] = item

    async def get_by_id(self, task_id: str):
        return self.tasks.get(task_id)

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.tasks.values() if item.learner_goal_id == learner_goal_id]

    async def list_filtered(self, *, learner_goal_id: str, statuses=None, scheduled_from=None, scheduled_to=None, task_type=None, limit=None):
        items = [item for item in self.tasks.values() if item.learner_goal_id == learner_goal_id]
        if statuses is not None:
            items = [item for item in items if item.status in statuses]
        if scheduled_from is not None:
            items = [item for item in items if item.scheduled_for >= scheduled_from.date()]
        if scheduled_to is not None:
            items = [item for item in items if item.scheduled_for <= scheduled_to.date()]
        if task_type is not None:
            items = [item for item in items if item.task_type == task_type]
        items.sort(key=lambda item: (item.scheduled_for, item.created_at, item.id))
        return items if limit is None else items[:limit]

    async def list_active_future_by_goal(self, learner_goal_id: str):
        return [item for item in self.tasks.values() if item.learner_goal_id == learner_goal_id and item.status in {"pending", "in_progress"}]

    async def list_future_by_plan(self, study_plan_id: str):
        return [item for item in self.tasks.values() if item.study_plan_id == study_plan_id and item.status in {"pending", "in_progress"}]

    async def list_by_source_task(self, source_task_id: str):
        return [item for item in self.tasks.values() if item.source_task_id == source_task_id]

    async def update(self, entity: DailyTask):
        self.tasks[entity.id] = entity

    async def bulk_mark_superseded(self, study_plan_id: str):
        for task_id, task in list(self.tasks.items()):
            if task.study_plan_id == study_plan_id and task.status in {"pending", "in_progress"}:
                self.tasks[task_id] = task.with_status("superseded", result_note=task.result_note)


class FailingReviewTaskRepository(StubDailyTaskRepository):
    async def create_many(self, entities: list[DailyTask]):
        if any(item.task_origin == "review_scheduler" for item in entities):
            raise RuntimeError("review scheduling failed")
        await super().create_many(entities)


class StubWorkflowRunRepository:
    def __init__(self):
        self.runs: dict[str, WorkflowRun] = {}

    async def create(self, entity: WorkflowRun):
        self.runs[entity.id] = entity

    async def update(self, entity: WorkflowRun):
        self.runs[entity.id] = entity

    async def get_by_id(self, run_id: str):
        return self.runs.get(run_id)

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.runs.values() if item.learner_goal_id == learner_goal_id]

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 10):
        runs = [item for item in self.runs.values() if item.learner_goal_id == learner_goal_id]
        return runs[:limit]


class StubGoalAutonomyStateRepository:
    def __init__(self):
        self.states: dict[str, GoalAutonomyState] = {}

    async def create(self, entity: GoalAutonomyState):
        self.states[entity.learner_goal_id] = entity

    async def get_by_goal(self, learner_goal_id: str):
        return self.states.get(learner_goal_id)

    async def update(self, entity: GoalAutonomyState):
        self.states[entity.learner_goal_id] = entity


class StubLearnerAvailabilityRepository:
    def __init__(self):
        self.items: dict[str, LearnerAvailability] = {}

    async def upsert(self, entity: LearnerAvailability):
        self.items[entity.learner_goal_id] = entity

    async def get_by_goal(self, learner_goal_id: str):
        return self.items.get(learner_goal_id)


class StubTaskAttemptRepository:
    def __init__(self):
        self.items = []

    async def create(self, entity):
        self.items.append(entity)

    async def get_by_id(self, attempt_id: str):
        for item in self.items:
            if item.id == attempt_id:
                return item
        return None

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 10):
        items = [item for item in self.items if item.learner_goal_id == learner_goal_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]


class StubLearnerTopicMasteryRepository:
    def __init__(self):
        self.items: dict[tuple[str, str], LearnerTopicMastery] = {}

    async def get_by_goal_and_topic(self, learner_goal_id: str, topic_key: str):
        return self.items.get((learner_goal_id, topic_key))

    async def upsert(self, entity: LearnerTopicMastery):
        self.items[(entity.learner_goal_id, entity.topic_key)] = entity

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.items.values() if item.learner_goal_id == learner_goal_id]


class StubScheduledAutonomyJobRepository:
    def __init__(self):
        self.jobs: dict[str, ScheduledAutonomyJob] = {}

    async def create(self, entity: ScheduledAutonomyJob):
        if entity.job_type == "long_term_memory_materialization_replay":
            for job in self.jobs.values():
                if job.idempotency_key == entity.idempotency_key:
                    return job
        self.jobs[entity.id] = entity
        return entity

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.jobs.values() if item.learner_goal_id == learner_goal_id]

    async def list_active_by_goal(self, learner_goal_id: str, *, job_types=None):
        items = [
            item
            for item in self.jobs.values()
            if item.learner_goal_id == learner_goal_id and item.status in {"scheduled", "claimed"}
        ]
        if job_types is not None:
            items = [item for item in items if item.job_type in job_types]
        return items

    async def list_due(self, *, now: datetime, limit: int):
        items = [item for item in self.jobs.values() if item.status == "scheduled" and item.due_at <= now]
        items.sort(key=lambda item: (item.due_at, item.created_at))
        return items[:limit]

    async def claim(self, entity: ScheduledAutonomyJob, *, lease_owner: str, lease_seconds: int):
        claimed = entity.claim(lease_owner=lease_owner, lease_seconds=lease_seconds)
        self.jobs[entity.id] = claimed
        return claimed

    async def update(self, entity: ScheduledAutonomyJob):
        self.jobs[entity.id] = entity


class StubProposalRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposal] = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_id(self, proposal_id: str):
        return self.items.get(proposal_id)

    async def list_by_reflection(self, reflection_record_id: str):
        return [item for item in self.items.values() if item.reflection_record_id == reflection_record_id]

    async def list_queue(self, **kwargs):
        return list(self.items.values())

    async def count_queue(self, **kwargs):
        return len(self.items)

    async def update(self, entity):
        self.items[entity.id] = entity


class StubProposalEvaluationRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposalEvaluation] = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_proposal(self, proposal_id: str):
        for item in self.items.values():
            if item.proposal_id == proposal_id:
                return item
        return None

    async def update(self, entity):
        self.items[entity.id] = entity


class StubProposalApprovalDecisionRepository:
    def __init__(self):
        self.items = []

    async def create(self, entity):
        self.items.append(entity)

    async def list_by_proposal(self, proposal_id: str):
        return [item for item in self.items if item.proposal_id == proposal_id]


class StubProposalRolloutRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposalRollout] = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_id(self, rollout_id: str):
        return self.items.get(rollout_id)

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ):
        statuses = {"staged", "rolled_out"} if include_staged else {"rolled_out"}
        active = [
            item
            for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in statuses
        ]
        return active[-1] if active else None


class StubGoalSkillBindingResolver:
    def __init__(self, bindings: dict[tuple[str, str], ActiveGoalSkillBinding] | None = None):
        self.bindings = bindings or {}

    async def get_active_binding(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        goal_active_root_causes: set[str] | None = None,
        include_staged: bool = False,
    ):
        return self.bindings.get((learner_goal_id, surface))


class StubSkillUsageService:
    def __init__(self, resolutions: dict[tuple[str, str], SkillResolution] | None = None):
        self.resolutions = resolutions or {}
        self.resolution_requests: list[dict[str, object]] = []
        self.execution_plan_requests: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []

    async def resolve_for_runtime(self, *, skill_name: str, surface: str, resource_id: str | None = None):
        self.resolution_requests.append(
            {
                "skill_name": skill_name,
                "surface": surface,
                "resource_id": resource_id,
            }
        )
        return self.resolutions.get(
            (skill_name, surface),
            SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                implementation_binding=skill_name,
            ),
        )

    async def resolve_execution_plan(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        skill_binding: ActiveGoalSkillBinding | None = None,
    ):
        self.execution_plan_requests.append(
            {
                "skill_name": skill_name,
                "surface": surface,
                "resource_id": resource_id,
                "skill_binding": skill_binding,
            }
        )
        resolution = await self.resolve_for_runtime(skill_name=skill_name, surface=surface, resource_id=resource_id)
        execution_kind_by_surface = {
            "plan_generation": "study_plan",
            "replan": "study_plan",
            "review_scheduling": "review_schedule",
            "assessment_generation": "quiz_draft",
        }
        return SkillExecutionPlan(
            resolution=resolution,
            execution_kind=execution_kind_by_surface.get(surface, "study_plan"),
            runtime_directives=dict(skill_binding.runtime_directives) if skill_binding is not None else {},
            tool_plan=[dict(item) for item in skill_binding.tool_plan] if skill_binding is not None else [],
            binding_metadata=skill_binding.usage_metadata(skill_name=skill_name) if skill_binding is not None else {},
        )

    async def record_usage(self, **kwargs):
        self.events.append(dict(kwargs))
        return None


class StubSessionRepository:
    def __init__(self):
        self.sessions: dict[str, LearningSession] = {}

    async def create(self, entity: LearningSession):
        self.sessions[entity.id] = entity

    async def list_sessions(self):
        return list(self.sessions.values())

    async def get_by_id(self, session_id: str):
        return self.sessions.get(session_id)

    async def update(self, entity: LearningSession):
        self.sessions[entity.id] = entity


class StubSessionMessageRepository:
    async def list_history(self, *, session_id, limit, before_id):
        return []


class StubMemoryEventRepository:
    async def list_by_profile_since(self, **kwargs):
        return []


class StubMessageRepository:
    def __init__(self):
        self.messages: list[SessionMessage] = []

    async def create(self, entity: SessionMessage):
        self.messages.append(entity)

    async def list_history(self, *, session_id, limit, before_id):
        return [item for item in self.messages if item.session_id == session_id][-limit:]


class StubQuizRepository:
    def __init__(self):
        self.quizzes: dict[str, SessionQuiz] = {}
        self.questions: dict[str, list[SessionQuizQuestion]] = {}

    async def create_quiz(self, entity: SessionQuiz):
        self.quizzes[entity.id] = entity

    async def create_questions(self, entities: list[SessionQuizQuestion]):
        for entity in entities:
            self.questions.setdefault(entity.quiz_id, []).append(entity)

    async def list_by_session(self, session_id: str):
        return [item for item in self.quizzes.values() if item.session_id == session_id]

    async def get_quiz_with_questions(self, *, session_id, quiz_id):
        quiz = self.quizzes[quiz_id]
        return type("StoredQuiz", (), {"quiz": quiz, "questions": []})()


class StubMemoryService:
    embedding_provider_name = None
    embedding_model_name = None

    async def retrieve_relevant_session_memories(self, **kwargs):
        from agent_core.domain.entities.memory import MemoryRetrievalResult

        return MemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)

    async def retrieve_relevant_profile_memories(self, **kwargs):
        from agent_core.domain.entities.memory import MemoryRetrievalResult

        return MemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)

    async def record_learning_memories(self, **kwargs):
        return []

    async def build_interpretation(self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit_per_type: int = 4):
        from agent_core.application.services.memory import MemoryInterpretationResult

        return MemoryInterpretationResult(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc),
            facts=[],
            behavior_patterns=[],
            contested_items=[],
            recommended_constraints=[],
            conflict_count=0,
        )

    async def build_reflection_corpus(self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit_per_type: int = 2):
        from agent_core.application.services.memory import ReflectionCorpusResult, ReflectionCorpusSummary

        return ReflectionCorpusResult(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc),
            items=[],
            summary=ReflectionCorpusSummary(
                total_items=0,
                knowledge_items=0,
                behavior_items=0,
                candidate_items=0,
                stable_items=0,
                contradiction_focus_items=0,
                stale_focus_items=0,
                validate_items=0,
                reinforce_items=0,
            ),
        )


class FailingLongTermMemoryMaterializationService:
    async def materialize_from_task_outcome(self, **kwargs):
        raise RuntimeError("materialization failed")


class SuccessfulLongTermMemoryReplayExecutor:
    def __init__(self, audit_service: AuditService):
        self.audit_service = audit_service
        self.jobs: list[ScheduledAutonomyJob] = []

    async def replay(self, job: ScheduledAutonomyJob):
        self.jobs.append(job)
        await self.audit_service.record(
            event_type="long_term_memory.materialization.replayed",
            resource_type="autonomy_job",
            resource_id=job.id,
            actor="system",
            event_data={
                "autonomy_job_id": job.id,
                "learner_goal_id": job.learner_goal_id,
                "source_type": job.payload.get("source_type"),
            },
        )


class FailingLongTermMemoryReplayExecutor:
    async def replay(self, job: ScheduledAutonomyJob):
        raise RuntimeError("replay failed")


def _build_task_service(
    *,
    goal: LearnerGoal,
    profile: LearnerProfile,
    fake_session: FakeSession,
    audit_service: AuditService,
    workflow_run_repository: StubWorkflowRunRepository,
    daily_task_repository: StubDailyTaskRepository | None = None,
    goal_skill_binding_resolver: StubGoalSkillBindingResolver | None = None,
    long_term_memory_materialization_service=None,
    long_term_memory_replay_executor=None,
    skill_usage_service: StubSkillUsageService | None = None,
):
    session_repository = StubSessionRepository()
    task_repository = daily_task_repository or StubDailyTaskRepository()
    study_plan_repository = StubStudyPlanRepository()
    autonomy_state_repository = StubGoalAutonomyStateRepository()
    availability_repository = StubLearnerAvailabilityRepository()
    autonomy_job_repository = StubScheduledAutonomyJobRepository()
    task_attempt_repository = StubTaskAttemptRepository()
    mastery_repository = StubLearnerTopicMasteryRepository()
    session_service = SessionService(
        session_repository,
        StubLearnerProfileRepository([profile]),
        StubGoalRepository(goal),
        fake_session,
        audit_service,
    )
    reflection_record_repository = StubReflectionRecordRepository()
    reflection_action_repository = StubReflectionActionRepository()
    review_decision_repository = StubReviewDecisionRepository()
    outcome_repository = StubOutcomeRepository()
    strategy_card_repository = StubStrategyCardRepository()
    reflective_memory_repository = StubReflectiveMemoryRepository()
    evidence_repository = StubReflectionEvidenceRepository()
    memory_repository = StubMemoryEventRepository()
    evidence_service = ReflectionEvidenceService(
        repository=evidence_repository,
        message_repository=StubSessionMessageRepository(),
        memory_event_repository=memory_repository,
        daily_task_repository=task_repository,
        workflow_run_repository=workflow_run_repository,
        learner_topic_mastery_repository=mastery_repository,
        audit_service=audit_service,
    )
    outcome_service = ReflectionOutcomeService(
        repository=outcome_repository,
        task_attempt_repository=task_attempt_repository,
        audit_service=audit_service,
    )
    governance_service = ReflectionGovernanceService(
        reflection_record_repository=reflection_record_repository,
        reflection_action_repository=reflection_action_repository,
        review_decision_repository=review_decision_repository,
        audit_service=audit_service,
    )
    strategy_card_service = StrategyCardService(
        repository=strategy_card_repository,
        audit_service=audit_service,
    )
    reflective_memory_service = ReflectiveMemoryService(
        repository=reflective_memory_repository,
        audit_service=audit_service,
    )
    proposal_repository = StubProposalRepository()
    proposal_evaluation_repository = StubProposalEvaluationRepository()
    rollout_repository = StubProposalRolloutRepository()
    reflection_service = ReflectionService(
        reflection_record_repository=reflection_record_repository,
        reflection_action_repository=reflection_action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=task_repository,
        workflow_run_repository=workflow_run_repository,
        study_plan_repository=study_plan_repository,
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=session_repository,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=evidence_service,
        outcome_service=outcome_service,
        governance_service=governance_service,
        strategy_card_service=strategy_card_service,
        reflective_memory_service=reflective_memory_service,
        proposal_service=ReflectionProposalService(
            repository=proposal_repository,
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            evaluation_repository=proposal_evaluation_repository,
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=proposal_evaluation_repository, audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )
    task_repository = daily_task_repository or StubDailyTaskRepository()
    tool_registry = InternalToolRegistry(audit_service=audit_service)
    tool_plan_runtime_executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=tool_registry,
        audit_service=audit_service,
    )
    task_service = AutonomousTaskService(
        db_session=fake_session,
        goal_repository=StubGoalRepository(goal),
        study_plan_repository=study_plan_repository,
        plan_stage_repository=StubPlanStageRepository(),
        daily_task_repository=task_repository,
        workflow_run_repository=workflow_run_repository,
        goal_autonomy_state_repository=autonomy_state_repository,
        autonomy_job_repository=autonomy_job_repository,
        learner_availability_repository=availability_repository,
        learner_topic_mastery_repository=mastery_repository,
        task_attempt_repository=task_attempt_repository,
        planner_service=PlannerService(
            llm_provider=MockLLMProvider("mock-tutor-v1"),
            audit_service=audit_service,
            goal_skill_binding_resolver=goal_skill_binding_resolver,
            skill_usage_service=skill_usage_service,
        ),
        workflow_run_service=WorkflowRunService(
            repository=workflow_run_repository,
            db_session=fake_session,
            audit_service=audit_service,
        ),
        session_service=session_service,
        chat_service=type("ChatStub", (), {"create_message": staticmethod(_async_noop_message)})(),
        quiz_service=type("QuizStub", (), {"generate_quiz": staticmethod(_async_noop_quiz)})(),
        autonomy_job_service=AutonomyJobService(repository=autonomy_job_repository, audit_service=audit_service),
        reflection_service=reflection_service,
        reflection_evidence_service=evidence_service,
        reflection_outcome_service=outcome_service,
        reflection_proposal_sandbox_service=None,
        reflection_proposal_rollout_service=None,
        rollout_resolver=ReflectionProposalRolloutResolver(rollout_repository=rollout_repository),
        rollout_observation_scheduler=ReflectionProposalRolloutObservationScheduler(
            rollout_repository=rollout_repository,
            autonomy_job_service=AutonomyJobService(repository=autonomy_job_repository, audit_service=audit_service),
            audit_service=audit_service,
        ),
        goal_skill_binding_resolver=goal_skill_binding_resolver,
        strategy_card_service=strategy_card_service,
        reflective_memory_service=reflective_memory_service,
        memory_service=StubMemoryService(),
        long_term_memory_materialization_service=long_term_memory_materialization_service,
        long_term_memory_replay_executor=long_term_memory_replay_executor,
        internal_tool_registry=tool_registry,
        tool_plan_runtime_executor=tool_plan_runtime_executor,
        skill_usage_service=skill_usage_service,
        audit_service=audit_service,
    )
    return task_service, reflection_record_repository, reflection_action_repository, rollout_repository


async def test_generate_plan_execute_task_and_schedule_reviews():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    plan = await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    assert plan.version == 1
    tasks = await task_service.list_tasks(goal.id)
    assert len(tasks) >= 1

    first_task = tasks[0]
    execute_result = await task_service.execute_task(first_task.id)
    assert execute_result.execution_session_id is not None
    assert execute_result.task.status == "in_progress"
    reused_result = await task_service.execute_task(first_task.id)
    assert reused_result.reused_existing_execution is True
    assert any(event.event_type == "daily_task.execution.reused" for event in audit_repository.events)

    completed = await task_service.update_task_status(
        task_id=first_task.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
    )
    assert completed.status == "completed"
    await task_service.run_due_autonomy_jobs(raise_on_error=True)

    all_tasks = await task_service.list_tasks(goal.id)
    assert any(task.task_type == "review" for task in all_tasks)
    assert any(event.event_type == "review.tasks.scheduled" for event in audit_repository.events)


async def test_update_task_status_queues_review_and_worker_failure_is_audited():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    failing_repository = FailingReviewTaskRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
        daily_task_repository=failing_repository,
    )

    plan = await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task = (await task_service.list_tasks(goal.id))[0]
    task_repository = task_service._daily_task_repository
    assert isinstance(task_repository, FailingReviewTaskRepository)
    stored_task = task_repository.tasks[task.id]
    task_repository.tasks[task.id] = stored_task.with_execution_session(
        execution_session_id="session-1",
        workflow_run_id="run-1",
    )

    updated = await task_service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
    )
    assert updated.status == "completed"

    assert plan.version == 1
    assert any(event.event_type == "daily_task.status.updated" for event in audit_repository.events)
    assert not any(event.event_type == "autonomy.job.failed" for event in audit_repository.events)

    try:
        await task_service.run_due_autonomy_jobs(raise_on_error=True)
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "review scheduling failed" in str(exc)
    assert any(event.event_type == "autonomy.job.failed" for event in audit_repository.events)


async def test_update_task_status_queues_replan_without_inline_worker_side_effects():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task = (await task_service.list_tasks(goal.id))[0]
    await task_service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="failed", result_note="Still confused"),
    )

    plans_before_worker = await task_service.list_plans(goal.id)
    assert [item.version for item in plans_before_worker] == [1]
    jobs = await task_service.list_autonomy_jobs(goal.id)
    assert any(job.job_type == "replan" and job.status == "scheduled" for job in jobs)

    await task_service.run_due_autonomy_jobs(raise_on_error=True)
    plans_after_worker = await task_service.list_plans(goal.id)
    assert sorted(item.version for item in plans_after_worker) == [1, 2]


async def test_review_scheduling_worker_records_skill_usage():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="review_scheduling",
        trigger_source="task_completed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-review-scheduling",
        payload={"source_task_id": source_task.id},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    event = next(item for item in skill_usage_service.events if item["surface"] == "review_scheduling")
    assert event["skill_name"] == "schedule_review"
    assert event["outcome_status"] == "completed"
    assert event["daily_task_id"] == source_task.id
    assert event["workflow_run_id"] is not None
    assert event["topic_key"] == source_task.topic_focus
    assert event["trigger_source"] == "task_completed"
    assert event["metadata"]["autonomy_job_id"] == job.id
    assert event["metadata"]["source_task_id"] == source_task.id
    assert event["metadata"]["created_review_task_ids"]
    assert event["metadata"]["implementation_binding"] == "schedule_review"
    assert event["metadata"]["execution_kind"] == "review_schedule"
    assert event["metadata"]["artifact_id"] is None
    assert event["metadata"]["artifact_status"] is None
    assert event["metadata"]["binding_id"] is None
    assert event["metadata"]["rollout_id"] is None
    assert event["metadata"]["tool_plan_enabled"] is False
    assert event["metadata"]["dynamic_registry_version"] == "v1"
    assert event["metadata"]["source_summary"] == {
        "artifact_source": "static_fallback",
        "directives_source": "none",
        "tool_plan_source": "none",
    }
    assert {
        "skill_name": "schedule_review",
        "surface": "review_scheduling",
        "resource_id": source_task.id,
    } in skill_usage_service.resolution_requests
    assert {
        "skill_name": "schedule_review",
        "surface": "review_scheduling",
        "resource_id": source_task.id,
        "skill_binding": None,
    } in skill_usage_service.execution_plan_requests
    observation_jobs = [
        item
        for item in task_service._autonomy_job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert observation_jobs == []


async def test_review_scheduling_worker_schedules_rollout_observation_for_active_surface():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, rollout_repository = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-review-1",
            learner_goal_id=goal.id,
            surface="review_scheduling",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="review_scheduling",
        trigger_source="task_completed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-review-scheduling-observation",
        payload={"source_task_id": source_task.id},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    observation_jobs = [
        item
        for item in task_service._autonomy_job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == goal.id
    assert observation_jobs[0].trigger_source == "task_completed"
    assert observation_jobs[0].payload["surface"] == "review_scheduling"
    assert observation_jobs[0].payload["rollout_id"]


async def test_assessment_generation_worker_records_skill_usage_with_binding_metadata():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    binding_resolver = StubGoalSkillBindingResolver(
        {
            (goal.id, "assessment_generation"): ActiveGoalSkillBinding(
                binding_id="binding-assessment-1",
                proposal_id="proposal-assessment-1",
                rollout_id="rollout-assessment-1",
                learner_goal_id=goal.id,
                surface="assessment_generation",
                status="rolled_out",
                priority_score=0.9,
                match_rules={},
                runtime_directives={},
                tool_plan=[],
            )
        }
    )
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        goal_skill_binding_resolver=binding_resolver,
        skill_usage_service=skill_usage_service,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="assessment_generation",
        trigger_source="task_completed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-assessment-generation",
        payload={"topic_focus": source_task.topic_focus, "source_task_id": source_task.id},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    event = next(item for item in skill_usage_service.events if item["surface"] == "assessment_generation")
    metadata = event["metadata"]
    assert event["skill_name"] == "create_quiz"
    assert event["outcome_status"] == "completed"
    assert event["workflow_run_id"] is not None
    assert event["topic_key"] == source_task.topic_focus
    assert event["trigger_source"] == "task_completed"
    assert metadata["autonomy_job_id"] == job.id
    assert metadata["source_task_id"] == source_task.id
    assert metadata["created_assessment_task_ids"] == [metadata["assessment_task_id"]]
    assert metadata["implementation_binding"] == "create_quiz"
    assert metadata["execution_kind"] == "quiz_draft"
    assert metadata["artifact_id"] is None
    assert metadata["artifact_status"] is None
    assert metadata["binding_id"] == "binding-assessment-1"
    assert metadata["rollout_id"] == "rollout-assessment-1"
    assert metadata["tool_plan_enabled"] is False
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"] == {
        "artifact_source": "static_fallback",
        "directives_source": "none",
        "tool_plan_source": "none",
    }
    assert metadata["skill_package_rollout"] == {
        "proposal_id": "proposal-assessment-1",
        "rollout_id": "rollout-assessment-1",
        "binding_id": "binding-assessment-1",
        "skill_name": "create_quiz",
        "surface": "assessment_generation",
        "binding_status": "rolled_out",
    }


async def test_assessment_generation_worker_schedules_rollout_observation_for_active_surface():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, rollout_repository = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-assessment-1",
            learner_goal_id=goal.id,
            surface="assessment_generation",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="assessment_generation",
        trigger_source="task_completed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-assessment-generation-observation",
        payload={"topic_focus": source_task.topic_focus, "source_task_id": source_task.id},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    observation_jobs = [
        item
        for item in task_service._autonomy_job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == goal.id
    assert observation_jobs[0].trigger_source == "task_completed"
    assert observation_jobs[0].payload["surface"] == "assessment_generation"
    assert observation_jobs[0].payload["rollout_id"]


async def test_partial_replan_worker_records_skill_usage():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="replan",
        trigger_source="task_failed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-replan-partial",
        payload={"mode": "partial", "source_task_id": source_task.id, "topic_focus": source_task.topic_focus},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    event = next(item for item in skill_usage_service.events if item["surface"] == "replan")
    metadata = event["metadata"]
    assert event["skill_name"] == "plan_study_path"
    assert event["outcome_status"] == "completed"
    assert event["daily_task_id"] == source_task.id
    assert event["workflow_run_id"] is not None
    assert event["topic_key"] == source_task.topic_focus
    assert event["trigger_source"] == "task_failed"
    assert metadata["autonomy_job_id"] == job.id
    assert metadata["mode"] == "partial"
    assert metadata["effective_mode"] == "partial"
    assert metadata["source_task_id"] == source_task.id
    assert metadata["repair_task_id"]
    assert metadata["artifact_id"] is None
    assert metadata["artifact_status"] is None
    assert metadata["binding_id"] is None
    assert metadata["rollout_id"] is None
    assert metadata["tool_plan_enabled"] is False
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"] == {
        "artifact_source": "static_fallback",
        "directives_source": "none",
        "tool_plan_source": "none",
    }


async def test_partial_replan_worker_executes_two_step_tool_plan_chain():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    binding_resolver = StubGoalSkillBindingResolver(
        {
            (goal.id, "replan"): ActiveGoalSkillBinding(
                binding_id="binding-replan-1",
                proposal_id="proposal-replan-1",
                rollout_id="rollout-replan-1",
                learner_goal_id=goal.id,
                surface="replan",
                status="rolled_out",
                priority_score=0.9,
                match_rules={},
                runtime_directives={"replan_bias": "normal"},
                tool_plan=[
                    {
                        "step_id": "repair",
                        "tool_name": "partial_replan",
                        "payload_template": {"source_task_id": "$source_task_id"},
                    },
                    {
                        "step_id": "followup_review",
                        "tool_name": "review_scheduling",
                        "payload_template": {"source_task_id": "$steps.repair.created_task_ids[0]"},
                    },
                ],
            )
        }
    )
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        goal_skill_binding_resolver=binding_resolver,
        skill_usage_service=skill_usage_service,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="replan",
        trigger_source="task_failed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-replan-two-step",
        payload={"mode": "partial", "source_task_id": source_task.id, "topic_focus": source_task.topic_focus},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    all_tasks = await task_service.list_tasks(goal.id)
    repair_tasks = [task for task in all_tasks if task.task_type == "repair"]
    review_tasks = [task for task in all_tasks if task.task_type == "review" and task.source_task_id in {task.id for task in repair_tasks}]
    assert repair_tasks
    assert review_tasks
    event = next(item for item in skill_usage_service.events if item["surface"] == "replan")
    metadata = event["metadata"]
    assert metadata["binding_id"] == "binding-replan-1"
    assert metadata["rollout_id"] == "rollout-replan-1"
    assert metadata["tool_plan_enabled"] is True
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"] == {
        "artifact_source": "static_fallback",
        "directives_source": "binding_overlay",
        "tool_plan_source": "binding_overlay",
    }


async def test_replan_worker_schedules_rollout_observation_for_active_surface():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, rollout_repository = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-replan-1",
            learner_goal_id=goal.id,
            surface="replan",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    source_task_response = (await task_service.list_tasks(goal.id))[0]
    source_task = await task_service._daily_task_repository.get_by_id(source_task_response.id)
    assert source_task is not None
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="replan",
        trigger_source="task_failed",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-replan-observation",
        payload={"mode": "partial", "source_task_id": source_task.id, "topic_focus": source_task.topic_focus},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    observation_jobs = [
        item
        for item in task_service._autonomy_job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == goal.id
    assert observation_jobs[0].trigger_source == "task_failed"
    assert observation_jobs[0].payload["surface"] == "replan"
    assert observation_jobs[0].payload["rollout_id"]


async def test_full_replan_worker_records_skill_usage():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task_service._autonomy_job_repository.jobs.clear()
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="replan",
        trigger_source="manual_replan",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="usage-replan-full",
        payload={"mode": "full", "topic_focus": goal.subject},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="usage-test", limit=1)

    assert processed == 1
    event = next(item for item in skill_usage_service.events if item["surface"] == "replan")
    metadata = event["metadata"]
    assert event["skill_name"] == "plan_study_path"
    assert event["outcome_status"] == "completed"
    assert event["daily_task_id"] is None
    assert event["topic_key"] == goal.subject
    assert event["trigger_source"] == "manual_replan"
    assert metadata["autonomy_job_id"] == job.id
    assert metadata["mode"] == "full"
    assert metadata["effective_mode"] == "full"
    assert metadata["fallback_used"] is False
    assert metadata["implementation_binding"] == "plan_study_path"
    assert metadata["execution_kind"] == "study_plan"
    assert metadata["artifact_id"] is None
    assert metadata["artifact_status"] is None
    assert metadata["binding_id"] is None
    assert metadata["rollout_id"] is None
    assert metadata["tool_plan_enabled"] is False
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"] == {
        "artifact_source": "static_fallback",
        "directives_source": "none",
        "tool_plan_source": "none",
    }


async def test_generate_plan_uses_execution_plan_resolution():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")

    assert {
        "skill_name": "plan_study_path",
        "surface": "plan_generation",
        "resource_id": goal.id,
        "skill_binding": None,
    } in skill_usage_service.execution_plan_requests
    event = next(item for item in skill_usage_service.events if item["surface"] == "plan_generation")
    assert event["metadata"]["implementation_binding"] == "plan_study_path"
    assert event["metadata"]["execution_kind"] == "study_plan"


async def test_generate_plan_schedules_rollout_observation_for_active_surface():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    skill_usage_service = StubSkillUsageService()
    task_service, _, _, rollout_repository = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        workflow_run_repository=StubWorkflowRunRepository(),
        skill_usage_service=skill_usage_service,
    )
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-plan-1",
            learner_goal_id=goal.id,
            surface="plan_generation",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")

    observation_jobs = [
        item
        for item in task_service._autonomy_job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == goal.id
    assert observation_jobs[0].trigger_source == "initial"
    assert observation_jobs[0].payload["surface"] == "plan_generation"
    assert observation_jobs[0].payload["rollout_id"]


async def test_task_materialization_failure_is_audited_without_blocking_status_update():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
        long_term_memory_materialization_service=FailingLongTermMemoryMaterializationService(),
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task = (await task_service.list_tasks(goal.id))[0]
    stored_task = task_service._daily_task_repository.tasks[task.id]
    task_service._daily_task_repository.tasks[task.id] = stored_task.with_execution_session(
        execution_session_id="session-1",
        workflow_run_id="run-1",
    )

    updated = await task_service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
    )

    assert updated.status == "completed"
    assert fake_session.committed >= 1
    assert fake_session.rolled_back == 0
    assert fake_session.nested_transactions >= 1
    failure_events = [
        item
        for item in audit_repository.events
        if item.event_type == "long_term_memory.materialization.failed"
    ]
    assert len(failure_events) == 1
    assert failure_events[0].event_data["source_type"] == "task_outcome"
    assert failure_events[0].event_data["task_id"] == task.id
    assert failure_events[0].event_data["workflow_run_id"] == "run-1"
    assert failure_events[0].event_data["session_id"] == "session-1"
    assert failure_events[0].event_data["error_code"] == "RuntimeError"
    assert failure_events[0].event_data["replay_enqueued"] is True
    assert failure_events[0].event_data["replay_skip_reason"] is None
    replay_jobs = [
        job
        for job in task_service._autonomy_job_repository.jobs.values()
        if job.job_type == "long_term_memory_materialization_replay"
    ]
    assert len(replay_jobs) == 1
    assert replay_jobs[0].learner_goal_id == goal.id
    assert replay_jobs[0].payload == {
        "source_type": "task_outcome",
        "task_id": task.id,
        "attempt_id": failure_events[0].event_data["attempt_id"],
    }


async def test_long_term_memory_replay_job_completes_after_successful_replay():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    replay_executor = SuccessfulLongTermMemoryReplayExecutor(audit_service)
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=StubWorkflowRunRepository(),
        long_term_memory_replay_executor=replay_executor,
    )
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="ltm-replay:test:success",
        payload={"source_type": "task_outcome", "task_id": "task-1", "attempt_id": "attempt-1"},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="test-worker")

    assert processed == 1
    stored = task_service._autonomy_job_repository.jobs[job.id]
    assert stored.status == "completed"
    assert stored.attempt_count == 1
    assert replay_executor.jobs[0].id == job.id
    assert any(item.event_type == "long_term_memory.materialization.replayed" for item in audit_repository.events)
    assert any(item.event_type == "autonomy.job.completed" for item in audit_repository.events)


async def test_long_term_memory_replay_job_failure_schedules_retry_with_backoff():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=audit_service,
        workflow_run_repository=StubWorkflowRunRepository(),
        long_term_memory_replay_executor=FailingLongTermMemoryReplayExecutor(),
    )
    before = datetime.now(timezone.utc)
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=before - timedelta(minutes=1),
        idempotency_key="ltm-replay:test:retry",
        payload={"source_type": "task_outcome", "task_id": "task-1", "attempt_id": "attempt-1"},
    )
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="test-worker")

    assert processed == 1
    stored = task_service._autonomy_job_repository.jobs[job.id]
    assert stored.status == "scheduled"
    assert stored.attempt_count == 1
    assert stored.due_at >= before + timedelta(minutes=5)
    assert any(
        item.event_type == "long_term_memory.materialization.replay_retry_scheduled"
        for item in audit_repository.events
    )
    assert not any(item.event_type == "autonomy.job.failed" for item in audit_repository.events)


async def test_long_term_memory_replay_job_failure_exhausts_after_max_attempts():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=FakeSession(),
        audit_service=audit_service,
        workflow_run_repository=StubWorkflowRunRepository(),
        long_term_memory_replay_executor=FailingLongTermMemoryReplayExecutor(),
    )
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        idempotency_key="ltm-replay:test:exhausted",
        payload={"source_type": "task_outcome", "task_id": "task-1", "attempt_id": "attempt-1"},
    )
    job = replace(job, attempt_count=2, max_attempts=3)
    task_service._autonomy_job_repository.jobs[job.id] = job

    processed = await task_service.run_due_autonomy_jobs(raise_on_error=False, lease_owner="test-worker")

    assert processed == 0
    stored = task_service._autonomy_job_repository.jobs[job.id]
    assert stored.status == "failed"
    assert stored.attempt_count == 3
    assert stored.error_code == "RuntimeError"
    assert any(
        item.event_type == "long_term_memory.materialization.replay_exhausted"
        for item in audit_repository.events
    )
    assert any(item.event_type == "autonomy.job.failed" for item in audit_repository.events)


async def test_failed_task_creates_reflection_record_and_action():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, reflection_record_repository, reflection_action_repository, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task = (await task_service.list_tasks(goal.id))[0]
    stored_task = task_service._daily_task_repository.tasks[task.id]
    task_service._daily_task_repository.tasks[task.id] = stored_task.with_execution_session(
        execution_session_id="session-1",
        workflow_run_id="run-1",
    )

    updated = await task_service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="failed", result_note="Still confused"),
    )

    assert updated.status == "failed"
    assert len(reflection_record_repository.records) >= 1
    assert any(item.primary_root_cause == "knowledge_gap" for item in reflection_record_repository.records.values())
    assert len(reflection_action_repository.actions) >= 1
    assert any(event.event_type == "reflection.record.completed" for event in audit_repository.events)


async def test_review_intervals_use_active_rollout_overlay():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, rollout_repository = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )
    rollout = ReflectionProposalRollout.build(
        proposal_id="proposal-1",
        learner_goal_id=goal.id,
        surface="review_scheduling",
        baseline_snapshot={},
        runtime_overlay_payload={"review_bias": "intensive"},
        activated_by="operator",
    ).with_status("rolled_out")
    await rollout_repository.create(rollout)
    mastery = LearnerTopicMastery.build(learner_goal_id=goal.id, topic_key="matrix multiplication")

    intervals = await task_service._review_intervals(goal.id, mastery)  # noqa: SLF001

    assert intervals == [1, 2, 3]


async def test_review_intervals_use_active_skill_binding_before_rollout_overlay():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    binding_resolver = StubGoalSkillBindingResolver(
        {
            (goal.id, "review_scheduling"): ActiveGoalSkillBinding(
                binding_id="binding-1",
                proposal_id="proposal-1",
                rollout_id="rollout-1",
                learner_goal_id=goal.id,
                surface="review_scheduling",
                status="rolled_out",
                priority_score=0.9,
                match_rules={},
                runtime_directives={"review_bias": "intensive"},
                tool_plan=[],
            )
        }
    )
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
        goal_skill_binding_resolver=binding_resolver,
    )
    mastery = LearnerTopicMastery.build(learner_goal_id=goal.id, topic_key="matrix multiplication")

    intervals = await task_service._review_intervals(goal.id, mastery)  # noqa: SLF001

    assert intervals == [1, 2, 3]


async def test_update_availability_schedules_daily_materialization_job():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    await task_service.update_goal_availability(
        goal_id=goal.id,
        payload=type(
            "Payload",
            (),
            {
                "timezone": "Asia/Shanghai",
                "available_days": ["mon", "wed", "fri"],
                "time_windows": [{"start": "19:00", "end": "21:00"}],
                "max_daily_minutes": 60,
                "preferred_session_length_minutes": 30,
            },
        )(),
    )

    jobs = await task_service.list_autonomy_jobs(goal.id)
    materialization_jobs = [job for job in jobs if job.job_type == "daily_task_materialization"]
    assert materialization_jobs
    active_job = next(job for job in materialization_jobs if job.status in {"scheduled", "claimed"})
    assert active_job.payload["target_timezone"] == "Asia/Shanghai"
    assert active_job.payload["scheduled_local_time"] == "19:00"


async def test_materialization_and_milestone_jobs_create_followup_tasks():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    tasks = await task_service.list_tasks(goal.id)
    first_task = tasks[0]
    stored_task = task_service._daily_task_repository.tasks[first_task.id]
    task_service._daily_task_repository.tasks[first_task.id] = stored_task.with_execution_session(
        execution_session_id="session-1",
        workflow_run_id="run-1",
    )
    await task_service.update_task_status(
        task_id=first_task.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
    )
    await task_service.run_due_autonomy_jobs(raise_on_error=True)

    await task_service.materialize_today(goal.id)
    jobs = await task_service.list_autonomy_jobs(goal.id)
    milestone_jobs = [job for job in jobs if job.job_type == "milestone_generation"]
    if milestone_jobs:
        await task_service.run_due_autonomy_jobs(raise_on_error=True)

    refreshed_tasks = await task_service.list_tasks(goal.id)
    assert any(task.task_type == "review" for task in refreshed_tasks)


async def test_generate_plan_schedules_periodic_goal_reflection_job():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    jobs = await task_service.list_autonomy_jobs(goal.id)
    assert any(job.job_type == "goal_reflection_periodic" for job in jobs)


async def test_completed_task_schedules_reflection_outcome_evaluation_job():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    task = (await task_service.list_tasks(goal.id))[0]
    stored = task_service._daily_task_repository.tasks[task.id]
    task_service._daily_task_repository.tasks[task.id] = stored.with_execution_session(
        execution_session_id="session-1",
        workflow_run_id="run-1",
    )
    await task_service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="failed", result_note="Still confused"),
    )
    jobs = await task_service.list_autonomy_jobs(goal.id)
    assert any(job.job_type == "reflection_outcome_evaluation" for job in jobs)


async def test_milestone_gate_blocks_downstream_until_completed():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )

    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    tasks = await task_service.list_tasks(goal.id)
    first_stage_id = tasks[0].plan_stage_id
    first_stage_tasks = [task for task in tasks if task.plan_stage_id == first_stage_id and task.task_type in {"lesson", "practice"}]
    target_count = max(1, (len(first_stage_tasks) + 1) // 2)
    for task in first_stage_tasks[:target_count]:
        stored = task_service._daily_task_repository.tasks[task.id]
        task_service._daily_task_repository.tasks[task.id] = stored.with_execution_session(
            execution_session_id=f"session-{task.id}",
            workflow_run_id=f"run-{task.id}",
        )
        await task_service.update_task_status(
            task_id=task.id,
            payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
        )
        await task_service.run_due_autonomy_jobs(raise_on_error=True)
    await task_service.materialize_today(goal.id)
    await task_service.run_due_autonomy_jobs(raise_on_error=True)

    gated_tasks = await task_service.list_tasks(goal.id)
    milestone = next(task for task in gated_tasks if task.task_type == "milestone")
    state = await task_service.get_goal_autonomy_state(goal.id)
    assert state.phase == "assessment_due"
    downstream_superseded = [
        task
        for task in gated_tasks
        if task.task_type in {"lesson", "practice"} and task.plan_stage_id != first_stage_id and task.status == "superseded"
    ]
    assert downstream_superseded

    milestone_stored = task_service._daily_task_repository.tasks[milestone.id]
    task_service._daily_task_repository.tasks[milestone.id] = milestone_stored.with_execution_session(
        execution_session_id="session-m",
        workflow_run_id="run-m",
    )
    await task_service.update_task_status(
        task_id=milestone.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Gate passed"),
    )
    released = await task_service.get_goal_autonomy_state(goal.id)
    assert released.phase == "active"


async def test_dynamic_review_intervals_shift_by_recent_failures_and_strategy():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve core matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    workflow_run_repository = StubWorkflowRunRepository()
    task_service, _, _, _ = _build_task_service(
        goal=goal,
        profile=profile,
        fake_session=fake_session,
        audit_service=audit_service,
        workflow_run_repository=workflow_run_repository,
    )
    await task_service.generate_plan(goal_id=goal.id, trigger_source="initial")
    mastery = LearnerTopicMastery.build(learner_goal_id=goal.id, topic_key="Matrices").update_from_attempt(
        outcome_status="failed",
        task_type="practice",
    )
    mastery = mastery.update_from_attempt(outcome_status="failed", task_type="practice")
    await task_service._learner_topic_mastery_repository.upsert(mastery)
    failed_attempt = task_service._task_attempt_repository
    await failed_attempt.create(
        type(
            "Attempt",
            (),
            {
                "learner_goal_id": goal.id,
                "topic_focus": "Matrices",
                "outcome_status": "failed",
                "created_at": datetime.now(timezone.utc),
            },
        )()
    )
    await failed_attempt.create(
        type(
            "Attempt",
            (),
            {
                "learner_goal_id": goal.id,
                "topic_focus": "Matrices",
                "outcome_status": "skipped",
                "created_at": datetime.now(timezone.utc) + timedelta(seconds=1),
            },
        )()
    )
    intervals = await task_service._review_intervals(goal.id, mastery)  # noqa: SLF001
    assert intervals == [1, 2, 3]


async def test_http_tool_registry_enforces_json_and_audits(monkeypatch):
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    registry = InternalToolRegistry(audit_service=audit_service)
    registry.register(
        HttpToolSpec(
            name="progress_hook",
            description="Test hook",
            risk_level="medium",
            url="https://example.test/hook",
            timeout_seconds=5.0,
            allowed_statuses=(200,),
            enabled=True,
        )
    )

    async def fake_request(self, method, url, json):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"accepted": True, "echo": json},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    result = await registry.execute(
        ToolExecutionRequest(
            name="progress_hook",
            payload={"goal_id": "goal-1"},
            actor="system",
            resource_id="goal-1",
        )
    )
    assert result == {"accepted": True, "echo": {"goal_id": "goal-1"}}
    assert any(event.event_type == "tool.execution.completed" for event in audit_repository.events)


async def _async_noop_message(**kwargs):
    return None


async def _async_noop_quiz(payload):
    return None
