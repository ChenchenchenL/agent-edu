from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.planning import WorkflowRun
from agent_core.infrastructure.db.repositories import WorkflowRunRepository
from agent_core.infrastructure.observability.metrics import observe_workflow_run


class WorkflowRunService:
    def __init__(
        self,
        *,
        repository: WorkflowRunRepository,
        db_session: AsyncSession,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._db_session = db_session
        self._audit_service = audit_service

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
        run = WorkflowRun.build(
            workflow_type=workflow_type,
            trigger_source=trigger_source,
            learner_goal_id=learner_goal_id,
            study_plan_id=study_plan_id,
            daily_task_id=daily_task_id,
            scheduled_job_id=scheduled_job_id,
        )
        await self._repository.create(run)
        await self._audit_service.record(
            event_type="workflow.run.started",
            resource_type="workflow_run",
            resource_id=run.id,
            actor="system",
            event_data={
                "workflow_run_id": run.id,
                "workflow_type": workflow_type,
                "trigger_source": trigger_source,
                "learner_goal_id": learner_goal_id,
                "study_plan_id": study_plan_id,
                "daily_task_id": daily_task_id,
            },
        )
        return run

    async def complete_run(
        self,
        *,
        run: WorkflowRun,
        result_resource_type: str | None,
        result_resource_ids: list[str],
    ) -> WorkflowRun:
        completed = run.complete(
            result_resource_type=result_resource_type,
            result_resource_ids=result_resource_ids,
        )
        await self._repository.update(completed)
        await self._audit_service.record(
            event_type="workflow.run.completed",
            resource_type="workflow_run",
            resource_id=completed.id,
            actor="system",
            event_data={
                "workflow_run_id": completed.id,
                "workflow_type": completed.workflow_type,
                "result_resource_type": result_resource_type,
                "result_resource_ids": result_resource_ids,
            },
        )
        observe_workflow_run(workflow_type=completed.workflow_type, status="completed", run=completed)
        return completed

    async def fail_run(self, *, run: WorkflowRun, error_code: str | None) -> WorkflowRun:
        failed = run.fail(error_code=error_code)
        await self._repository.update(failed)
        await self._audit_service.record_durable(
            event_type="workflow.run.failed",
            resource_type="workflow_run",
            resource_id=failed.id,
            actor="system",
            event_data={
                "workflow_run_id": failed.id,
                "workflow_type": failed.workflow_type,
                "error_code": error_code,
            },
        )
        observe_workflow_run(workflow_type=failed.workflow_type, status="failed", run=failed)
        return failed
