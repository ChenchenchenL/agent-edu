from __future__ import annotations

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.tool_plan_runtime import (
    ToolPlanExecutionContext,
    ToolPlanRuntimeExecutor,
)
from agent_core.application.tools.registry import InternalToolRegistry, ToolSpec
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.errors import ValidationError


class StubAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent) -> None:
        self.events.append(entity)


@pytest.mark.asyncio
async def test_tool_plan_runtime_executes_review_scheduling_step() -> None:
    audit_repository = StubAuditRepository()
    registry = InternalToolRegistry(audit_service=AuditService(audit_repository))

    async def review_handler(payload: dict[str, object]) -> dict[str, object] | None:
        return {"created_task_ids": [str(payload["source_task_id"])]}

    registry.register(
        ToolSpec(
            name="review_scheduling",
            description="Create review tasks.",
            risk_level="low",
            handler=review_handler,
        )
    )
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=registry,
        audit_service=AuditService(audit_repository),
    )

    report = await executor.execute(
        surface="review_scheduling",
        tool_plan=[{"tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}}],
        context=ToolPlanExecutionContext(
            surface="review_scheduling",
            learner_goal_id="goal-1",
            resource_id="task-1",
            actor="system",
            source_task_id="task-1",
        ),
    )

    assert len(report.steps) == 1
    assert report.steps[0].tool_name == "review_scheduling"
    assert report.steps[0].resolved_payload == {"source_task_id": "task-1"}
    assert report.steps[0].result_payload == {"created_task_ids": ["task-1"]}


@pytest.mark.asyncio
async def test_tool_plan_runtime_rejects_unsupported_template_variable() -> None:
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=None,
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError, match="unsupported template variable"):
        await executor.execute(
            surface="review_scheduling",
            tool_plan=[{"tool_name": "review_scheduling", "payload_template": {"source_task_id": "$learner_goal_id"}}],
            context=ToolPlanExecutionContext(
                surface="review_scheduling",
                learner_goal_id="goal-1",
                resource_id="task-1",
                actor="system",
                source_task_id="task-1",
            ),
            dry_run=True,
        )


@pytest.mark.asyncio
async def test_tool_plan_runtime_rejects_missing_runtime_context_variable() -> None:
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=None,
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError, match="missing from runtime context"):
        await executor.execute(
            surface="replan",
            tool_plan=[{"tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}}],
            context=ToolPlanExecutionContext(
                surface="replan",
                learner_goal_id="goal-1",
                resource_id="goal-1",
                actor="system",
            ),
            dry_run=True,
        )


@pytest.mark.asyncio
async def test_tool_plan_runtime_dry_run_returns_preview_payload() -> None:
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=None,
        audit_service=AuditService(StubAuditRepository()),
    )

    report = await executor.execute(
        surface="assessment_generation",
        tool_plan=[
            {
                "tool_name": "assessment_generation",
                "payload_template": {"learner_goal_id": "$learner_goal_id", "topic_focus": "$topic_focus"},
            }
        ],
        context=ToolPlanExecutionContext(
            surface="assessment_generation",
            learner_goal_id="goal-1",
            resource_id="goal-1",
            actor="system",
            topic_focus="Matrices",
        ),
        dry_run=True,
    )

    assert report.dry_run is True
    assert report.steps[0].resolved_payload == {"learner_goal_id": "goal-1", "topic_focus": "Matrices"}
    assert report.steps[0].result_payload == {
        "dry_run": True,
        "preview_payload": {"learner_goal_id": "goal-1", "topic_focus": "Matrices"},
    }


@pytest.mark.asyncio
async def test_tool_plan_runtime_executes_two_step_replan_sequence() -> None:
    audit_repository = StubAuditRepository()
    registry = InternalToolRegistry(audit_service=AuditService(audit_repository))

    async def partial_replan_handler(payload: dict[str, object]) -> dict[str, object] | None:
        return {"created_task_ids": [f"{payload['source_task_id']}-repair"]}

    async def review_handler(payload: dict[str, object]) -> dict[str, object] | None:
        return {"created_task_ids": [str(payload["source_task_id"])]}

    registry.register(
        ToolSpec(
            name="partial_replan",
            description="Create repair tasks.",
            risk_level="medium",
            handler=partial_replan_handler,
        )
    )
    registry.register(
        ToolSpec(
            name="review_scheduling",
            description="Create review tasks.",
            risk_level="low",
            handler=review_handler,
        )
    )
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=registry,
        audit_service=AuditService(audit_repository),
    )

    report = await executor.execute(
        surface="replan",
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
        context=ToolPlanExecutionContext(
            surface="replan",
            learner_goal_id="goal-1",
            resource_id="task-1",
            actor="system",
            source_task_id="task-1",
        ),
    )

    assert [step.step_id for step in report.steps] == ["repair", "followup_review"]
    assert report.steps[0].result_payload == {"created_task_ids": ["task-1-repair"]}
    assert report.steps[1].resolved_payload == {"source_task_id": "task-1-repair"}
    assert report.steps[1].result_payload == {"created_task_ids": ["task-1-repair"]}


@pytest.mark.asyncio
async def test_tool_plan_runtime_rejects_future_step_reference() -> None:
    executor = ToolPlanRuntimeExecutor(
        internal_tool_registry=None,
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError, match="prior step outputs"):
        await executor.execute(
            surface="replan",
            tool_plan=[
                {
                    "step_id": "followup_review",
                    "tool_name": "review_scheduling",
                    "payload_template": {"source_task_id": "$steps.repair.created_task_ids[0]"},
                },
                {
                    "step_id": "repair",
                    "tool_name": "partial_replan",
                    "payload_template": {"source_task_id": "$source_task_id"},
                },
            ],
            context=ToolPlanExecutionContext(
                surface="replan",
                learner_goal_id="goal-1",
                resource_id="task-1",
                actor="system",
                source_task_id="task-1",
            ),
            dry_run=True,
        )
