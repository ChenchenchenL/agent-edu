from datetime import date, timedelta

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal import LearnerGoalService
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.goal import CreateLearnerGoalRequest, UpdateLearnerGoalStatusRequest


class FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubLearnerProfileRepository:
    def __init__(self, profiles: list[LearnerProfile] | None = None):
        self.profiles = {item.id: item for item in profiles or []}

    async def get_by_id(self, profile_id: str):
        return self.profiles.get(profile_id)


class StubLearnerGoalRepository:
    def __init__(self):
        self.goals = {}
        self.fail_on_create = False
        self.fail_on_update = False

    async def create(self, entity):
        if self.fail_on_create:
            raise RuntimeError("goal create failed")
        self.goals[entity.id] = entity

    async def list_by_profile(self, learner_profile_id: str):
        return [item for item in self.goals.values() if item.learner_profile_id == learner_profile_id]

    async def get_by_id(self, goal_id: str):
        return self.goals.get(goal_id)

    async def update(self, entity):
        if self.fail_on_update:
            raise RuntimeError("goal update failed")
        self.goals[entity.id] = entity


async def test_create_goal_persists_goal_and_audit():
    profile = LearnerProfile.build()
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = LearnerGoalService(
        repository=StubLearnerGoalRepository(),
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=fake_session,
        audit_service=AuditService(audit_repository),
    )

    response = await service.create_goal(
        learner_profile_id=profile.id,
        payload=CreateLearnerGoalRequest(
            title="Master matrices",
            subject="Linear Algebra",
            target_outcome="Solve core matrix exercises independently",
            baseline_note="Can multiply simple matrices but gets confused on dimensions.",
            deadline_date=date.today() + timedelta(days=21),
            weekly_study_minutes=180,
        ),
    )

    assert response.learner_profile_id == profile.id
    assert response.status == "active"
    assert fake_session.committed == 1
    assert audit_repository.events[0].event_type == "learner_goal.created"


async def test_create_goal_rejects_short_deadline():
    profile = LearnerProfile.build()
    service = LearnerGoalService(
        repository=StubLearnerGoalRepository(),
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
    )

    try:
        await service.create_goal(
            learner_profile_id=profile.id,
            payload=CreateLearnerGoalRequest(
                title="Master matrices",
                subject="Linear Algebra",
                target_outcome="Solve core matrix exercises independently",
                baseline_note=None,
                deadline_date=date.today() + timedelta(days=3),
                weekly_study_minutes=180,
            ),
        )
        assert False, "Expected ValidationError"
    except ValidationError:
        assert True


async def test_update_goal_status_changes_status():
    profile = LearnerProfile.build()
    repository = StubLearnerGoalRepository()
    create_service = LearnerGoalService(
        repository=repository,
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
    )
    created = await create_service.create_goal(
        learner_profile_id=profile.id,
        payload=CreateLearnerGoalRequest(
            title="Master matrices",
            subject="Linear Algebra",
            target_outcome="Solve core matrix exercises independently",
            baseline_note=None,
            deadline_date=date.today() + timedelta(days=21),
            weekly_study_minutes=180,
        ),
    )
    audit_repository = StubAuditRepository()
    fake_session = FakeSession()
    service = LearnerGoalService(
        repository=repository,
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=fake_session,
        audit_service=AuditService(audit_repository),
    )

    updated = await service.update_goal_status(
        goal_id=created.id,
        payload=UpdateLearnerGoalStatusRequest(status="paused"),
    )

    assert updated.status == "paused"
    assert fake_session.committed == 1
    assert audit_repository.events[-1].event_type == "learner_goal.status.updated"


async def test_get_missing_goal_raises_not_found():
    service = LearnerGoalService(
        repository=StubLearnerGoalRepository(),
        learner_profile_repository=StubLearnerProfileRepository(),
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
    )

    try:
        await service.get_goal("missing")
        assert False, "Expected NotFoundError"
    except NotFoundError:
        assert True


async def test_create_goal_failure_writes_durable_audit():
    profile = LearnerProfile.build()
    repository = StubLearnerGoalRepository()
    repository.fail_on_create = True
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = LearnerGoalService(
        repository=repository,
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=fake_session,
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.create_goal(
            learner_profile_id=profile.id,
            payload=CreateLearnerGoalRequest(
                title="Master matrices",
                subject="Linear Algebra",
                target_outcome="Solve core matrix exercises independently",
                baseline_note=None,
                deadline_date=date.today() + timedelta(days=21),
                weekly_study_minutes=180,
            ),
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "goal create failed" in str(exc)

    assert fake_session.rolled_back == 1
    assert audit_repository.events[-1].event_type == "learner_goal.create.failed"


async def test_update_goal_status_failure_writes_durable_audit():
    profile = LearnerProfile.build()
    repository = StubLearnerGoalRepository()
    create_service = LearnerGoalService(
        repository=repository,
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
    )
    created = await create_service.create_goal(
        learner_profile_id=profile.id,
        payload=CreateLearnerGoalRequest(
            title="Master matrices",
            subject="Linear Algebra",
            target_outcome="Solve core matrix exercises independently",
            baseline_note=None,
            deadline_date=date.today() + timedelta(days=21),
            weekly_study_minutes=180,
        ),
    )
    repository.fail_on_update = True
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = LearnerGoalService(
        repository=repository,
        learner_profile_repository=StubLearnerProfileRepository([profile]),
        db_session=fake_session,
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.update_goal_status(
            goal_id=created.id,
            payload=UpdateLearnerGoalStatusRequest(status="paused"),
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "goal update failed" in str(exc)

    assert fake_session.rolled_back == 1
    assert audit_repository.events[-1].event_type == "learner_goal.status.update.failed"
