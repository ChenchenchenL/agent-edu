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
from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
from agent_core.application.services.reflection_proposal_sandbox import ReflectionProposalSandboxService
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposal_rollout_auto_governance import (
    ReflectionProposalRolloutDecisionOrchestrator,
    ReflectionProposalRolloutDecisionScheduler,
)
from agent_core.application.services.reflection_proposal_rollouts import ReflectionProposalRolloutService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.skills import SkillCandidateService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.tool_plan_runtime import ToolPlanRuntimeExecutor
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
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
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

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ):
        statuses = {"staged", "rolled_out"} if include_staged else {"rolled_out"}
        active = [
            item for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in statuses
        ]
        return active[-1] if active else None

    async def list_by_proposal(self, proposal_id: str):
        return [item for item in self.items.values() if item.proposal_id == proposal_id]

    async def update(self, entity):
        self.items[entity.id] = entity


class StubSkillUsageEventRepository:
    def __init__(self, events: list[SkillUsageEvent] | None = None):
        self.events: list[SkillUsageEvent] = list(events or [])

    async def list_events(
        self,
        *,
        artifact_id=None,
        skill_name=None,
        learner_goal_id=None,
        session_id=None,
        surface=None,
        outcome_status=None,
        resolver_status=None,
        created_at_from=None,
        limit=50,
    ):
        events = list(self.events)
        if artifact_id is not None:
            events = [item for item in events if item.skill_artifact_id == artifact_id]
        if skill_name is not None:
            events = [item for item in events if item.skill_name == skill_name]
        if learner_goal_id is not None:
            events = [item for item in events if item.learner_goal_id == learner_goal_id]
        if session_id is not None:
            events = [item for item in events if item.session_id == session_id]
        if surface is not None:
            events = [item for item in events if item.surface == surface]
        if outcome_status is not None:
            events = [item for item in events if item.outcome_status == outcome_status]
        if resolver_status is not None:
            events = [item for item in events if item.resolver_status == resolver_status]
        if created_at_from is not None:
            events = [item for item in events if item.created_at >= created_at_from]
        return events[:limit]


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

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ):
        active = await self.list_active_by_goal_and_surface(
            learner_goal_id,
            surface,
            include_staged=include_staged,
        )
        return active[0] if active else None

    async def list_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ):
        statuses = {"staged", "rolled_out"} if include_staged else {"rolled_out"}
        active = [
            item for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in statuses
        ]
        return sorted(active, key=lambda item: (item.priority_score, item.updated_at), reverse=True)

    async def list_by_goal(self, learner_goal_id: str):
        return [item for item in self.items.values() if item.learner_goal_id == learner_goal_id]

    async def update(self, entity: GoalSkillBinding):
        self.items[entity.id] = entity


class StubSkillArtifactRepository:
    def __init__(
        self,
        artifact: SkillArtifact | None = None,
        items: list[SkillArtifact] | None = None,
    ):
        self.items: dict[str, SkillArtifact] = {}
        if artifact is not None:
            self.items[artifact.id] = artifact
        for item in items or []:
            self.items[item.id] = item

    async def create(self, entity):
        self.items[entity.id] = entity

    async def get_by_id(self, artifact_id: str):
        return self.items.get(artifact_id)

    async def get_by_source_proposal_id(self, proposal_id: str):
        for item in self.items.values():
            if item.source_proposal_id == proposal_id:
                return item
        return None

    async def max_candidate_patch_version(self, name: str):
        max_patch = -1
        for artifact in self.items.values():
            if artifact.name != name or not artifact.version.startswith("0.1."):
                continue
            patch = artifact.version.removeprefix("0.1.")
            if patch.isdecimal():
                max_patch = max(max_patch, int(patch))
        return max_patch

    async def update(self, entity: SkillArtifact):
        self.items[entity.id] = entity


async def test_rollout_resolver_skips_staged_overlay_when_not_included():
    repository = StubProposalRolloutRepository()
    rolled_out = ReflectionProposalRollout.build(
        proposal_id="proposal-rolled-out",
        learner_goal_id="goal-1",
        surface="quiz",
        baseline_snapshot={},
        runtime_overlay_payload={"mode": "rolled_out"},
        activated_by="operator",
    ).with_status("rolled_out")
    staged = ReflectionProposalRollout.build(
        proposal_id="proposal-staged",
        learner_goal_id="goal-1",
        surface="quiz",
        baseline_snapshot={},
        runtime_overlay_payload={"mode": "staged"},
        activated_by="operator",
    )
    await repository.create(rolled_out)
    await repository.create(staged)
    resolver = ReflectionProposalRolloutResolver(rollout_repository=repository)

    default_overlay = await resolver.get_active_overlay(learner_goal_id="goal-1", surface="quiz")
    staged_overlay = await resolver.get_active_overlay(
        learner_goal_id="goal-1",
        surface="quiz",
        include_staged=True,
    )

    assert default_overlay is not None
    assert default_overlay.rollout_id == rolled_out.id
    assert default_overlay.status == "rolled_out"
    assert staged_overlay is not None
    assert staged_overlay.rollout_id == staged.id
    assert staged_overlay.status == "staged"


async def test_goal_skill_binding_resolver_skips_staged_binding_when_not_included():
    repository = StubGoalSkillBindingRepository()
    rolled_out = GoalSkillBinding.build(
        proposal_id="proposal-rolled-out",
        rollout_id="rollout-rolled-out",
        learner_goal_id="goal-1",
        surface="quiz",
        priority_score=0.2,
        match_rules={},
        runtime_directives={"mode": "rolled_out"},
        tool_plan=[],
    ).with_status("rolled_out")
    staged = GoalSkillBinding.build(
        proposal_id="proposal-staged",
        rollout_id="rollout-staged",
        learner_goal_id="goal-1",
        surface="quiz",
        priority_score=0.9,
        match_rules={},
        runtime_directives={"mode": "staged"},
        tool_plan=[],
    )
    await repository.create(rolled_out)
    await repository.create(staged)
    resolver = GoalSkillBindingResolver(repository=repository)

    default_binding = await resolver.get_active_binding(learner_goal_id="goal-1", surface="quiz")
    staged_binding = await resolver.get_active_binding(
        learner_goal_id="goal-1",
        surface="quiz",
        include_staged=True,
    )

    assert default_binding is not None
    assert default_binding.binding_id == rolled_out.id
    assert default_binding.status == "rolled_out"
    assert staged_binding is not None
    assert staged_binding.binding_id == staged.id
    assert staged_binding.status == "staged"


async def test_goal_skill_binding_resolver_falls_back_to_next_matching_binding():
    repository = StubGoalSkillBindingRepository()
    high_priority_non_match = GoalSkillBinding.build(
        proposal_id="proposal-non-match",
        rollout_id="rollout-non-match",
        learner_goal_id="goal-1",
        surface="quiz",
        priority_score=0.9,
        match_rules={"topic_keys": ["calculus"]},
        runtime_directives={"mode": "wrong-topic"},
        tool_plan=[],
    ).with_status("rolled_out")
    lower_priority_match = GoalSkillBinding.build(
        proposal_id="proposal-match",
        rollout_id="rollout-match",
        learner_goal_id="goal-1",
        surface="quiz",
        priority_score=0.4,
        match_rules={"topic_keys": ["algebra"]},
        runtime_directives={"mode": "right-topic"},
        tool_plan=[],
    ).with_status("rolled_out")
    await repository.create(high_priority_non_match)
    await repository.create(lower_priority_match)
    resolver = GoalSkillBindingResolver(repository=repository)

    binding = await resolver.get_active_binding(
        learner_goal_id="goal-1",
        surface="quiz",
        topic_key="algebra",
    )

    assert binding is not None
    assert binding.binding_id == lower_priority_match.id
    assert binding.runtime_directives == {"mode": "right-topic"}


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


def _approved_rollout_proposal(
    *,
    learner_goal_id: str,
    proposal_type: str = "skill_package",
    target_scope: str = "quiz",
) -> ReflectionProposal:
    if proposal_type == "skill_package":
        structured_patch_payload = {
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "bundle_id": "bundle-1",
            "surface": target_scope,
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"question_count": 3, "feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        }
    elif proposal_type == "workflow_optimization":
        structured_patch_payload = {
            "review_interval_policy": "denser",
            "assessment_threshold_policy": "earlier",
            "replan_mode_policy": "more_aggressive",
        }
    else:
        structured_patch_payload = {
            "response_preference_bias": "scaffold_first",
            "hint_level_preference": "targeted",
            "teaching_goal_override": "reduce_direct_answers",
        }
    return ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id=learner_goal_id,
        proposal_type=proposal_type,
        target_scope=target_scope,
        priority_score=0.8,
        hypothesis="Reusable rollout improvement helps.",
        change_summary="Apply rollout improvement.",
        structured_patch_payload=structured_patch_payload,
        expected_improvement="Improve learner outcomes.",
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


def _rollout_service_for_tests(
    *,
    audit_repository: StubAuditRepository,
    goal: LearnerGoal,
    proposal_repository: StubProposalRepository,
    rollout_repository: StubProposalRolloutRepository,
    observation_repository: StubProposalRolloutObservationRepository | None = None,
    decision_repository: StubProposalRolloutDecisionRepository | None = None,
    binding_repository: StubGoalSkillBindingRepository | None = None,
    artifact_repository: StubSkillArtifactRepository | None = None,
    usage_repository: StubSkillUsageEventRepository | None = None,
    observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
) -> ReflectionProposalRolloutService:
    audit_service = AuditService(repository=audit_repository)
    workflow_repository = StubWorkflowRunRepository([])
    return ReflectionProposalRolloutService(
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        rollout_observation_repository=observation_repository or StubProposalRolloutObservationRepository(),
        rollout_decision_repository=decision_repository or StubProposalRolloutDecisionRepository(),
        goal_repository=StubGoalRepository(goal),
        study_plan_repository=StubStudyPlanRepository([]),
        plan_stage_repository=StubPlanStageRepository(),
        daily_task_repository=StubDailyTaskRepository([]),
        workflow_run_repository=workflow_repository,
        goal_autonomy_state_repository=None,
        goal_skill_binding_repository=binding_repository or StubGoalSkillBindingRepository(),
        skill_artifact_repository=artifact_repository or StubSkillArtifactRepository(),
        session_repository=StubSessionRepository([]),
        message_repository=StubSessionMessageRepository([]),
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_evidence_repository=StubReflectionEvidenceRepository(),
        task_attempt_repository=StubTaskAttemptRepository([]),
        usage_repository=usage_repository or StubSkillUsageEventRepository(),
        planner_service=PlannerService(llm_provider=MockLLMProvider("mock-tutor-v1"), audit_service=audit_service),
        workflow_run_service=WorkflowRunService(
            repository=workflow_repository,
            db_session=StubDbSession(),
            audit_service=audit_service,
        ),
        observation_scheduler=observation_scheduler,
        audit_service=audit_service,
    )


def _skill_package_artifact_for_proposal(
    proposal: ReflectionProposal,
    *,
    status: str,
) -> SkillArtifact:
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope=proposal.target_scope,
        status="staged" if status in {"active", "stable", "suppressed"} else status,
        description="Learned quiz skill package.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "surface": proposal.target_scope,
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"question_count": 3, "feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
        tool_plan=[],
        source_reflection_ids=[proposal.reflection_record_id],
        source_proposal_id=proposal.id,
        quality_score=0.8,
        created_by="reflection_proposal",
    )
    if status == "active":
        return artifact.mark_active(operator_id="operator")
    if status == "stable":
        return artifact.mark_active(operator_id="operator").mark_stable(operator_id="operator")
    if status == "suppressed":
        return artifact.mark_active(operator_id="operator").mark_suppressed(
            operator_id="operator-suppress",
            reason_code="operator_request",
            reason_note="Temporarily suppress rollout artifact.",
        )
    return artifact


def _realizable_source_artifact() -> SkillArtifact:
    return SkillArtifact.build(
        name="create_quiz",
        version="0.1.8",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Current quiz skill package.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {"task_types": ["practice"], "topic_keys": ["matrices"]},
            "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
        },
        runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
        tool_plan=[],
        compatibility_contract={
            "surfaces": ["quiz"],
            "implementation_binding": "create_quiz",
            "input_schema_version": "1.0",
            "output_schema_version": "1.0",
            "dynamic_execution": False,
        },
        source_reflection_ids=["reflection-source"],
        source_memory_ids=["memory-source"],
        source_proposal_id="proposal-source",
        quality_score=0.8,
        created_by="operator",
        approved_by="operator",
    )


def _related_merge_artifact(
    *,
    source: SkillArtifact,
    status: str = "stable",
    name: str | None = None,
    scope: str | None = None,
    implementation_binding: str | None = None,
) -> SkillArtifact:
    artifact_name = name or source.name
    artifact_scope = scope or source.scope
    return SkillArtifact.build(
        name=artifact_name,
        version="0.1.9",
        skill_type="learned",
        scope=artifact_scope,
        status=status,
        description="Related merge skill package.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {
                "task_types": ["review", "practice"],
                "topic_keys": ["matrices", "linear-systems"],
                "non_list_rule": "ignored",
            },
            "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 4},
        },
        runtime_directives={"question_count": 5, "feedback_style": "direct"},
        tool_plan=[],
        compatibility_contract={
            "surfaces": [artifact_scope],
            "implementation_binding": implementation_binding or artifact_name,
            "input_schema_version": "1.0",
            "output_schema_version": "1.0",
            "dynamic_execution": False,
        },
        source_reflection_ids=["reflection-related"],
        quality_score=0.75,
        created_by="operator",
        approved_by="operator",
    )


def _skill_patch_request_proposal(
    *,
    artifact: SkillArtifact,
    status: str = "approved",
    evaluation_status: str = "effective",
) -> ReflectionProposal:
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-patch-1",
        learner_goal_id="goal-1",
        proposal_type="skill_patch_request",
        target_scope=artifact.scope,
        priority_score=0.8,
        hypothesis=f"Curator evidence indicates {artifact.name} needs a patch.",
        change_summary="Create governed patch request.",
        structured_patch_payload={
            "artifact_id": artifact.id,
            "skill_name": artifact.name,
            "skill_version": artifact.version,
            "scope": artifact.scope,
            "surface": artifact.scope,
            "recommendation_id": "recommendation-1",
            "recommendation_reason_code": "quality_regression",
            "usage_event_ids": ["usage-1", "usage-2"],
            "related_artifact_ids": ["artifact-related"],
            "evidence_snapshot": {"usage_event_ids": ["usage-1", "usage-2"]},
            "metrics_snapshot": {"negative_usage_rate": 0.5},
        },
        expected_improvement="Route patch evidence through governed review.",
        risk_level="medium",
        evidence_snapshot={"source": "skill_curator_recommendation"},
    )
    if status == "proposed":
        return proposal
    completed = proposal.enqueue_sandbox(
        sandbox_run_id="sandbox-patch-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-patch-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-patch-1",
        evaluation_status=evaluation_status,
        evaluation_summary=f"sandbox:{evaluation_status}",
    )
    if status == "sandbox_completed":
        return completed
    if status == "approved":
        return completed.approve(
            operator_id="operator",
            reason_code="validated",
            reason_note=None,
        )
    return completed.with_status(status)


def _effective_patch_request_evaluation(proposal: ReflectionProposal) -> ReflectionProposalEvaluation:
    return ReflectionProposalEvaluation.build(
        proposal_id=proposal.id,
        comparison_window_size=2,
        baseline_policy_snapshot={"artifact_id": proposal.structured_patch_payload["artifact_id"]},
        candidate_policy_snapshot={"usage_event_ids": proposal.structured_patch_payload["usage_event_ids"]},
        evaluator_type="rule",
        sandbox_run_id=proposal.latest_sandbox_run_id,
    ).with_result(
        evaluation_status="effective",
        simulated_outcome_summary={"score_delta": 0.15},
        score_delta=0.15,
        sandbox_run_id=proposal.latest_sandbox_run_id,
    )


def _rolled_out_rollout_for_proposal(proposal: ReflectionProposal) -> ReflectionProposalRollout:
    return ReflectionProposalRollout.build(
        proposal_id=proposal.id,
        learner_goal_id=proposal.learner_goal_id,
        surface=proposal.target_scope,
        baseline_snapshot=proposal.structured_patch_payload,
        runtime_overlay_payload={},
        activated_by="operator",
    ).with_status("rolled_out")


def _rolled_out_binding_for_rollout(
    *,
    proposal: ReflectionProposal,
    rollout: ReflectionProposalRollout,
) -> GoalSkillBinding:
    return GoalSkillBinding.build(
        proposal_id=proposal.id,
        rollout_id=rollout.id,
        learner_goal_id=proposal.learner_goal_id,
        surface=proposal.target_scope,
        priority_score=proposal.priority_score,
        match_rules=dict(proposal.structured_patch_payload.get("match_rules") or {}),
        runtime_directives=dict(proposal.structured_patch_payload.get("runtime_directives") or {}),
        tool_plan=[dict(item) for item in proposal.structured_patch_payload.get("tool_plan") or []],
    ).with_status("rolled_out")


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
        autonomy_job_service=None,
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


async def test_proposal_service_creates_reference_only_skill_patch_request_from_recommendation():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    proposal = await proposal_service.create_skill_patch_request_from_recommendation(
        recommendation_id="recommendation-1",
        artifact_id="artifact-1",
        skill_name="create_quiz",
        skill_version="0.1.0",
        scope="quiz",
        surface="quiz",
        recommendation_reason_code="quality_regression",
        evidence_snapshot={
            "usage_event_ids": ["usage-1", "usage-2"],
            "negative_usage_event_ids": ["usage-2", "usage-3"],
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
        },
        metrics_snapshot={"negative_usage_rate": 0.5},
        related_artifact_ids=["artifact-related"],
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        operator_id="operator",
    )
    described = await proposal_service.describe(proposal)

    assert proposal.proposal_type == "skill_patch_request"
    assert proposal.status == "proposed"
    assert proposal.target_scope == "quiz"
    assert proposal.structured_patch_payload == {
        "artifact_id": "artifact-1",
        "skill_name": "create_quiz",
        "skill_version": "0.1.0",
        "scope": "quiz",
        "surface": "quiz",
        "recommendation_id": "recommendation-1",
        "recommendation_reason_code": "quality_regression",
        "usage_event_ids": ["usage-1", "usage-2", "usage-3"],
        "related_artifact_ids": ["artifact-related"],
        "evidence_snapshot": {
            "usage_event_ids": ["usage-1", "usage-2"],
            "negative_usage_event_ids": ["usage-2", "usage-3"],
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
        },
        "metrics_snapshot": {"negative_usage_rate": 0.5},
    }
    assert "runtime_directives" not in proposal.structured_patch_payload
    assert "tool_plan" not in proposal.structured_patch_payload
    assert described["rollout_eligible"] is False
    assert described["activation_surface"] is None
    assert [event.event_type for event in audit_repository.events] == [
        "reflection.proposal.created",
        "reflection.proposal.manual_review_required",
    ]

    reused = await proposal_service.create_skill_patch_request_from_recommendation(
        recommendation_id="recommendation-1",
        artifact_id="artifact-1",
        skill_name="create_quiz",
        skill_version="0.1.0",
        scope="quiz",
        surface="quiz",
        recommendation_reason_code="quality_regression",
        evidence_snapshot={
            "usage_event_ids": ["usage-1", "usage-2"],
            "negative_usage_event_ids": ["usage-2", "usage-3"],
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
        },
        metrics_snapshot={"negative_usage_rate": 0.5},
        related_artifact_ids=["artifact-related"],
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        operator_id="operator",
    )

    assert reused.id == proposal.id
    assert sum(1 for item in proposal_repository.items.values() if item.proposal_type == "skill_patch_request") == 1
    assert audit_repository.events[-1].event_type == "reflection.proposal.deduplicated"


async def test_proposal_service_extracts_usage_event_ids_from_coverage_regression_evidence():
    proposal_service = ReflectionProposalService(
        repository=StubProposalRepository(),
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        autonomy_job_service=None,
        audit_service=AuditService(repository=StubAuditRepository()),
    )

    proposal = await proposal_service.create_skill_patch_request_from_recommendation(
        recommendation_id="recommendation-coverage-1",
        artifact_id="artifact-1",
        skill_name="create_quiz",
        skill_version="0.1.0",
        scope="quiz",
        surface="quiz",
        recommendation_reason_code="coverage_regression",
        evidence_snapshot={
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
            "coverage_regression": {
                "attributed_usage_event_ids_by_topic": {"geometry": ["usage-1", "usage-2"]},
                "binding_gap_event_ids_by_topic": {"geometry": ["usage-2", "usage-3"]},
                "unresolved_usage_event_ids_by_topic": {"geometry": ["usage-4"]},
            },
        },
        metrics_snapshot={"coverage_drift_topic_count": 1},
        related_artifact_ids=[],
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        operator_id="operator",
    )

    assert proposal.structured_patch_payload["usage_event_ids"] == [
        "usage-1",
        "usage-2",
        "usage-3",
        "usage-4",
    ]
    assert proposal.structured_patch_payload["recommendation_reason_code"] == "coverage_regression"


async def test_proposal_service_creates_skill_merge_package_from_recommendation():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    source_artifact = _realizable_source_artifact()
    related_artifact = _related_merge_artifact(source=source_artifact)
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        artifact_repository=StubSkillArtifactRepository(items=[source_artifact, related_artifact]),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    proposal = await proposal_service.create_skill_merge_package_from_recommendation(
        recommendation_id="recommendation-merge-1",
        artifact_id=source_artifact.id,
        skill_name=source_artifact.name,
        skill_version=source_artifact.version,
        scope=source_artifact.scope,
        surface=source_artifact.scope,
        recommendation_reason_code="merge_candidate",
        evidence_snapshot={"learner_goal_id": "goal-1", "reflection_record_id": "reflection-merge-1"},
        metrics_snapshot={"overlap_score": 0.8},
        related_artifact_ids=[related_artifact.id, related_artifact.id, source_artifact.id],
        reflection_record_id="reflection-merge-1",
        learner_goal_id="goal-1",
        operator_id="operator",
    )
    described = await proposal_service.describe(proposal)

    assert proposal.proposal_type == "skill_package"
    assert proposal.status == "proposed"
    assert proposal.target_scope == source_artifact.scope
    assert proposal.priority_score == pytest.approx(0.85)
    assert proposal.structured_patch_payload == {
        "artifact_kind": "declarative_skill_package",
        "skill_name": source_artifact.name,
        "surface": source_artifact.scope,
        "match_rules": {
            "task_types": ["practice", "review"],
            "topic_keys": ["matrices", "linear-systems"],
        },
        "runtime_directives": source_artifact.runtime_directives,
        "tool_plan": source_artifact.tool_plan,
        "scoring_contract": source_artifact.definition["scoring_contract"],
    }
    assert proposal.evidence_snapshot["source"] == "skill_curator_merge_recommendation"
    assert proposal.evidence_snapshot["recommendation_id"] == "recommendation-merge-1"
    assert proposal.evidence_snapshot["source_artifact_id"] == source_artifact.id
    assert proposal.evidence_snapshot["source_artifact_lineage_id"] == source_artifact.lineage_id
    assert proposal.evidence_snapshot["merge_source_artifact_ids"] == [related_artifact.id]
    assert described["rollout_eligible"] is True
    assert described["activation_surface"] == "quiz"
    assert [event.event_type for event in audit_repository.events] == [
        "reflection.proposal.created",
        "reflection.proposal.skill_merge_created",
        "reflection.proposal.manual_review_required",
    ]

    reused = await proposal_service.create_skill_merge_package_from_recommendation(
        recommendation_id="recommendation-merge-1",
        artifact_id=source_artifact.id,
        skill_name=source_artifact.name,
        skill_version=source_artifact.version,
        scope=source_artifact.scope,
        surface=source_artifact.scope,
        recommendation_reason_code="merge_candidate",
        evidence_snapshot={"learner_goal_id": "goal-1", "reflection_record_id": "reflection-merge-1"},
        metrics_snapshot={"overlap_score": 0.8},
        related_artifact_ids=[related_artifact.id],
        reflection_record_id="reflection-merge-1",
        learner_goal_id="goal-1",
        operator_id="operator",
    )

    assert reused.id == proposal.id
    assert sum(1 for item in proposal_repository.items.values() if item.proposal_type == "skill_package") == 1
    assert audit_repository.events[-1].event_type == "reflection.proposal.deduplicated"


async def test_proposal_service_accepts_skill_merge_artifacts_with_same_implementation_binding():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    source_artifact = _realizable_source_artifact()
    related_artifact = _related_merge_artifact(
        source=source_artifact,
        name="quiz_practice_variant",
        implementation_binding="create_quiz",
    )
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        artifact_repository=StubSkillArtifactRepository(items=[source_artifact, related_artifact]),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    proposal = await proposal_service.create_skill_merge_package_from_recommendation(
        recommendation_id="recommendation-merge-2",
        artifact_id=source_artifact.id,
        skill_name=source_artifact.name,
        skill_version=source_artifact.version,
        scope=source_artifact.scope,
        surface=source_artifact.scope,
        recommendation_reason_code="merge_candidate",
        evidence_snapshot={"learner_goal_id": "goal-1", "reflection_record_id": "reflection-merge-2"},
        metrics_snapshot={"overlap_score": 0.8},
        related_artifact_ids=[related_artifact.id],
        reflection_record_id="reflection-merge-2",
        learner_goal_id="goal-1",
        operator_id="operator",
    )

    assert proposal.proposal_type == "skill_package"
    assert proposal.structured_patch_payload["skill_name"] == source_artifact.name
    assert proposal.structured_patch_payload["match_rules"] == {
        "task_types": ["practice", "review"],
        "topic_keys": ["matrices", "linear-systems"],
    }
    assert proposal.evidence_snapshot["merge_source_artifact_ids"] == [related_artifact.id]


@pytest.mark.parametrize(
    ("related_artifact", "error"),
    [
        (None, "related_artifact_ids"),
        ("suppressed", "governed candidate"),
        ("archived", "governed candidate"),
        ("rejected", "governed candidate"),
        ("wrong-name", "match source skill/scope or implementation binding"),
    ],
)
async def test_proposal_service_rejects_invalid_skill_merge_artifacts(related_artifact, error: str):
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    source_artifact = _realizable_source_artifact()
    if related_artifact in {"suppressed", "archived", "rejected"}:
        related = _related_merge_artifact(source=source_artifact, status=related_artifact)
    elif related_artifact == "wrong-name":
        related = _related_merge_artifact(source=source_artifact, name="adaptive_hint")
    else:
        related = None
    artifacts = [source_artifact] + ([related] if related is not None else [])
    proposal_service = ReflectionProposalService(
        repository=StubProposalRepository(),
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=StubProposalEvaluationRepository(),
        artifact_repository=StubSkillArtifactRepository(items=artifacts),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    with pytest.raises(ValidationError, match=error):
        await proposal_service.create_skill_merge_package_from_recommendation(
            recommendation_id="recommendation-merge-1",
            artifact_id=source_artifact.id,
            skill_name=source_artifact.name,
            skill_version=source_artifact.version,
            scope=source_artifact.scope,
            surface=source_artifact.scope,
            recommendation_reason_code="merge_candidate",
            evidence_snapshot={"learner_goal_id": "goal-1", "reflection_record_id": "reflection-merge-1"},
            metrics_snapshot={"overlap_score": 0.8},
            related_artifact_ids=[related.id] if related is not None else [],
            reflection_record_id="reflection-merge-1",
            learner_goal_id="goal-1",
            operator_id="operator",
        )

    assert audit_repository.events == []


async def test_proposal_service_realizes_approved_skill_patch_request_as_replacement_skill_package():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    artifact = _realizable_source_artifact()
    patch_request = _skill_patch_request_proposal(artifact=artifact)
    evaluation = _effective_patch_request_evaluation(patch_request)
    await proposal_repository.create(patch_request)
    await evaluation_repository.create(evaluation)
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=evaluation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    realized = await proposal_service.realize_skill_patch_request(
        proposal_id=patch_request.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Create replacement proposal.",
    )
    described = await proposal_service.describe(realized)

    assert realized.proposal_type == "skill_package"
    assert realized.status == "proposed"
    assert realized.target_scope == artifact.scope
    assert realized.structured_patch_payload == {
        "artifact_kind": "declarative_skill_package",
        "skill_name": artifact.name,
        "surface": artifact.scope,
        "match_rules": artifact.definition["match_rules"],
        "runtime_directives": artifact.runtime_directives,
        "tool_plan": artifact.tool_plan,
        "scoring_contract": artifact.definition["scoring_contract"],
    }
    assert realized.evidence_snapshot["source"] == "skill_patch_request_realization"
    assert realized.evidence_snapshot["source_skill_patch_request_id"] == patch_request.id
    assert realized.evidence_snapshot["source_artifact_id"] == artifact.id
    assert realized.evidence_snapshot["source_artifact_lineage_id"] == artifact.lineage_id
    assert realized.evidence_snapshot["recommendation_id"] == "recommendation-1"
    assert realized.evidence_snapshot["usage_event_ids"] == ["usage-1", "usage-2"]
    assert realized.evidence_snapshot["patch_request_evaluation"]["id"] == evaluation.id
    assert described["rollout_eligible"] is True
    assert described["activation_surface"] == "quiz"
    assert artifact.status == "stable"
    assert [event.event_type for event in audit_repository.events] == [
        "reflection.proposal.created",
        "reflection.proposal.skill_patch_realized",
        "reflection.proposal.manual_review_required",
    ]


async def test_proposal_service_reuses_realized_skill_patch_request():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    artifact = _realizable_source_artifact()
    patch_request = _skill_patch_request_proposal(artifact=artifact)
    await proposal_repository.create(patch_request)
    await evaluation_repository.create(_effective_patch_request_evaluation(patch_request))
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=evaluation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        autonomy_job_service=None,
        audit_service=audit_service,
    )

    first = await proposal_service.realize_skill_patch_request(
        proposal_id=patch_request.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note=None,
    )
    reused = await proposal_service.realize_skill_patch_request(
        proposal_id=patch_request.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Repeat.",
    )

    assert reused.id == first.id
    assert sum(1 for item in proposal_repository.items.values() if item.proposal_type == "skill_package") == 1
    assert audit_repository.events[-1].event_type == "reflection.proposal.skill_patch_realize_reused"


async def test_proposal_service_rejects_skill_patch_realization_without_required_gates():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    artifact = _realizable_source_artifact()
    unapproved = _skill_patch_request_proposal(artifact=artifact, status="sandbox_completed")
    missing_evaluation = _skill_patch_request_proposal(artifact=artifact)
    inconclusive = _skill_patch_request_proposal(artifact=artifact, evaluation_status="inconclusive")
    for patch_request, evaluation, error in [
        (
            unapproved,
            _effective_patch_request_evaluation(unapproved),
            "Only approved",
        ),
        (
            missing_evaluation,
            None,
            "effective evaluation",
        ),
        (
            inconclusive,
            ReflectionProposalEvaluation.build(
                proposal_id=inconclusive.id,
                comparison_window_size=1,
                baseline_policy_snapshot={},
                candidate_policy_snapshot={},
                evaluator_type="rule",
            ).with_result(
                evaluation_status="inconclusive",
                simulated_outcome_summary={},
                score_delta=0.0,
            ),
            "effective patch request",
        ),
    ]:
        proposal_repository = StubProposalRepository()
        evaluation_repository = StubProposalEvaluationRepository()
        await proposal_repository.create(patch_request)
        if evaluation is not None:
            await evaluation_repository.create(evaluation)
        proposal_service = ReflectionProposalService(
            repository=proposal_repository,
            approval_decision_repository=StubProposalApprovalDecisionRepository(),
            evaluation_repository=evaluation_repository,
            artifact_repository=StubSkillArtifactRepository(artifact),
            autonomy_job_service=None,
            audit_service=audit_service,
        )

        with pytest.raises(ValidationError, match=error):
            await proposal_service.realize_skill_patch_request(
                proposal_id=patch_request.id,
                operator_id="operator",
                reason_code="operator_reviewed",
                reason_note=None,
            )


async def test_skill_candidate_from_realized_patch_proposal_inherits_replacement_lineage():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(repository=audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    source_artifact = _realizable_source_artifact()
    patch_request = _skill_patch_request_proposal(artifact=source_artifact)
    await proposal_repository.create(patch_request)
    await evaluation_repository.create(_effective_patch_request_evaluation(patch_request))
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=StubProposalApprovalDecisionRepository(),
        evaluation_repository=evaluation_repository,
        artifact_repository=StubSkillArtifactRepository(source_artifact),
        autonomy_job_service=None,
        audit_service=audit_service,
    )
    realized = await proposal_service.realize_skill_patch_request(
        proposal_id=patch_request.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note=None,
    )
    approved_realized = realized.enqueue_sandbox(
        sandbox_run_id="sandbox-realized-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-realized-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-realized-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    await proposal_repository.update(approved_realized)
    await evaluation_repository.create(
        ReflectionProposalEvaluation.build(
            proposal_id=approved_realized.id,
            comparison_window_size=2,
            baseline_policy_snapshot={},
            candidate_policy_snapshot=approved_realized.structured_patch_payload,
            evaluator_type="rule",
            sandbox_run_id="sandbox-realized-1",
        ).with_result(
            evaluation_status="effective",
            simulated_outcome_summary={"score_delta": 0.2},
            score_delta=0.2,
            sandbox_run_id="sandbox-realized-1",
        )
    )
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    candidate_service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=proposal_repository,
        evaluation_repository=evaluation_repository,
        audit_service=audit_service,
    )

    candidate = await candidate_service.create_candidate_from_proposal(
        proposal_id=approved_realized.id,
        operator_id="operator",
    )

    assert candidate.status == "candidate"
    assert candidate.lineage_id == source_artifact.lineage_id
    assert candidate.parent_artifact_id == source_artifact.id
    assert candidate.supersedes_artifact_id == source_artifact.id
    assert source_artifact.status == "stable"


async def test_sandbox_service_executes_skill_patch_request_without_artifact_side_effects():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    sandbox_run_repository = StubProposalSandboxRunRepository()
    approval_repository = StubProposalApprovalDecisionRepository()
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=approval_repository,
        audit_service=audit_service,
    )
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="skill_patch_request",
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Curator evidence indicates create_quiz needs a patch.",
        change_summary="Create governed patch request.",
        structured_patch_payload={
            "artifact_id": "artifact-1",
            "skill_name": "create_quiz",
            "skill_version": "0.1.0",
            "scope": "quiz",
            "surface": "quiz",
            "recommendation_id": "recommendation-1",
            "recommendation_reason_code": "quality_regression",
            "usage_event_ids": ["usage-1", "usage-2"],
            "related_artifact_ids": [],
            "evidence_snapshot": {"usage_event_ids": ["usage-1", "usage-2"]},
            "metrics_snapshot": {"negative_usage_rate": 0.5},
        },
        expected_improvement="Route patch evidence through governed review.",
        risk_level="medium",
        evidence_snapshot={},
    )
    await proposal_repository.create(proposal)
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
    assert result.sample_source_type == "mixed"
    assert result.sample_count == 2
    assert result.baseline_snapshot == {
        "surface": "quiz",
        "artifact_id": "artifact-1",
        "skill_name": "create_quiz",
        "skill_version": "0.1.0",
        "strategy_summary": None,
    }
    assert result.candidate_snapshot["usage_event_ids"] == ["usage-1", "usage-2"]
    stored_proposal = await proposal_service.get(proposal.id)
    assert stored_proposal.status == "sandbox_completed"
    assert stored_proposal.latest_sandbox_run_id == result.id
    evaluation = await evaluation_repository.get_by_proposal(proposal.id)
    assert evaluation is not None
    assert evaluation.evaluation_status == "effective"
    assert evaluation.score_delta == 0.15000000000000002


async def test_skill_patch_request_cannot_rollout_or_create_skill_candidate():
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
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id=goal.id,
        proposal_type="skill_patch_request",
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Curator evidence indicates create_quiz needs a patch.",
        change_summary="Create governed patch request.",
        structured_patch_payload={
            "artifact_id": "artifact-1",
            "skill_name": "create_quiz",
            "skill_version": "0.1.0",
            "scope": "quiz",
            "surface": "quiz",
            "recommendation_id": "recommendation-1",
            "recommendation_reason_code": "quality_regression",
            "usage_event_ids": ["usage-1", "usage-2"],
            "related_artifact_ids": [],
            "evidence_snapshot": {"usage_event_ids": ["usage-1", "usage-2"]},
            "metrics_snapshot": {"negative_usage_rate": 0.5},
        },
        expected_improvement="Route patch evidence through governed review.",
        risk_level="medium",
        evidence_snapshot={},
    ).enqueue_sandbox(
        sandbox_run_id="sandbox-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.15",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    await proposal_repository.create(proposal)
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=StubProposalRolloutRepository(),
    )

    with pytest.raises(ValidationError, match="not rollout-enabled"):
        await rollout_service.activate(
            proposal_id=proposal.id,
            operator_id="operator",
            reason_code="activate",
            reason_note=None,
        )

    candidate_service = SkillCandidateService(
        artifact_repository=StubSkillArtifactRepository(),
        proposal_repository=proposal_repository,
        evaluation_repository=StubProposalEvaluationRepository(),
        audit_service=audit_service,
    )
    with pytest.raises(ValidationError, match="Only skill_package proposals"):
        await candidate_service.create_candidate_from_proposal(
            proposal_id=proposal.id,
            operator_id="operator",
        )


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


async def test_sandbox_service_records_tool_plan_contract_and_preview_summary() -> None:
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    sandbox_run_repository = StubProposalSandboxRunRepository()
    approval_repository = StubProposalApprovalDecisionRepository()
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="skill_package",
        target_scope="replan",
        priority_score=0.8,
        hypothesis="Need governed multi-step repair and follow-up review.",
        change_summary="Use partial replan followed by review scheduling.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "plan_study_path",
            "bundle_id": "bundle-replan-1",
            "surface": "replan",
            "match_rules": {"topic_keys": ["algebra"]},
            "runtime_directives": {"replan_bias": "normal"},
            "tool_plan": [
                {"step_id": "repair", "tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
                {
                    "step_id": "followup_review",
                    "tool_name": "review_scheduling",
                    "payload_template": {"source_task_id": "$steps.repair.created_task_ids[0]"},
                },
            ],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        expected_improvement="Improve recovery consistency.",
        risk_level="medium",
        evidence_snapshot={"task": {"source_task_id": "task-1", "topic_focus": "algebra"}},
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
        internal_tool_registry=None,
        tool_plan_runtime_executor=ToolPlanRuntimeExecutor(
            internal_tool_registry=None,
            audit_service=audit_service,
        ),
    )

    result = await sandbox_service.execute(proposal_id=proposal.id)

    contract_summary = result.result_summary["tool_plan_contract_summary"]
    preview_summary = result.result_summary["tool_plan_preview_summary"]
    assert contract_summary["expected_sequence"] == ["partial_replan", "review_scheduling"]
    assert contract_summary["expected_step_count"] == 2
    assert preview_summary["preview_matches_contract"] is True
    assert preview_summary["reason_codes"] == ["tool_plan_sequence_verified"]
    evaluation = await evaluation_repository.get_by_proposal(proposal.id)
    assert evaluation is not None
    assert evaluation.simulated_outcome_summary["tool_plan_preview_summary"]["preview_matches_contract"] is True
    assert evaluation.evaluation_status == "effective"
    assert evaluation.score_delta >= 0.11


async def test_rollout_observation_rolls_back_on_tool_plan_sequence_mismatch() -> None:
    audit_repository = StubAuditRepository()
    goal = LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Matrices",
        target_outcome="Master matrix multiplication",
        weekly_study_minutes=180,
        deadline_date=date.today() + timedelta(days=60),
        baseline_note=None,
    )
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id=goal.id,
        proposal_type="skill_package",
        target_scope="replan",
        priority_score=0.8,
        hypothesis="Need governed multi-step repair and follow-up review.",
        change_summary="Use partial replan followed by review scheduling.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "plan_study_path",
            "bundle_id": "bundle-replan-1",
            "surface": "replan",
            "match_rules": {"topic_keys": ["algebra"]},
            "runtime_directives": {"replan_bias": "normal"},
            "tool_plan": [
                {"step_id": "repair", "tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
                {
                    "step_id": "followup_review",
                    "tool_name": "review_scheduling",
                    "payload_template": {"source_task_id": "$steps.repair.created_task_ids[0]"},
                },
            ],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        expected_improvement="Improve recovery consistency.",
        risk_level="medium",
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
    proposal_repository = StubProposalRepository()
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    binding_repository = StubGoalSkillBindingRepository()
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        binding_repository=binding_repository,
    )
    activated = await rollout_service.activate(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="activate",
        reason_note=None,
    )
    binding = await binding_repository.get_by_rollout(activated.id)
    assert binding is not None
    mismatch_event = SkillUsageEvent.build(
        skill_artifact_id=None,
        skill_name="plan_study_path",
        skill_version=None,
        skill_status_at_use=None,
        learner_goal_id=goal.id,
        surface="replan",
        outcome_status="completed",
        resolver_status="resolved",
        selection_reason="production_default",
        metadata={
            "tool_plan_sequence": ["partial_replan"],
            "tool_plan_step_count": 1,
            "skill_package_rollout": {
                "proposal_id": proposal.id,
                "rollout_id": activated.id,
                "binding_id": binding.id,
                "skill_name": "plan_study_path",
                "surface": "replan",
            },
        },
    )
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        binding_repository=binding_repository,
        usage_repository=StubSkillUsageEventRepository([mismatch_event]),
    )

    observation = await rollout_service.observe(rollout_id=activated.id, trigger_source="test")

    assert observation.recommendation == "rollback"
    assert "tool_plan_sequence_mismatch" in observation.reason_codes
    sequence_summary = observation.signal_summary["tool_plan_sequence"]
    assert sequence_summary["sequence_mismatch_count"] == 1
    assert sequence_summary["step_count_mismatch_count"] == 1


async def test_sandbox_service_rejects_skill_package_preview_with_missing_source_task_id():
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    proposal_repository = StubProposalRepository()
    evaluation_repository = StubProposalEvaluationRepository()
    sandbox_run_repository = StubProposalSandboxRunRepository()
    approval_repository = StubProposalApprovalDecisionRepository()
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="skill_package",
        target_scope="review_scheduling",
        priority_score=0.8,
        hypothesis="Need denser reviews after failures.",
        change_summary="Tighten review intervals.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "schedule_review",
            "bundle_id": "bundle-1",
            "surface": "review_scheduling",
            "match_rules": {"required_root_causes": ["review_gap"]},
            "runtime_directives": {"review_bias": "intensive"},
            "tool_plan": [{"tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}}],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
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
        internal_tool_registry=None,
        tool_plan_runtime_executor=ToolPlanRuntimeExecutor(
            internal_tool_registry=None,
            audit_service=audit_service,
        ),
    )

    with pytest.raises(ValidationError):
        await sandbox_service.execute(proposal_id=proposal.id)


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
        skill_artifact_repository=StubSkillArtifactRepository(),
        session_repository=StubSessionRepository([]),
        message_repository=StubSessionMessageRepository([]),
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_evidence_repository=StubReflectionEvidenceRepository(),
        task_attempt_repository=StubTaskAttemptRepository([]),
        usage_repository=StubSkillUsageEventRepository(),
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
            "skill_name": "create_quiz",
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
        skill_artifact_repository=StubSkillArtifactRepository(),
        session_repository=StubSessionRepository([]),
        message_repository=StubSessionMessageRepository([]),
        reflection_record_repository=StubReflectionRecordRepository(),
        reflection_evidence_repository=StubReflectionEvidenceRepository(),
        task_attempt_repository=StubTaskAttemptRepository([]),
        usage_repository=StubSkillUsageEventRepository(),
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


@pytest.mark.parametrize("artifact_status", ["active", "stable", "suppressed"])
async def test_skill_package_rollout_rollback_deprecates_selectable_artifact(artifact_status: str):
    audit_repository = StubAuditRepository()
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id)
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    binding_repository = StubGoalSkillBindingRepository()
    rollout = _rolled_out_rollout_for_proposal(proposal)
    binding = _rolled_out_binding_for_rollout(proposal=proposal, rollout=rollout)
    await rollout_repository.create(rollout)
    await binding_repository.create(binding)
    artifact = _skill_package_artifact_for_proposal(proposal, status=artifact_status)
    artifact_repository = StubSkillArtifactRepository(artifact)
    decision_repository = StubProposalRolloutDecisionRepository()
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        decision_repository=decision_repository,
        binding_repository=binding_repository,
        artifact_repository=artifact_repository,
    )

    rolled_back = await rollout_service.rollback(
        rollout_id=rollout.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note="Rollback source rollout.",
    )

    assert rolled_back.status == "rolled_back"
    updated_binding = await binding_repository.get_by_rollout(rollout.id)
    assert updated_binding is not None
    assert updated_binding.status == "rolled_back"
    deactivated_artifact = artifact_repository.items[artifact.id]
    assert deactivated_artifact.status == "deprecated"
    assert deactivated_artifact.deprecated_by == "operator"
    assert deactivated_artifact.deprecated_at is not None
    assert deactivated_artifact.suppressed_reason_code is None
    assert deactivated_artifact.suppressed_reason_note is None
    assert deactivated_artifact.suppressed_by is None
    assert deactivated_artifact.suppressed_at is None
    assert deactivated_artifact.suppressed_previous_status is None
    assert len(decision_repository.items) == 1
    assert decision_repository.items[0].decision_type == "rollback"
    deactivation_event = next(
        item for item in audit_repository.events
        if item.event_type == "skill.artifact.deactivated"
    )
    assert deactivation_event.event_data["artifact_id"] == artifact.id
    assert deactivation_event.event_data["source_proposal_id"] == proposal.id
    assert deactivation_event.event_data["rollout_id"] == rollout.id
    assert deactivation_event.event_data["previous_status"] == artifact_status
    assert deactivation_event.event_data["reason_code"] == "rollout_rollback"
    rollback_event = next(
        item for item in audit_repository.events
        if item.event_type == "reflection.proposal.rollout.rolled_back"
    )
    assert rollback_event.event_data["deactivated_skill_artifact_id"] == artifact.id
    assert rollback_event.event_data["deactivated_skill_artifact_previous_status"] == artifact_status
    assert rollback_event.event_data["deactivated_skill_artifact_status"] == "deprecated"


async def test_skill_package_rollout_rollback_leaves_staged_artifact_unchanged():
    audit_repository = StubAuditRepository()
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id)
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    binding_repository = StubGoalSkillBindingRepository()
    rollout = _rolled_out_rollout_for_proposal(proposal)
    binding = _rolled_out_binding_for_rollout(proposal=proposal, rollout=rollout)
    await rollout_repository.create(rollout)
    await binding_repository.create(binding)
    artifact = _skill_package_artifact_for_proposal(proposal, status="staged")
    artifact_repository = StubSkillArtifactRepository(artifact)
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        binding_repository=binding_repository,
        artifact_repository=artifact_repository,
    )

    rolled_back = await rollout_service.rollback(
        rollout_id=rollout.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note=None,
    )

    assert rolled_back.status == "rolled_back"
    unchanged_artifact = artifact_repository.items[artifact.id]
    assert unchanged_artifact.status == "staged"
    assert unchanged_artifact.deprecated_by is None
    assert unchanged_artifact.deprecated_at is None
    assert not any(item.event_type == "skill.artifact.deactivated" for item in audit_repository.events)
    rollback_event = next(
        item for item in audit_repository.events
        if item.event_type == "reflection.proposal.rollout.rolled_back"
    )
    assert rollback_event.event_data["deactivated_skill_artifact_id"] is None
    assert rollback_event.event_data["deactivated_skill_artifact_previous_status"] is None
    assert rollback_event.event_data["deactivated_skill_artifact_status"] is None


async def test_non_skill_package_rollout_rollback_does_not_deprecate_artifact():
    audit_repository = StubAuditRepository()
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
    proposal = _approved_rollout_proposal(
        learner_goal_id=goal.id,
        proposal_type="workflow_optimization",
        target_scope="quiz",
    )
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    rollout = _rolled_out_rollout_for_proposal(proposal)
    await rollout_repository.create(rollout)
    artifact = _skill_package_artifact_for_proposal(proposal, status="active")
    artifact_repository = StubSkillArtifactRepository(artifact)
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        artifact_repository=artifact_repository,
    )

    rolled_back = await rollout_service.rollback(
        rollout_id=rollout.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note=None,
    )

    assert rolled_back.status == "rolled_back"
    unchanged_artifact = artifact_repository.items[artifact.id]
    assert unchanged_artifact.status == "active"
    assert unchanged_artifact.deprecated_by is None
    assert unchanged_artifact.deprecated_at is None
    assert not any(item.event_type == "skill.artifact.deactivated" for item in audit_repository.events)


async def test_rollout_rollback_is_idempotent_after_artifact_deactivation():
    audit_repository = StubAuditRepository()
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id)
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    binding_repository = StubGoalSkillBindingRepository()
    rollout = _rolled_out_rollout_for_proposal(proposal)
    binding = _rolled_out_binding_for_rollout(proposal=proposal, rollout=rollout)
    await rollout_repository.create(rollout)
    await binding_repository.create(binding)
    artifact = _skill_package_artifact_for_proposal(proposal, status="active")
    artifact_repository = StubSkillArtifactRepository(artifact)
    decision_repository = StubProposalRolloutDecisionRepository()
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        decision_repository=decision_repository,
        binding_repository=binding_repository,
        artifact_repository=artifact_repository,
    )

    first = await rollout_service.rollback(
        rollout_id=rollout.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note="First rollback.",
    )
    second = await rollout_service.rollback(
        rollout_id=rollout.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note="Repeat rollback.",
    )

    assert first.id == second.id
    assert second.status == "rolled_back"
    assert artifact_repository.items[artifact.id].status == "deprecated"
    assert len(decision_repository.items) == 1
    assert sum(1 for item in audit_repository.events if item.event_type == "skill.artifact.deactivated") == 1
    reused_event = next(
        item for item in audit_repository.events
        if item.event_type == "reflection.proposal.rollout.rollback_reused"
    )
    assert reused_event.event_data["proposal_id"] == proposal.id
    assert reused_event.event_data["rollout_id"] == rollout.id
    assert reused_event.event_data["reason_note"] == "Repeat rollback."


@pytest.mark.asyncio
async def test_rollout_observation_schedules_auto_decision_job() -> None:
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id, target_scope="review_scheduling")
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    autonomy_jobs = StubScheduledAutonomyJobRepository()
    scheduler = ReflectionProposalRolloutObservationScheduler(
        rollout_repository=rollout_repository,
        autonomy_job_service=AutonomyJobService(repository=autonomy_jobs, audit_service=audit_service),
        audit_service=audit_service,
        decision_scheduler=ReflectionProposalRolloutDecisionScheduler(
            rollout_repository=rollout_repository,
            autonomy_job_service=AutonomyJobService(repository=autonomy_jobs, audit_service=audit_service),
            audit_service=audit_service,
        ),
    )
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        observation_scheduler=scheduler,
    )
    rollout = ReflectionProposalRollout.build(
        proposal_id=proposal.id,
        learner_goal_id=goal.id,
        surface="review_scheduling",
        baseline_snapshot={},
        runtime_overlay_payload={},
        activated_by="operator",
    )
    await rollout_repository.create(rollout)

    await rollout_service.observe(
        rollout_id=rollout.id,
        trigger_source="worker_tick",
    )

    assert any(job.job_type == "reflection_proposal_rollout_decision" for job in autonomy_jobs.jobs.values())
    queued = next(
        item for item in audit_repository.events
        if item.event_type == "reflection.proposal.rollout.auto_decision.queued"
    )
    assert queued.event_data["rollout_id"] == rollout.id


@pytest.mark.asyncio
async def test_rollout_auto_governance_promotes_staged_rollout() -> None:
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id, target_scope="review_scheduling")
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    decision_repository = StubProposalRolloutDecisionRepository()
    binding_repository = StubGoalSkillBindingRepository()
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        decision_repository=decision_repository,
        binding_repository=binding_repository,
    )
    rollout = ReflectionProposalRollout.build(
        proposal_id=proposal.id,
        learner_goal_id=goal.id,
        surface="review_scheduling",
        baseline_snapshot={},
        runtime_overlay_payload={},
        activated_by="operator",
    )
    binding = GoalSkillBinding.build(
        proposal_id=proposal.id,
        rollout_id=rollout.id,
        learner_goal_id=goal.id,
        surface="review_scheduling",
        priority_score=proposal.priority_score,
        match_rules={},
        runtime_directives={},
        tool_plan=[],
    )
    await rollout_repository.create(rollout)
    await binding_repository.create(binding)
    observation = ReflectionProposalRolloutObservation.build(
        rollout_id=rollout.id,
        proposal_id=proposal.id,
        learner_goal_id=goal.id,
        surface="review_scheduling",
        recommendation="promote",
        observed_sample_count=2,
        positive_score=0.8,
        negative_score=0.0,
        signal_summary={},
        reason_codes=["review_completed"],
    )
    await observation_repository.create(observation)
    await rollout_repository.update(rollout.with_status(rollout.status, latest_observation_id=observation.id))
    orchestrator = ReflectionProposalRolloutDecisionOrchestrator(
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        rollout_service=rollout_service,
        audit_service=audit_service,
    )

    result = await orchestrator.evaluate_and_execute(
        rollout_id=rollout.id,
        source_ref=observation.id,
    )

    assert result is not None
    assert result.status == "rolled_out"
    assert decision_repository.items[-1].decision_type == "promote"
    assert decision_repository.items[-1].operator_id == "system:auto_rollout_governor"


@pytest.mark.asyncio
async def test_rollout_auto_governance_rolls_back_staged_rollout() -> None:
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
    proposal = _approved_rollout_proposal(learner_goal_id=goal.id, target_scope="assessment_generation")
    await proposal_repository.create(proposal)
    rollout_repository = StubProposalRolloutRepository()
    observation_repository = StubProposalRolloutObservationRepository()
    decision_repository = StubProposalRolloutDecisionRepository()
    rollout_service = _rollout_service_for_tests(
        audit_repository=audit_repository,
        goal=goal,
        proposal_repository=proposal_repository,
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        decision_repository=decision_repository,
    )
    rollout = ReflectionProposalRollout.build(
        proposal_id=proposal.id,
        learner_goal_id=goal.id,
        surface="assessment_generation",
        baseline_snapshot={},
        runtime_overlay_payload={},
        activated_by="operator",
    )
    await rollout_repository.create(rollout)
    observation = ReflectionProposalRolloutObservation.build(
        rollout_id=rollout.id,
        proposal_id=proposal.id,
        learner_goal_id=goal.id,
        surface="assessment_generation",
        recommendation="rollback",
        observed_sample_count=1,
        positive_score=0.0,
        negative_score=1.0,
        signal_summary={},
        reason_codes=["assessment_regressed"],
    )
    await observation_repository.create(observation)
    await rollout_repository.update(rollout.with_status(rollout.status, latest_observation_id=observation.id))
    orchestrator = ReflectionProposalRolloutDecisionOrchestrator(
        rollout_repository=rollout_repository,
        observation_repository=observation_repository,
        rollout_service=rollout_service,
        audit_service=audit_service,
    )

    result = await orchestrator.evaluate_and_execute(
        rollout_id=rollout.id,
        source_ref=observation.id,
    )

    assert result is not None
    assert result.status == "rolled_back"
    assert decision_repository.items[-1].decision_type == "rollback"
    assert decision_repository.items[-1].operator_id == "system:auto_rollout_governor"
