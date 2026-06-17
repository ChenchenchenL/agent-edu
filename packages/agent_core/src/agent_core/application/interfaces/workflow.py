"""Workflow run service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.entities.planning import WorkflowRun


class WorkflowRunServiceProtocol(Protocol):
    """Contract for workflow run orchestration."""

    async def create_run(
        self,
        *,
        workflow_type: str,
        trigger_source: str,
        learner_goal_id: str | None,
        study_plan_id: str | None,
        daily_task_id: str | None,
        scheduled_job_id: str | None = None,
    ) -> WorkflowRun:
        """Create a workflow run."""

    async def complete_run(
        self,
        *,
        run: WorkflowRun,
        result_resource_type: str | None,
        result_resource_ids: list[str] | None,
    ) -> WorkflowRun:
        """Mark a workflow run as completed."""

    async def fail_run(
        self,
        *,
        run: WorkflowRun,
        error_code: str | None,
    ) -> WorkflowRun:
        """Mark a workflow run as failed."""
