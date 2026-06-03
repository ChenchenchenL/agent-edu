from agent_core.application.services.audit import AuditService
from agent_core.application.services.profile_access import hash_profile_access_key
from agent_core.application.services.profile import LearnerProfileService
from agent_core.domain.entities.audit import AuditEvent


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
    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.profiles = {}

    async def create(self, entity):
        if self.should_fail:
            raise RuntimeError("profile create failed")
        self.profiles[entity.id] = entity

    async def list_profiles(self):
        return list(self.profiles.values())

    async def get_by_id(self, profile_id: str):
        return self.profiles.get(profile_id)

    async def get_by_access_key_hash(self, access_key_hash: str):
        return next(
            (profile for profile in self.profiles.values() if profile.access_key_hash == access_key_hash),
            None,
        )

    async def update(self, entity):
        self.profiles[entity.id] = entity


async def test_create_profile_persists_profile_and_audit():
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    repository = StubLearnerProfileRepository()
    service = LearnerProfileService(
        repository,
        fake_session,
        AuditService(audit_repository),
    )

    response = await service.create_profile()

    assert response.id in repository.profiles
    assert response.access_key.startswith("edu_prof_")
    assert repository.profiles[response.id].access_key_hash == hash_profile_access_key(response.access_key)
    assert repository.profiles[response.id].access_key_created_at is not None
    assert fake_session.committed == 1
    assert audit_repository.events[0].event_type == "learner_profile.created"


async def test_create_profile_does_not_expose_hash_in_response_models():
    service = LearnerProfileService(
        StubLearnerProfileRepository(),
        FakeSession(),
        AuditService(StubAuditRepository()),
    )

    created = await service.create_profile()
    listed = await service.list_profiles()
    fetched = await service.get_profile(created.id)

    assert "access_key_hash" not in created.model_dump()
    assert "access_key_created_at" not in created.model_dump()
    assert "access_key" not in listed[0].model_dump()
    assert "access_key_hash" not in fetched.model_dump()


async def test_rotate_access_key_changes_hash_and_invalidates_old_key():
    repository = StubLearnerProfileRepository()
    audit_repository = StubAuditRepository()
    service = LearnerProfileService(
        repository,
        FakeSession(),
        AuditService(audit_repository),
    )
    created = await service.create_profile()
    old_hash = repository.profiles[created.id].access_key_hash

    rotated = await service.rotate_access_key(created.id, operator_id="operator:abc123")

    assert rotated.id == created.id
    assert rotated.access_key != created.access_key
    assert repository.profiles[created.id].access_key_hash == hash_profile_access_key(rotated.access_key)
    assert repository.profiles[created.id].access_key_hash != old_hash
    assert await repository.get_by_access_key_hash(hash_profile_access_key(created.access_key)) is None
    assert (await repository.get_by_access_key_hash(hash_profile_access_key(rotated.access_key))).id == created.id
    rotated_event = next(item for item in audit_repository.events if item.event_type == "learner_profile.access_key.rotated")
    assert rotated_event.actor == "operator:abc123"
    assert rotated_event.event_data["operator_id"] == "operator:abc123"


async def test_create_profile_failure_writes_durable_audit():
    fake_session = FakeSession()
    audit_repository = StubAuditRepository()
    service = LearnerProfileService(
        StubLearnerProfileRepository(should_fail=True),
        fake_session,
        AuditService(audit_repository),
    )

    try:
        await service.create_profile()
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "profile create failed" in str(exc)

    assert fake_session.rolled_back == 1
    assert audit_repository.events[-1].event_type == "learner_profile.create.failed"
