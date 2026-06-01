from datetime import date, datetime, timedelta, timezone

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.reflective_memory import ReflectiveMemoryService
from agent_core.application.services.reflection import ReflectionService, ReflectionTriggerRequest
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_governance import ReflectionGovernanceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.reflection_proposal_sandbox import ReflectionProposalSandboxService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposal_rollouts import ReflectionProposalRolloutService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.domain.entities.autonomy import GoalAutonomyState, TaskAttempt
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.planning import DailyTask, StudyPlan, WorkflowRun
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalApprovalDecision,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutDecision,
    ReflectionProposalRolloutObservation,
    ReflectionProposalSandboxRun,
)
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.llm.mock_provider import MockLLMProvider


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubScheduledAutonomyJobRepository:
    def __init__(self):
        self.jobs: dict[str, ScheduledAutonomyJob] = {}

    async def create(self, entity: ScheduledAutonomyJob):
        for job in self.jobs.values():
            if job.idempotency_key == entity.idempotency_key:
                return job
        self.jobs[entity.id] = entity
        return entity


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


class StubProposalSandboxRunRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposalSandboxRun] = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_id(self, sandbox_run_id: str):
        return self.items.get(sandbox_run_id)

    async def list_by_proposal(self, proposal_id: str):
        return [item for item in self.items.values() if item.proposal_id == proposal_id]

    async def update(self, entity):
        self.items[entity.id] = entity


class StubProposalApprovalDecisionRepository:
    def __init__(self):
        self.items: list[ReflectionProposalApprovalDecision] = []

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

    async def get_by_proposal(self, proposal_id: str):
        for item in self.items.values():
            if item.proposal_id == proposal_id:
                return item
        return None

    async def get_active_by_goal_and_surface(self, learner_goal_id: str, surface: str):
        active = [
            item for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in {"staged", "rolled_out"}
        ]
        return active[-1] if active else None

    async def list_by_proposal(self, proposal_id: str):
        return [item for item in self.items.values() if item.proposal_id == proposal_id]

    async def update(self, entity):
        self.items[entity.id] = entity


class StubProposalRolloutObservationRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposalRolloutObservation] = {}

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_id(self, observation_id: str):
        return self.items.get(observation_id)

    async def list_by_rollout(self, rollout_id: str):
        return [item for item in self.items.values() if item.rollout_id == rollout_id]


class StubProposalRolloutDecisionRepository:
    def __init__(self):
        self.items: list[ReflectionProposalRolloutDecision] = []

    async def create(self, entity):
        self.items.append(entity)

    async def list_by_rollout(self, rollout_id: str):
        return [item for item in self.items if item.rollout_id == rollout_id]


class StubGoalSkillBindingRepository:
    def __init__(self):
        self.items: dict[str, GoalSkillBinding] = {}

    async def create(self, entity: GoalSkillBinding):
        self.items[entity.id] = entity

    async def get_by_id(self, binding_id: str):
        return self.items.get(binding_id)

    async def get_by_rollout(self, rollout_id: str):
        for item in self.items.values():
            if item.rollout_id == rollout_id:
                return item
        return None

    async def get_active_by_goal_and_surface(self, learner_goal_id: str, surface: str):
        active = [
            item for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in {"staged", "rolled_out"}
        ]
        return active[-1] if active else None

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.items.values() if item.learner_goal_id == learner_goal_id]

    async def update(self, entity: GoalSkillBinding):
        self.items[entity.id] = entity


class StubTaskAttemptRepository:
    def __init__(self, attempts: list[TaskAttempt]):
        self.attempts = list(attempts)

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 20):
        return [item for item in self.attempts if item.learner_goal_id == learner_goal_id][:limit]


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

    async def list_by_session(self, session_id: str, **kwargs):
        return [item for item in self.items if item.session_id == session_id]


class StubMemoryEventRepository:
    async def list_by_profile_since(self, **kwargs):
        return []

    async def list_by_session(self, session_id: str, *, limit: int = 50):
        return []


class StubSessionMessageRepository:
    def __init__(self, messages: list | None = None):
        self.messages = list(messages or [])

    async def list_history(self, *, session_id, limit, before_id=None, **kwargs):
        return [item for item in self.messages if item.session_id == session_id][-limit:]


class StubSessionRepository:
    def __init__(self, sessions: list[LearningSession] | None = None):
        self.sessions = {item.id: item for item in sessions or []}

    async def list_by_goal(self, learner_goal_id: str, *, limit: int | None = None):
        items = [item for item in self.sessions.values() if item.learner_goal_id == learner_goal_id]
        return items[:limit] if limit is not None else items


class StubGoalRepository:
    def __init__(self, goal: LearnerGoal):
        self.goal = goal

    async def get_by_id(self, goal_id: str):
        return self.goal if self.goal.id == goal_id else None


class StubDailyTaskRepository:
    def __init__(self, tasks: list[DailyTask]):
        self.tasks = {item.id: item for item in tasks}

    async def create_many(self, entities: list[DailyTask]):
        for item in entities:
            self.tasks[item.id] = item

    async def get_by_id(self, task_id: str):
        return self.tasks.get(task_id)

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.tasks.values() if item.learner_goal_id == learner_goal_id]

    async def bulk_mark_superseded(self, study_plan_id: str):
        for task_id, task in list(self.tasks.items()):
            if task.study_plan_id == study_plan_id and task.status in {"pending", "in_progress"}:
                self.tasks[task_id] = task.with_status("superseded", result_note=task.result_note)


class StubWorkflowRunRepository:
    def __init__(self, runs: list[WorkflowRun]):
        self.runs = {item.id: item for item in runs}

    async def create(self, entity: WorkflowRun):
        self.runs[entity.id] = entity

    async def update(self, entity: WorkflowRun):
        self.runs[entity.id] = entity

    async def get_by_id(self, run_id: str):
        return self.runs.get(run_id)

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.runs.values() if item.learner_goal_id == learner_goal_id]

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 10):
        return [item for item in self.runs.values() if item.learner_goal_id == learner_goal_id][:limit]


class StubStudyPlanRepository:
    def __init__(self, plans: list[StudyPlan]):
        self.plans = {item.id: item for item in plans}

    async def create(self, entity: StudyPlan):
        self.plans[entity.id] = entity

    async def get_by_id(self, plan_id: str):
        return self.plans.get(plan_id)

    async def get_active_by_goal(self, learner_goal_id: str):
        active = [item for item in self.plans.values() if item.learner_goal_id == learner_goal_id and item.status == "active"]
        return sorted(active, key=lambda item: item.version, reverse=True)[0] if active else None

    async def update(self, entity: StudyPlan):
        self.plans[entity.id] = entity


class StubPlanStageRepository:
    def __init__(self):
        self.items = {}

    async def create_many(self, entities):
        for item in entities:
            self.items[item.id] = item


class StubGoalAutonomyStateRepository:
    def __init__(self):
        self.items = {}

    async def create(self, entity: GoalAutonomyState):
        self.items[entity.learner_goal_id] = entity

    async def get_by_goal(self, learner_goal_id: str):
        return self.items.get(learner_goal_id)

    async def update(self, entity: GoalAutonomyState):
        self.items[entity.learner_goal_id] = entity


class StubTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class StubDbSession:
    def __init__(self):
        self.nested_transactions = 0

    async def commit(self):
        return None

    async def rollback(self):
        return None

    def begin_nested(self):
        self.nested_transactions += 1
        return StubTransaction()


class StubMemoryService:
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

    async def bridge_reflection_outcome(self, **kwargs):
        return 0


class FailingLongTermMemoryMaterializationService:
    async def materialize_from_reflection_outcome(self, **kwargs):
        raise RuntimeError("materialization failed")


async def test_reflection_service_creates_low_risk_replan_action():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    plan = StudyPlan.build(
        learner_goal_id=goal.id,
        version=1,
        trigger_source="initial",
        plan_summary="Plan",
        blueprint_payload={},
        materialized_until_date=date.today() + timedelta(days=7),
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id=plan.id,
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics",
        instructions="Learn matrix basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("failed", result_note="Still confused")
    run = WorkflowRun.build(
        workflow_type="task_execution",
        trigger_source="manual_execute",
        learner_goal_id=goal.id,
        study_plan_id=plan.id,
        daily_task_id=task.id,
    )
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    record_repository = StubReflectionRecordRepository()
    action_repository = StubReflectionActionRepository()
    evidence_service = ReflectionEvidenceService(
        repository=StubReflectionEvidenceRepository(),
        message_repository=StubSessionMessageRepository(),
        memory_event_repository=StubMemoryEventRepository(),
        daily_task_repository=StubDailyTaskRepository([task]),
        workflow_run_repository=StubWorkflowRunRepository([run]),
        learner_topic_mastery_repository=None,
        audit_service=audit_service,
    )
    outcome_service = ReflectionOutcomeService(
        repository=StubOutcomeRepository(),
        task_attempt_repository=None,
        audit_service=audit_service,
    )
    governance_service = ReflectionGovernanceService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        review_decision_repository=StubReviewDecisionRepository(),
        audit_service=audit_service,
    )
    strategy_card_service = StrategyCardService(
        repository=StubStrategyCardRepository(),
        audit_service=audit_service,
    )
    reflective_memory_service = ReflectiveMemoryService(
        repository=StubReflectiveMemoryRepository(),
        audit_service=audit_service,
    )
    service = ReflectionService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([task]),
        workflow_run_repository=StubWorkflowRunRepository([run]),
        study_plan_repository=StubStudyPlanRepository([plan]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=evidence_service,
        outcome_service=outcome_service,
        governance_service=governance_service,
        strategy_card_service=strategy_card_service,
        reflective_memory_service=reflective_memory_service,
        proposal_service=ReflectionProposalService(
            repository=StubProposalRepository(),
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )

    record = await service.trigger_reflection(
        ReflectionTriggerRequest(
            learner_profile_id=profile.id,
            learner_goal_id=goal.id,
            scope="task",
            target_type="daily_task",
            target_id=task.id,
            trigger_source="task_failed",
            reflection_depth=1,
            daily_task_id=task.id,
            workflow_run_id=run.id,
            study_plan_id=plan.id,
            source_attempt_id=task.id,
        )
    )

    assert record is not None
    assert record.status in {"actioned", "completed"}
    assert any(item.action_type == "enqueue_replan_job" for item in action_repository.actions.values())
    assert any(event.event_type == "reflection.record.completed" for event in audit_repository.events)


async def test_reflection_service_blocks_high_risk_workflow_issue():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    run = WorkflowRun.build(
        workflow_type="plan_generation",
        trigger_source="initial",
        learner_goal_id=goal.id,
        study_plan_id=None,
        daily_task_id=None,
    ).fail(error_code="RuntimeError")
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    record_repository = StubReflectionRecordRepository()
    action_repository = StubReflectionActionRepository()
    evidence_service = ReflectionEvidenceService(
        repository=StubReflectionEvidenceRepository(),
        message_repository=StubSessionMessageRepository(),
        memory_event_repository=StubMemoryEventRepository(),
        daily_task_repository=StubDailyTaskRepository([]),
        workflow_run_repository=StubWorkflowRunRepository([run]),
        learner_topic_mastery_repository=None,
        audit_service=audit_service,
    )
    outcome_service = ReflectionOutcomeService(
        repository=StubOutcomeRepository(),
        task_attempt_repository=None,
        audit_service=audit_service,
    )
    governance_service = ReflectionGovernanceService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        review_decision_repository=StubReviewDecisionRepository(),
        audit_service=audit_service,
    )
    strategy_card_service = StrategyCardService(
        repository=StubStrategyCardRepository(),
        audit_service=audit_service,
    )
    reflective_memory_service = ReflectiveMemoryService(
        repository=StubReflectiveMemoryRepository(),
        audit_service=audit_service,
    )
    service = ReflectionService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([]),
        workflow_run_repository=StubWorkflowRunRepository([run]),
        study_plan_repository=StubStudyPlanRepository([]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=evidence_service,
        outcome_service=outcome_service,
        governance_service=governance_service,
        strategy_card_service=strategy_card_service,
        reflective_memory_service=reflective_memory_service,
        proposal_service=ReflectionProposalService(
            repository=StubProposalRepository(),
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )

    record = await service.trigger_reflection(
        ReflectionTriggerRequest(
            learner_profile_id=profile.id,
            learner_goal_id=goal.id,
            scope="goal",
            target_type="workflow_run",
            target_id=run.id,
            trigger_source="workflow_failed",
            reflection_depth=1,
            workflow_run_id=run.id,
            source_attempt_id=run.id,
        )
    )

    assert record is not None
    assert record.status == "needs_review"
    assert any(item.status == "blocked" for item in action_repository.actions.values())
    assert any(event.event_type == "reflection.action.blocked" for event in audit_repository.events)


async def test_reflection_service_aggregates_same_root_cause_within_cooldown():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    plan = StudyPlan.build(
        learner_goal_id=goal.id,
        version=1,
        trigger_source="initial",
        plan_summary="Plan",
        blueprint_payload={},
        materialized_until_date=date.today() + timedelta(days=7),
    )
    task_one = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id=plan.id,
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics 1",
        instructions="Learn matrix basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("failed", result_note="confused")
    task_two = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id=plan.id,
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics 2",
        instructions="Try again.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today() + timedelta(days=1),
        due_on=date.today() + timedelta(days=1),
    ).with_status("failed", result_note="still confused")
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    record_repository = StubReflectionRecordRepository()
    action_repository = StubReflectionActionRepository()
    evidence_service = ReflectionEvidenceService(
        repository=StubReflectionEvidenceRepository(),
        message_repository=StubSessionMessageRepository(),
        memory_event_repository=StubMemoryEventRepository(),
        daily_task_repository=StubDailyTaskRepository([task_one, task_two]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        learner_topic_mastery_repository=None,
        audit_service=audit_service,
    )
    service = ReflectionService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([task_one, task_two]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        study_plan_repository=StubStudyPlanRepository([plan]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=evidence_service,
        outcome_service=ReflectionOutcomeService(repository=StubOutcomeRepository(), task_attempt_repository=None, audit_service=audit_service),
        governance_service=ReflectionGovernanceService(
            reflection_record_repository=record_repository,
            reflection_action_repository=action_repository,
            review_decision_repository=StubReviewDecisionRepository(),
            audit_service=audit_service,
        ),
        strategy_card_service=StrategyCardService(repository=StubStrategyCardRepository(), audit_service=audit_service),
        reflective_memory_service=ReflectiveMemoryService(repository=StubReflectiveMemoryRepository(), audit_service=audit_service),
        proposal_service=ReflectionProposalService(
            repository=StubProposalRepository(),
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )

    first = await service.trigger_reflection(
        ReflectionTriggerRequest(
            learner_profile_id=profile.id,
            learner_goal_id=goal.id,
            scope="task",
            target_type="daily_task",
            target_id=task_one.id,
            trigger_source="task_failed",
            reflection_depth=1,
            daily_task_id=task_one.id,
            study_plan_id=plan.id,
            source_attempt_id=task_one.id,
        )
    )
    second = await service.trigger_reflection(
        ReflectionTriggerRequest(
            learner_profile_id=profile.id,
            learner_goal_id=goal.id,
            scope="task",
            target_type="daily_task",
            target_id=task_two.id,
            trigger_source="task_failed",
            reflection_depth=1,
            daily_task_id=task_two.id,
            study_plan_id=plan.id,
            source_attempt_id=task_two.id,
        )
    )

    assert first is not None and second is not None
    assert first.id == second.id
    assert second.duplicate_count == 1
    assert any(event.event_type == "reflection.record.aggregated" for event in audit_repository.events)


async def test_outcome_feedback_updates_priority_and_strategy():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics",
        instructions="Learn matrix basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("failed", result_note="confused")
    reflection = ReflectionRecord.build(
        learner_profile_id=profile.id,
        learner_goal_id=goal.id,
        daily_task_id=task.id,
        workflow_run_id=None,
        study_plan_id="plan-1",
        scope="task",
        target_type="daily_task",
        target_id=task.id,
        trigger_source="task_failed",
        reflection_depth=1,
        dedupe_key="r1",
        aggregation_key="task:key",
        duplicate_count=0,
        priority_score=0.6,
        last_duplicate_at=None,
        cooldown_until=datetime.now(timezone.utc) + timedelta(hours=24),
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        summary="summary",
        evidence_summary="evidence",
        recommended_next_step="next",
        evidence_payload={"task": {"topic_focus": "matrix multiplication"}},
    )
    attempts = [
        TaskAttempt.build(
            learner_goal_id=goal.id,
            daily_task_id="t1",
            workflow_run_id=None,
            execution_session_id=None,
            task_type="lesson",
            topic_focus="matrix multiplication",
            outcome_status="completed",
            score=1.0,
            result_note="ok",
        ),
        TaskAttempt.build(
            learner_goal_id=goal.id,
            daily_task_id="t2",
            workflow_run_id=None,
            execution_session_id=None,
            task_type="practice",
            topic_focus="matrix multiplication",
            outcome_status="completed",
            score=1.0,
            result_note="ok",
        ),
        TaskAttempt.build(
            learner_goal_id=goal.id,
            daily_task_id="t3",
            workflow_run_id=None,
            execution_session_id=None,
            task_type="practice",
            topic_focus="matrix multiplication",
            outcome_status="failed",
            score=0.0,
            result_note="oops",
        ),
    ]
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    record_repository = StubReflectionRecordRepository()
    record_repository.records[reflection.id] = reflection
    action_repository = StubReflectionActionRepository()
    action = ReflectionAction.build(
        reflection_record_id=reflection.id,
        action_type="enqueue_replan_job",
        risk_level="low",
        approval_required=False,
        payload={"mode": "partial"},
    )
    action_repository.actions[action.id] = action
    strategy_repository = StubStrategyCardRepository()
    reflective_memory_repository = StubReflectiveMemoryRepository()
    proposal_service = ReflectionProposalService(
        repository=StubProposalRepository(),
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        audit_service=audit_service,
    )
    outcome_service = ReflectionOutcomeService(
        repository=StubOutcomeRepository(),
        task_attempt_repository=StubTaskAttemptRepository(attempts),
        audit_service=audit_service,
    )
    await outcome_service.start_tracking(
        reflection=reflection,
        topic_key="matrix multiplication",
        baseline_snapshot={},
    )
    service = ReflectionService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([task]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        study_plan_repository=StubStudyPlanRepository([]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=None,
        outcome_service=outcome_service,
        governance_service=ReflectionGovernanceService(
            reflection_record_repository=record_repository,
            reflection_action_repository=action_repository,
            review_decision_repository=StubReviewDecisionRepository(),
            audit_service=audit_service,
        ),
        strategy_card_service=StrategyCardService(repository=strategy_repository, audit_service=audit_service),
        reflective_memory_service=ReflectiveMemoryService(repository=reflective_memory_repository, audit_service=audit_service),
        proposal_service=proposal_service,
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )

    evaluation = await outcome_service.evaluate(reflection=reflection, topic_key="matrix multiplication")
    updated = await service.apply_outcome_feedback(reflection=reflection, evaluation=evaluation)

    assert evaluation is not None
    assert evaluation.evaluation_status == "effective"
    assert updated.priority_score > reflection.priority_score
    assert await StrategyCardService(repository=strategy_repository, audit_service=audit_service).get_active(goal.id) is not None
    assert len(reflective_memory_repository.items) >= 1


async def test_reflection_materialization_failure_is_audited_without_blocking_feedback():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics",
        instructions="Learn matrix basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("failed", result_note="confused")
    reflection = ReflectionRecord.build(
        learner_profile_id=profile.id,
        learner_goal_id=goal.id,
        daily_task_id=task.id,
        workflow_run_id="run-1",
        study_plan_id="plan-1",
        scope="task",
        target_type="daily_task",
        target_id=task.id,
        trigger_source="task_failed",
        reflection_depth=1,
        dedupe_key="r1",
        aggregation_key="task:key",
        duplicate_count=0,
        priority_score=0.6,
        last_duplicate_at=None,
        cooldown_until=datetime.now(timezone.utc) + timedelta(hours=24),
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        summary="summary",
        evidence_summary="evidence",
        recommended_next_step="next",
        evidence_payload={"task": {"topic_focus": "matrix multiplication"}},
    )
    evaluation = ReflectionOutcomeEvaluation.build(
        reflection_record_id=reflection.id,
        learner_goal_id=goal.id,
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    ).with_result(
        evaluation_status="effective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 2},
        improvement_score=0.7,
        evaluation_note="improved",
        evaluated=True,
    )
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    job_repository = StubScheduledAutonomyJobRepository()
    record_repository = StubReflectionRecordRepository()
    record_repository.records[reflection.id] = reflection
    action_repository = StubReflectionActionRepository()
    db_session = StubDbSession()
    service = ReflectionService(
        reflection_record_repository=record_repository,
        reflection_action_repository=action_repository,
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([task]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        study_plan_repository=StubStudyPlanRepository([]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        long_term_memory_materialization_service=FailingLongTermMemoryMaterializationService(),
        autonomy_job_service=AutonomyJobService(repository=job_repository, audit_service=audit_service),
        evidence_service=None,
        outcome_service=None,
        governance_service=ReflectionGovernanceService(
            reflection_record_repository=record_repository,
            reflection_action_repository=action_repository,
            review_decision_repository=StubReviewDecisionRepository(),
            audit_service=audit_service,
        ),
        strategy_card_service=StrategyCardService(repository=StubStrategyCardRepository(), audit_service=audit_service),
        reflective_memory_service=ReflectiveMemoryService(repository=StubReflectiveMemoryRepository(), audit_service=audit_service),
        proposal_service=ReflectionProposalService(
            repository=StubProposalRepository(),
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        db_session=db_session,
        reflection_max_depth=2,
    )

    updated = await service.apply_outcome_feedback(reflection=reflection, evaluation=evaluation)

    assert updated.priority_score > reflection.priority_score
    assert record_repository.records[reflection.id] == updated
    assert db_session.nested_transactions == 1
    failure_events = [
        item
        for item in audit_repository.events
        if item.event_type == "long_term_memory.materialization.failed"
    ]
    assert len(failure_events) == 1
    assert failure_events[0].event_data["source_type"] == "reflection_outcome"
    assert failure_events[0].event_data["reflection_id"] == reflection.id
    assert failure_events[0].event_data["evaluation_id"] == evaluation.id
    assert failure_events[0].event_data["daily_task_id"] == task.id
    assert failure_events[0].event_data["workflow_run_id"] == "run-1"
    assert failure_events[0].event_data["error_code"] == "RuntimeError"
    assert failure_events[0].event_data["replay_enqueued"] is True
    assert failure_events[0].event_data["replay_skip_reason"] is None
    assert len(job_repository.jobs) == 1
    job = next(iter(job_repository.jobs.values()))
    assert job.job_type == "long_term_memory_materialization_replay"
    assert job.learner_goal_id == goal.id
    assert job.idempotency_key == f"ltm-replay:reflection_outcome:{reflection.id}:{evaluation.id}"
    assert job.payload == {
        "source_type": "reflection_outcome",
        "reflection_id": reflection.id,
        "evaluation_id": evaluation.id,
    }
    assert any(item.event_type == "reflection.outcome.feedback.applied" for item in audit_repository.events)


async def test_reflection_record_completion_creates_proposals():
    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="review",
        execution_mode="quiz",
        title="Review basics",
        instructions="Review basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=3,
        estimated_minutes=20,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("failed", result_note="still weak")
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    service = ReflectionService(
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_action_repository=StubReflectionActionRepository(),
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository([task]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        study_plan_repository=StubStudyPlanRepository([]),
        task_attempt_repository=None,
        learner_topic_mastery_repository=None,
        goal_autonomy_state_repository=None,
        session_repository=None,
        memory_service=StubMemoryService(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        evidence_service=ReflectionEvidenceService(
            repository=StubReflectionEvidenceRepository(),
            message_repository=StubSessionMessageRepository(),
            memory_event_repository=StubMemoryEventRepository(),
            daily_task_repository=StubDailyTaskRepository([task]),
            workflow_run_repository=StubWorkflowRunRepository([]),
            learner_topic_mastery_repository=None,
            audit_service=audit_service,
        ),
        outcome_service=ReflectionOutcomeService(repository=StubOutcomeRepository(), task_attempt_repository=None, audit_service=audit_service),
        governance_service=ReflectionGovernanceService(
            reflection_record_repository=StubReflectionRecordRepository(),
            reflection_action_repository=StubReflectionActionRepository(),
            review_decision_repository=StubReviewDecisionRepository(),
            audit_service=audit_service,
        ),
        strategy_card_service=StrategyCardService(repository=StubStrategyCardRepository(), audit_service=audit_service),
        reflective_memory_service=ReflectiveMemoryService(repository=StubReflectiveMemoryRepository(), audit_service=audit_service),
        proposal_service=ReflectionProposalService(
            repository=proposal_repository,
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            audit_service=audit_service,
        ),
        replay_service=ReflectionReplayService(repository=StubProposalEvaluationRepository(), audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        reflection_max_depth=2,
    )

    record = await service.trigger_reflection(
        ReflectionTriggerRequest(
            learner_profile_id=profile.id,
            learner_goal_id=goal.id,
            scope="task",
            target_type="daily_task",
            target_id=task.id,
            trigger_source="task_failed",
            reflection_depth=1,
            daily_task_id=task.id,
            source_attempt_id=task.id,
        )
    )

    assert record is not None
    assert len(proposal_repository.items) >= 1


async def test_proposal_enqueue_sandbox_and_approve_flow():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    approval_repository = StubProposalApprovalDecisionRepository()

    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="prompt_optimization",
        target_scope="hint",
        priority_score=0.7,
        hypothesis="Need smaller steps.",
        change_summary="Use scaffolded hints.",
        structured_patch_payload={
            "response_preference_bias": "guided",
            "hint_level_preference": "scaffolded",
            "teaching_goal_override": "unblock next step",
        },
        expected_improvement="Reduce confusion.",
        risk_level="low",
        evidence_snapshot={},
    )
    await proposal_repository.create(proposal)
    job_service = AutonomyJobService(repository=None, audit_service=audit_service)
    service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=approval_repository,
        autonomy_job_service=job_service,
        audit_service=audit_service,
    )

    with pytest.raises(ValidationError):
        await service.approve(
            proposal_id=proposal.id,
            operator_id="operator",
            reason_code="premature",
            reason_note=None,
        )

    queued = proposal.enqueue_sandbox(sandbox_run_id="job-1")
    await proposal_repository.update(queued)
    running = await service.mark_sandbox_started(proposal_id=proposal.id, sandbox_run_id="run-1")
    assert running.status == "sandbox_running"
    completed = await service.mark_sandbox_completed(
        proposal_id=proposal.id,
        sandbox_run_id="run-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    )
    assert completed.status == "sandbox_completed"
    approved = await service.approve(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="looks_good",
        reason_note="Passes governed sandbox.",
    )
    assert approved.status == "approved"
    assert len(approval_repository.items) == 1


async def test_proposal_service_auto_admits_low_risk_proposals_to_sandbox():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    approval_repository = StubProposalApprovalDecisionRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=approval_repository,
        evaluation_repository=evaluation_repository,
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        audit_service=audit_service,
    )
    reflection = ReflectionRecord.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id="task-1",
        workflow_run_id=None,
        study_plan_id="plan-1",
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        dedupe_key="dedupe-1",
        aggregation_key="agg-1",
        duplicate_count=0,
        priority_score=0.7,
        last_duplicate_at=None,
        cooldown_until=None,
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        summary="Need better scaffolding.",
        evidence_summary="Repeated confusion.",
        recommended_next_step="Use more scaffolding.",
        evidence_payload={"session_signals": {"hint_turn_count": 2}, "task": {"task_type": "lesson"}},
    )

    proposals = await service.create_from_reflection(reflection=reflection)

    assert proposals
    assert all(item.status == "proposed" for item in proposals)
    assert any(event.event_type in {"reflection.proposal.created", "reflection.proposal.manual_review_required"} for event in audit_repository.events)


@pytest.mark.asyncio
async def test_effective_reflection_creates_skill_package_proposals():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        autonomy_job_service=AutonomyJobService(repository=None, audit_service=audit_service),
        audit_service=audit_service,
    )
    reflection = ReflectionRecord.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id="task-1",
        workflow_run_id=None,
        study_plan_id=None,
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        dedupe_key="dedupe-1",
        aggregation_key="agg-1",
        duplicate_count=1,
        priority_score=0.82,
        last_duplicate_at=None,
        cooldown_until=None,
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        summary="Repeated concept confusion.",
        evidence_summary="Learner repeatedly misses the same concept.",
        recommended_next_step="Add guided remediation.",
        evidence_payload={"task": {"topic_focus": "matrices", "task_type": "lesson"}},
    )

    proposals = await proposal_service.create_skill_packages_from_reflection(reflection=reflection)

    assert proposals
    assert all(item.proposal_type == "skill_package" for item in proposals)
    assert {item.target_scope for item in proposals} == {"chat", "hint", "quiz"}


async def test_sandbox_service_executes_and_persists_run():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    sandbox_run_repository = StubProposalSandboxRunRepository()
    approval_repository = StubProposalApprovalDecisionRepository()
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="workflow_optimization",
        target_scope="review_scheduling",
        priority_score=0.8,
        hypothesis="Need denser reviews after failures.",
        change_summary="Tighten review intervals.",
        structured_patch_payload={
            "review_interval_policy": "denser",
            "assessment_threshold_policy": "earlier",
            "replan_mode_policy": "more_aggressive",
        },
        expected_improvement="Improve recovery.",
        risk_level="medium",
        evidence_snapshot={},
    )
    await proposal_repository.create(proposal)
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=approval_repository,
        audit_service=audit_service,
    )
    sandbox_service = ReflectionProposalSandboxService(
        sandbox_run_repository=sandbox_run_repository,
        proposal_service=proposal_service,
        replay_service=ReflectionReplayService(repository=evaluation_repository, audit_service=audit_service),
        audit_service=audit_service,
        strategy_card_service=StrategyCardService(repository=StubStrategyCardRepository(), audit_service=audit_service),
        task_attempt_repository=StubTaskAttemptRepository([]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        chat_service=None,
    )

    result = await sandbox_service.execute(proposal_id=proposal.id)

    assert result.status == "completed"
    assert result.proposal_id == proposal.id
    stored_proposal = await proposal_service.get(proposal.id)
    assert stored_proposal.status == "sandbox_completed"
    assert stored_proposal.latest_sandbox_run_id == result.id
    evaluation = await evaluation_repository.get_by_proposal(proposal.id)
    assert evaluation is not None


async def test_outcome_repository_lists_pending_items():
    repository = StubOutcomeRepository()
    pending = ReflectionOutcomeEvaluation.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    )
    completed = ReflectionOutcomeEvaluation.build(
        reflection_record_id="reflection-2",
        learner_goal_id="goal-1",
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    ).with_result(
        evaluation_status="effective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 2},
        improvement_score=0.7,
        evaluation_note="improved",
        evaluated=True,
    )
    await repository.create(pending)
    await repository.create(completed)

    listed = await repository.list_pending(learner_goal_id="goal-1", limit=10)

    assert len(listed) == 1
    assert listed[0].evaluation_status == "pending"


async def test_rollout_service_activates_promotes_and_rolls_back_plan_generation():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    decision_repository = StubProposalRolloutDecisionRepository()
    goal_state_repository = StubGoalAutonomyStateRepository()
    goal = LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id=goal.id,
        proposal_type="workflow_optimization",
        target_scope="plan_generation",
        priority_score=0.8,
        hypothesis="Need denser reviews.",
        change_summary="Tighten planner review/assessment/replan bias.",
        structured_patch_payload={
            "review_interval_policy": "denser",
            "assessment_threshold_policy": "earlier",
            "replan_mode_policy": "more_aggressive",
        },
        expected_improvement="Improve recovery.",
        risk_level="medium",
        evidence_snapshot={},
    )
    proposal = proposal.enqueue_sandbox(
        sandbox_run_id="job-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    await proposal_repository.create(proposal)
    planner = PlannerService(
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        audit_service=audit_service,
        strategy_card_service=StrategyCardService(
            repository=StubStrategyCardRepository(),
            audit_service=audit_service,
        ),
    )
    workflow_service = WorkflowRunService(
        repository=StubWorkflowRunRepository([]),
        db_session=StubDbSession(),
        audit_service=audit_service,
    )
    rollout_service = ReflectionProposalRolloutService(
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        rollout_observation_repository=observation_repository,
        rollout_decision_repository=decision_repository,
        goal_repository=StubGoalRepository(goal),
        study_plan_repository=StubStudyPlanRepository([]),
        plan_stage_repository=StubPlanStageRepository(),
        daily_task_repository=StubDailyTaskRepository([]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        goal_autonomy_state_repository=goal_state_repository,
        goal_skill_binding_repository=StubGoalSkillBindingRepository(),
        session_repository=StubSessionRepository([]),
        message_repository=StubSessionMessageRepository([]),
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_evidence_repository=StubReflectionEvidenceRepository(),
        task_attempt_repository=StubTaskAttemptRepository([]),
        planner_service=planner,
        workflow_run_service=workflow_service,
        observation_scheduler=ReflectionProposalRolloutObservationScheduler(
            rollout_repository=rollout_repository,
            autonomy_job_service=None,
            audit_service=audit_service,
        ),
        audit_service=audit_service,
    )

    activated = await rollout_service.activate(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="activate",
        reason_note=None,
    )
    assert activated.status == "staged"
    assert activated.staged_plan_id is not None

    promoted = await rollout_service.promote(
        rollout_id=activated.id,
        operator_id="operator",
        reason_code="promote",
        reason_note=None,
    )
    assert promoted.status == "rolled_out"

    rolled_back = await rollout_service.rollback(
        rollout_id=activated.id,
        operator_id="operator",
        reason_code="rollback",
        reason_note=None,
    )
    assert rolled_back.status == "rolled_back"
    assert rolled_back.rollback_restored_plan_id is not None
    assert len(decision_repository.items) == 3


@pytest.mark.asyncio
async def test_skill_package_rollout_creates_goal_skill_binding():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    goal = LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Matrices",
        target_outcome="Master matrix multiplication",
        weekly_study_minutes=180,
        deadline_date=date.today() + timedelta(days=60),
        baseline_note=None,
    )
    proposal_repository = StubProposalRepository()
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    decision_repository = StubProposalRolloutDecisionRepository()
    binding_repository = StubGoalSkillBindingRepository()
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id=goal.id,
        proposal_type="skill_package",
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Reusable quiz remediation helps.",
        change_summary="Create quiz skill package.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "quiz_knowledge_gap",
            "bundle_id": "bundle-1",
            "surface": "quiz",
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"question_count": 3, "feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        expected_improvement="Reuse verified quiz remediation.",
        risk_level="low",
        evidence_snapshot={},
    ).enqueue_sandbox(
        sandbox_run_id="sandbox-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    await proposal_repository.create(proposal)
    rollout_service = ReflectionProposalRolloutService(
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        rollout_observation_repository=observation_repository,
        rollout_decision_repository=decision_repository,
        goal_repository=StubGoalRepository(goal),
        study_plan_repository=StubStudyPlanRepository([]),
        plan_stage_repository=StubPlanStageRepository(),
        daily_task_repository=StubDailyTaskRepository([]),
        workflow_run_repository=StubWorkflowRunRepository([]),
        goal_autonomy_state_repository=None,
        goal_skill_binding_repository=binding_repository,
        session_repository=StubSessionRepository([]),
        message_repository=StubSessionMessageRepository([]),
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_evidence_repository=StubReflectionEvidenceRepository(),
        task_attempt_repository=StubTaskAttemptRepository([]),
        planner_service=PlannerService(llm_provider=MockLLMProvider("mock-tutor-v1"), audit_service=audit_service),
        workflow_run_service=WorkflowRunService(
            repository=StubWorkflowRunRepository([]),
            db_session=StubDbSession(),
            audit_service=audit_service,
        ),
        observation_scheduler=None,
        audit_service=audit_service,
    )

    activated = await rollout_service.activate(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="activate",
        reason_note=None,
    )

    binding = await binding_repository.get_by_rollout(activated.id)
    assert binding is not None
    assert binding.surface == "quiz"
    assert binding.status == "staged"
