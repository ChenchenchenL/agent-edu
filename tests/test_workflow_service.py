from agent_core.application.services.audit import AuditService
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.planning import WorkflowRun


class FakeSession:
    async def commit(self):
        return None

    async def rollback(self):
        return None


class StubWorkflowRunRepository:
    def __init__(self, run: WorkflowRun):
        self.run = run
        self.updated = None

    async def create(self, entity: WorkflowRun):
        self.run = entity

    async def update(self, entity: WorkflowRun):
        self.updated = entity
        self.run = entity

    async def get_by_id(self, run_id: str):
        return self.run if self.run.id == run_id else None


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


async def test_workflow_run_failed_uses_durable_audit():
    run = WorkflowRun.build(
        workflow_type="plan_generation",
        trigger_source="initial",
        learner_goal_id="goal-1",
        study_plan_id=None,
        daily_task_id=None,
    )
    repository = StubWorkflowRunRepository(run)
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    service = WorkflowRunService(
        repository=repository,
        db_session=FakeSession(),
        audit_service=audit_service,
    )

    failed = await service.fail_run(run=run, error_code="RuntimeError")

    assert failed.status == "failed"
    assert repository.updated is not None
    assert repository.updated.status == "failed"
    assert any(event.event_type == "workflow.run.failed" for event in audit_repository.events)
