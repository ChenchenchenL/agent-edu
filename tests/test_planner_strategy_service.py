from datetime import date, timedelta

from agent_core.application.services.audit import AuditService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.reflection_v2 import LearnerGoalStrategyCard


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubStrategyCardRepository:
    def __init__(self, card: LearnerGoalStrategyCard | None):
        self.card = card

    async def get_active_by_goal(self, learner_goal_id: str):
        if self.card is not None and self.card.learner_goal_id == learner_goal_id and self.card.status == "active":
            return self.card
        return None

    async def create(self, entity):
        self.card = entity

    async def list_by_goal(self, learner_goal_id: str):
        return [self.card] if self.card is not None and self.card.learner_goal_id == learner_goal_id else []

    async def update(self, entity):
        self.card = entity


class StubRolloutResolver:
    def __init__(self, overlay: dict[str, object] | None):
        self.overlay = overlay

    async def get_active_overlay(self, *, learner_goal_id: str, surface: str, include_staged: bool = False):
        if self.overlay is None:
            return None
        return type(
            "Overlay",
            (),
            {
                "rollout_id": "rollout-1",
                "proposal_id": "proposal-1",
                "learner_goal_id": learner_goal_id,
                "surface": surface,
                "status": "rolled_out",
                "payload": self.overlay,
                "baseline_snapshot": {},
            },
        )()


class CapturingPlannerProvider:
    provider_name = "stub"
    model_name = "stub-planner"

    def __init__(self):
        self.last_strategy_summary = None
        self.last_stage_blueprint = None
        self.last_task_blueprint = None

    async def generate_study_plan_draft(
        self,
        *,
        subject: str,
        target_outcome: str,
        baseline_note: str | None,
        weekly_study_minutes: int,
        stage_blueprint: list[dict[str, object]],
        task_blueprint: list[dict[str, object]],
        strategy_summary: dict[str, object] | None = None,
        skill_directives: list[str] | None = None,
    ):
        from agent_core.infrastructure.llm.mock_provider import MockLLMProvider

        self.last_strategy_summary = strategy_summary
        self.last_stage_blueprint = stage_blueprint
        self.last_task_blueprint = task_blueprint
        return await MockLLMProvider("mock-tutor-v1").generate_study_plan_draft(
            subject=subject,
            target_outcome=target_outcome,
            baseline_note=baseline_note,
            weekly_study_minutes=weekly_study_minutes,
            stage_blueprint=stage_blueprint,
            task_blueprint=task_blueprint,
            strategy_summary=strategy_summary,
            skill_directives=skill_directives,
        )


async def test_planner_uses_strategy_card_for_blueprint_and_llm_context():
    goal = LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    card = LearnerGoalStrategyCard.build(
        learner_goal_id=goal.id,
        version=1,
        source_reflection_ids=["r1"],
        primary_instruction_mode="guided",
        difficulty_bias="supportive",
        review_bias="intensive",
        replan_bias="aggressive",
        assessment_bias="early",
        intervention_policy={"source": "test"},
        rationale="Derived from recent reflections.",
        confidence_score=0.8,
    )
    provider = CapturingPlannerProvider()
    planner = PlannerService(
        llm_provider=provider,
        audit_service=AuditService(StubAuditRepository()),
        strategy_card_service=StrategyCardService(
            repository=StubStrategyCardRepository(card),
            audit_service=AuditService(StubAuditRepository()),
        ),
    )

    materialized = await planner.build_plan(
        goal=goal,
        version=1,
        trigger_source="initial",
        supersedes_plan_id=None,
    )

    assert provider.last_strategy_summary is not None
    assert provider.last_strategy_summary["primary_instruction_mode"] == "guided"
    assert provider.last_strategy_summary["difficulty_bias"] == "supportive"
    assert provider.last_stage_blueprint is not None
    assert provider.last_stage_blueprint[0]["title"] == "Foundation"
    assert provider.last_task_blueprint is not None
    assert any(item["task_type"] == "lesson" for item in provider.last_task_blueprint)
    assert any(item["difficulty"] == "easy" for item in provider.last_task_blueprint if item["task_type"] == "practice")
    assert materialized.study_plan.blueprint_payload["strategy_summary"]["primary_instruction_mode"] == "guided"


async def test_planner_rollout_overlay_merges_into_strategy_summary():
    goal = LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )
    provider = CapturingPlannerProvider()
    planner = PlannerService(
        llm_provider=provider,
        audit_service=AuditService(StubAuditRepository()),
        strategy_card_service=StrategyCardService(
            repository=StubStrategyCardRepository(None),
            audit_service=AuditService(StubAuditRepository()),
        ),
        rollout_resolver=StubRolloutResolver(
            {
                "review_bias": "intensive",
                "assessment_bias": "early",
                "replan_bias": "aggressive",
            }
        ),
    )

    materialized = await planner.build_plan(
        goal=goal,
        version=1,
        trigger_source="initial",
        supersedes_plan_id=None,
    )

    assert provider.last_strategy_summary is not None
    assert provider.last_strategy_summary["review_bias"] == "intensive"
    assert materialized.study_plan.blueprint_payload["rollout_context"]["rollout_id"] == "rollout-1"
