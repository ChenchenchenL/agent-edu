from agent_core.application.services.audit import AuditService
from agent_core.application.services.session import SessionService
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.session import CreateSessionRequest, UpdateSessionStatusRequest


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def begin(self):
        return FakeTransaction()

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


class StubSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, LearningSession] = {}

    async def create(self, entity: LearningSession) -> None:
        self.sessions[entity.id] = entity

    async def list_sessions(self) -> list[LearningSession]:
        return sorted(
            self.sessions.values(),
            key=lambda item: (item.last_activity_at, item.created_at),
            reverse=True,
        )

    async def get_by_id(self, session_id: str) -> LearningSession | None:
        return self.sessions.get(session_id)

    async def update(self, entity: LearningSession) -> None:
        self.sessions[entity.id] = entity


class StubLearnerProfileRepository:
    def __init__(self) -> None:
        self.profiles = []

    async def create(self, entity) -> None:
        self.profiles.append(entity)

    async def get_by_id(self, profile_id: str):
        for item in self.profiles:
            if item.id == profile_id:
                return item
        return None


class StubLearnerGoalRepository:
    async def get_by_id(self, goal_id: str):
        return None


class StubAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent) -> None:
        self.events.append(entity)


class FailingCreateSessionRepository(StubSessionRepository):
    async def create(self, entity: LearningSession) -> None:
        raise RuntimeError("session create failed")


class FailingUpdateSessionRepository(StubSessionRepository):
    async def update(self, entity: LearningSession) -> None:
        raise RuntimeError("session update failed")


async def test_create_session_sets_defaults():
    repository = StubSessionRepository()
    fake_session = FakeSession()
    learner_profiles = StubLearnerProfileRepository()
    audit_repository = StubAuditRepository()
    service = SessionService(
        repository,
        learner_profiles,
        StubLearnerGoalRepository(),
        fake_session,
        AuditService(audit_repository),
    )

    response = await service.create_session(
        CreateSessionRequest(title="Geometry", subject="Triangles")
    )

    assert response.status == "active"
    assert response.message_count == 0
    assert response.summary is None
    assert len(learner_profiles.profiles) == 1
    assert repository.sessions[response.id].learner_profile_id == learner_profiles.profiles[0].id
    assert fake_session.committed == 1
    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_type == "session.created"


async def test_list_sessions_returns_created_session():
    repository = StubSessionRepository()
    service = SessionService(
        repository,
        StubLearnerProfileRepository(),
        StubLearnerGoalRepository(),
        FakeSession(),
        AuditService(StubAuditRepository()),
    )
    created = await service.create_session(
        CreateSessionRequest(title="Probability", subject="Distributions")
    )

    sessions = await service.list_sessions()

    assert len(sessions) == 1
    assert sessions[0].id == created.id


async def test_update_session_status():
    repository = StubSessionRepository()
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = SessionService(
        repository,
        StubLearnerProfileRepository(),
        StubLearnerGoalRepository(),
        fake_session,
        AuditService(audit_repository),
    )
    created = await service.create_session(
        CreateSessionRequest(title="Physics", subject="Motion")
    )

    updated = await service.update_session_status(
        created.id,
        UpdateSessionStatusRequest(status="archived"),
    )

    assert updated.status == "archived"
    assert fake_session.committed == 2
    assert audit_repository.events[-1].event_type == "session.status.updated"


async def test_update_session_status_rejects_invalid_status():
    repository = StubSessionRepository()
    service = SessionService(
        repository,
        StubLearnerProfileRepository(),
        StubLearnerGoalRepository(),
        FakeSession(),
        AuditService(StubAuditRepository()),
    )
    created = await service.create_session(
        CreateSessionRequest(title="Chemistry", subject="Atoms")
    )

    try:
        await service.update_session_status(
            created.id,
            UpdateSessionStatusRequest(status="paused"),
        )
        assert False, "Expected ValidationError"
    except ValidationError:
        assert True


async def test_get_missing_session_raises_not_found():
    repository = StubSessionRepository()
    service = SessionService(
        repository,
        StubLearnerProfileRepository(),
        StubLearnerGoalRepository(),
        FakeSession(),
        AuditService(StubAuditRepository()),
    )

    try:
        await service.get_session("missing")
        assert False, "Expected NotFoundError"
    except NotFoundError:
        assert True


async def test_create_session_failure_writes_durable_audit():
    fake_session = FakeSession()
    learner_profiles = StubLearnerProfileRepository()
    audit_repository = StubAuditRepository()
    service = SessionService(
        FailingCreateSessionRepository(),
        learner_profiles,
        StubLearnerGoalRepository(),
        fake_session,
        AuditService(audit_repository),
    )

    try:
        await service.create_session(
            CreateSessionRequest(title="Biology", subject="Cells")
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "session create failed" in str(exc)

    assert fake_session.rolled_back == 1
    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_type == "session.create.failed"


async def test_update_session_failure_writes_durable_audit():
    repository = FailingUpdateSessionRepository()
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = SessionService(
        repository,
        StubLearnerProfileRepository(),
        StubLearnerGoalRepository(),
        fake_session,
        AuditService(audit_repository),
    )
    created = await service.create_session(
        CreateSessionRequest(title="History", subject="Ancient Rome")
    )

    try:
        await service.update_session_status(
            created.id,
            UpdateSessionStatusRequest(status="completed"),
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "session update failed" in str(exc)

    assert fake_session.rolled_back == 1
    assert audit_repository.events[-1].event_type == "session.status.update.failed"
