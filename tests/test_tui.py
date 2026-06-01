from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent_core.cli.config import CliConfig
from agent_core.cli.tui import AgentEduTui
from agent_core.domain.schemas.autonomy import GoalAutonomyStateResponse
from agent_core.domain.schemas.goal import LearnerGoalResponse, LearnerProfileResponse
from agent_core.domain.schemas.memory import (
    BehaviorMemoryBrowseItemResponse,
    KnowledgeMemoryBrowseItemResponse,
)
from agent_core.domain.schemas.planning import DailyTaskResponse, StudyPlanResponse, WorkflowRunResponse
from agent_core.domain.schemas.session import MessageHistoryResponse, MessageHistoryItemResponse, MessageRequest, MessageResponse
from agent_core.domain.schemas.workspace import WorkspaceMemorySummaryResponse, WorkspaceSummaryResponse


class _FakeClient:
    async def close(self) -> None:
        return None

    async def doctor(self, *, active_profile_id: str | None, active_goal_id: str | None):
        raise NotImplementedError

    async def list_profiles(self) -> list[LearnerProfileResponse]:
        now = datetime.now(timezone.utc)
        return [LearnerProfileResponse(id="profile-1", created_at=now, updated_at=now)]

    async def list_goals(self, profile_id: str) -> list[LearnerGoalResponse]:
        raise NotImplementedError

    async def get_workspace(self, profile_id: str, goal_id: str | None = None) -> WorkspaceSummaryResponse:
        now = datetime.now(timezone.utc)
        return WorkspaceSummaryResponse(
            learner_profile=LearnerProfileResponse(id="profile-1", created_at=now, updated_at=now),
            learner_goal=LearnerGoalResponse(
                id="goal-1",
                learner_profile_id="profile-1",
                title="Linear Algebra",
                subject="Matrices",
                target_outcome="Understand matrices",
                baseline_note=None,
                deadline_date=now.date(),
                weekly_study_minutes=180,
                status="active",
                created_at=now,
                updated_at=now,
            ),
            active_plan=StudyPlanResponse(
                id="plan-1",
                learner_goal_id="goal-1",
                version=1,
                status="active",
                trigger_source="initial",
                plan_summary="Study matrices",
                blueprint_payload={},
                materialized_until_date=now.date(),
                supersedes_plan_id=None,
                created_at=now,
                updated_at=now,
                stages=[],
            ),
            today_tasks=[
                DailyTaskResponse(
                    id="task-1",
                    learner_goal_id="goal-1",
                    study_plan_id="plan-1",
                    plan_stage_id=None,
                    task_origin="plan",
                    task_type="practice",
                    execution_mode="chat",
                    title="Practice matrices",
                    instructions="Explain matrices",
                    topic_focus="Matrices",
                    difficulty="easy",
                    question_count=None,
                    estimated_minutes=20,
                    scheduled_for=now.date(),
                    due_on=now.date(),
                    status="pending",
                    source_task_id=None,
                    execution_session_id=None,
                    last_workflow_run_id=None,
                    result_note=None,
                    created_at=now,
                    updated_at=now,
                )
            ],
            review_tasks=[],
            milestone_tasks=[],
            recent_workflow_runs=[
                WorkflowRunResponse(
                    id="run-1",
                    workflow_type="plan_generation",
                    status="completed",
                    trigger_source="initial",
                    learner_goal_id="goal-1",
                    study_plan_id="plan-1",
                    daily_task_id=None,
                    result_resource_type="study_plan",
                    result_resource_ids=["plan-1"],
                    error_code=None,
                    created_at=now,
                    started_at=now,
                    finished_at=now,
                )
            ],
            recent_sessions=[],
            autonomy_state=GoalAutonomyStateResponse(
                id="state-1",
                learner_goal_id="goal-1",
                phase="active",
                current_plan_id="plan-1",
                next_due_at=now,
                availability_snapshot={},
                mastery_snapshot={},
                last_transition_reason="initial",
                last_transition_at=now,
                created_at=now,
                updated_at=now,
            ),
            autonomy_jobs=[],
            memory_summary=WorkspaceMemorySummaryResponse(
                knowledge_items=[
                    KnowledgeMemoryBrowseItemResponse(
                        id="km-1",
                        learner_profile_id="profile-1",
                        learner_goal_id="goal-1",
                        knowledge_key="matrix_multiplication",
                        title="Matrix multiplication",
                        summary="Rows by columns.",
                        knowledge_level="core",
                        time_horizon="mid_term",
                        importance_score=0.8,
                        confidence_score=0.7,
                        freshness_score=0.9,
                        stability_score=0.6,
                        goal_relevance_score=0.9,
                        quality_score=0.75,
                        quality_tier="medium",
                        promotion_readiness="watch",
                        quality_reasons=["test"],
                        evidence_mix={"session": 1.0},
                        evidence_count=2,
                        contradiction_count=0,
                        semantic_category="concept",
                        validation_status="unverified",
                        provenance_type="system_inference",
                        tags=["matrices"],
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                ],
                behavior_items=[
                    BehaviorMemoryBrowseItemResponse(
                        id="bm-1",
                        learner_profile_id="profile-1",
                        learner_goal_id="goal-1",
                        behavior_key="needs_examples",
                        behavior_category="support_preference",
                        title="Needs examples",
                        summary="Learner benefits from concrete examples.",
                        behavior_level="pattern",
                        time_horizon="mid_term",
                        importance_score=0.7,
                        confidence_score=0.8,
                        freshness_score=0.8,
                        stability_score=0.7,
                        goal_relevance_score=0.8,
                        quality_score=0.76,
                        quality_tier="medium",
                        promotion_readiness="watch",
                        quality_reasons=["test"],
                        evidence_mix={"session": 1.0},
                        evidence_count=2,
                        contradiction_count=0,
                        semantic_category="preference",
                        validation_status="unverified",
                        provenance_type="system_inference",
                        tags=["examples"],
                        status="active",
                        created_at=now,
                        updated_at=now,
                    )
                ],
                knowledge_count=1,
                behavior_count=1,
            ),
            generated_at=now,
        )

    async def list_tasks_today(self, goal_id: str):
        raise NotImplementedError

    async def execute_task(self, task_id: str):
        raise NotImplementedError

    async def update_task_status(self, task_id: str, *, status: str, result_note: str | None):
        raise NotImplementedError

    async def get_message_history(self, session_id: str, *, limit: int = 20) -> MessageHistoryResponse:
        now = datetime.now(timezone.utc)
        return MessageHistoryResponse(
            items=[
                MessageHistoryItemResponse(
                    id="msg-1",
                    session_id=session_id,
                    role="assistant",
                    content="Matrix multiplication combines linear transformations.",
                    mode="chat",
                    skill_trace=["explain_concept"],
                    content_payload=None,
                    created_at=now,
                )
            ],
            total=1,
            next_before_id=None,
        )

    async def create_message(self, session_id: str, payload: MessageRequest) -> MessageResponse:
        raise NotImplementedError

    async def retrieve_knowledge_memories(self, *, learner_profile_id: str, query_text: str, limit: int = 3):
        raise NotImplementedError

    async def retrieve_behavior_memories(self, *, learner_profile_id: str, query_text: str, limit: int = 3):
        raise NotImplementedError

    async def browse_knowledge_memories(self, *, learner_profile_id: str, learner_goal_id: str | None = None, statuses=None, limit: int = 20, offset: int = 0):
        raise NotImplementedError

    async def browse_behavior_memories(self, *, learner_profile_id: str, learner_goal_id: str | None = None, statuses=None, limit: int = 20, offset: int = 0):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_tui_loads_workspace_and_renders_summary():
    app = AgentEduTui(
        client=_FakeClient(),
        config=CliConfig(mode="embedded", active_profile_id=None, active_goal_id=None),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        left_panel = app.query_one("#left")
        right_panel = app.query_one("#right")
        assert "Linear Algebra" in str(left_panel.render())
        assert "Matrix multiplication" in str(right_panel.render())
