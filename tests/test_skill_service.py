from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skills import SkillCatalogService, SkillUsageService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import ValidationError


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubSkillArtifactRepository:
    def __init__(self, artifact: SkillArtifact | None = None):
        self.artifact = artifact

    async def get_by_id(self, artifact_id: str):
        if self.artifact is not None and self.artifact.id == artifact_id:
            return self.artifact
        return None

    async def get_active_by_name(self, name: str):
        if self.artifact is not None and self.artifact.name == name and self.artifact.status == "active":
            return self.artifact
        return None

    async def list_artifacts(self, *, status=None, name=None, limit=50):
        if self.artifact is None:
            return []
        if status is not None and self.artifact.status != status:
            return []
        if name is not None and self.artifact.name != name:
            return []
        return [self.artifact]


class StubSkillUsageEventRepository:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.events: list[SkillUsageEvent] = []

    async def create(self, entity: SkillUsageEvent):
        if self.fail:
            raise RuntimeError("write failed")
        self.events.append(entity)

    async def list_by_artifact(self, artifact_id: str, *, limit: int = 50):
        return [item for item in self.events if item.skill_artifact_id == artifact_id][:limit]

    async def list_events(self, *, learner_goal_id=None, session_id=None, surface=None, limit=50):
        events = list(self.events)
        if learner_goal_id is not None:
            events = [item for item in events if item.learner_goal_id == learner_goal_id]
        if session_id is not None:
            events = [item for item in events if item.session_id == session_id]
        if surface is not None:
            events = [item for item in events if item.surface == surface]
        return events[:limit]


def test_skill_entities_validate_status_and_usage_bounds():
    artifact = SkillArtifact.build(
        name="explain_concept",
        version="1.0.0",
        skill_type="baseline",
        scope="chat",
        status="active",
        description="Explain concepts.",
        quality_score=1.0,
    )
    assert artifact.status == "active"

    event = SkillUsageEvent.build(
        skill_artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        surface="chat",
        outcome_status="completed",
        latency_ms=1,
    )
    assert event.skill_version == "1.0.0"

    try:
        SkillUsageEvent.build(
            skill_artifact_id=None,
            skill_name="explain_concept",
            skill_version=None,
            surface="unknown",
            outcome_status="completed",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("unsupported surface should fail")


async def test_skill_usage_service_records_active_artifact_usage():
    artifact = SkillArtifact.build(
        name="explain_concept",
        version="1.0.0",
        skill_type="baseline",
        scope="chat",
        status="active",
        description="Explain concepts.",
        quality_score=1.0,
    )
    audit_repository = StubAuditRepository()
    catalog = SkillCatalogService(
        artifact_repository=StubSkillArtifactRepository(artifact),
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(["explain_concept"]),
    )
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        catalog_service=catalog,
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
        learner_profile_id="profile-1",
        session_id="session-1",
    )

    assert event is not None
    assert event.skill_artifact_id == artifact.id
    assert usage_repository.events[0].skill_version == "1.0.0"
    assert any(item.event_type == "skill.usage.recorded" for item in audit_repository.events)


async def test_skill_usage_service_degrades_when_artifact_missing():
    audit_repository = StubAuditRepository()
    catalog = SkillCatalogService(
        artifact_repository=StubSkillArtifactRepository(None),
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(["explain_concept"]),
    )
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        catalog_service=catalog,
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
    )

    assert event is not None
    assert event.skill_artifact_id is None
    assert any(item.event_type == "skill.artifact.missing" for item in audit_repository.events)


async def test_skill_usage_service_audits_write_failure_without_raising():
    artifact = SkillArtifact.build(
        name="explain_concept",
        version="1.0.0",
        skill_type="baseline",
        scope="chat",
        status="active",
        description="Explain concepts.",
        quality_score=1.0,
    )
    audit_repository = StubAuditRepository()
    catalog = SkillCatalogService(
        artifact_repository=StubSkillArtifactRepository(artifact),
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(["explain_concept"]),
    )
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(fail=True),
        catalog_service=catalog,
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
    )

    assert event is None
    assert any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)
