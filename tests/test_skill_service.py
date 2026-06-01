from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_core.application.services.audit import AuditService
import pytest

from agent_core.application.services.skills import SkillCandidateService, SkillResolver, SkillUsageService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.reflection_closure import ReflectionProposal, ReflectionProposalEvaluation
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import ValidationError
from agent_core.domain.schemas.skill import SkillUsageEventResponse
from agent_core.infrastructure.db.models import SkillArtifactModel, SkillUsageEventModel


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubSkillArtifactRepository:
    def __init__(self, artifact: SkillArtifact | None = None):
        self.artifact = artifact
        self.artifacts: list[SkillArtifact] = [artifact] if artifact is not None else []

    async def create(self, entity: SkillArtifact):
        self.artifact = entity
        self.artifacts.append(entity)

    async def get_by_id(self, artifact_id: str):
        for artifact in self.artifacts:
            if artifact.id == artifact_id:
                return artifact
        return None

    async def get_by_source_proposal_id(self, proposal_id: str):
        for artifact in self.artifacts:
            if artifact.source_proposal_id == proposal_id:
                return artifact
        return None

    async def get_selectable_by_name_scope(self, *, name: str, scope: str):
        for artifact in self.artifacts:
            if artifact.name == name and artifact.scope == scope and artifact.status in {"active", "stable"}:
                return artifact
        return None

    async def get_suppressed_by_name_scope(self, *, name: str, scope: str):
        for artifact in self.artifacts:
            if artifact.name == name and artifact.scope == scope and artifact.status == "suppressed":
                return artifact
        return None

    async def list_artifacts(self, *, status=None, name=None, scope=None, lineage_id=None, limit=50):
        artifacts = list(self.artifacts)
        if status is not None:
            artifacts = [item for item in artifacts if item.status == status]
        if name is not None:
            artifacts = [item for item in artifacts if item.name == name]
        if scope is not None:
            artifacts = [item for item in artifacts if item.scope == scope]
        if lineage_id is not None:
            artifacts = [item for item in artifacts if item.lineage_id == lineage_id]
        return artifacts[:limit]

    async def list_by_lineage(self, lineage_id: str, *, limit: int = 50):
        return [item for item in self.artifacts if item.lineage_id == lineage_id][:limit]

    async def list_by_name(self, name: str, *, limit: int = 200):
        return [item for item in self.artifacts if item.name == name][:limit]


class StubProposalRepository:
    def __init__(self, proposal: ReflectionProposal | None = None):
        self.proposal = proposal

    async def get_by_id(self, proposal_id: str):
        if self.proposal is not None and self.proposal.id == proposal_id:
            return self.proposal
        return None


class StubProposalEvaluationRepository:
    def __init__(self, evaluation: ReflectionProposalEvaluation | None = None):
        self.evaluation = evaluation

    async def get_by_proposal(self, proposal_id: str):
        if self.evaluation is not None and self.evaluation.proposal_id == proposal_id:
            return self.evaluation
        return None


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

    async def list_events(
        self,
        *,
        artifact_id=None,
        learner_goal_id=None,
        session_id=None,
        surface=None,
        outcome_status=None,
        resolver_status=None,
        limit=50,
    ):
        events = list(self.events)
        if artifact_id is not None:
            events = [item for item in events if item.skill_artifact_id == artifact_id]
        if learner_goal_id is not None:
            events = [item for item in events if item.learner_goal_id == learner_goal_id]
        if session_id is not None:
            events = [item for item in events if item.session_id == session_id]
        if surface is not None:
            events = [item for item in events if item.surface == surface]
        if outcome_status is not None:
            events = [item for item in events if item.outcome_status == outcome_status]
        if resolver_status is not None:
            events = [item for item in events if item.resolver_status == resolver_status]
        return events[:limit]


def _skill_resolver(artifact, audit_repository, allowed_skills=None):
    return SkillResolver(
        artifact_repository=StubSkillArtifactRepository(artifact),
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(allowed_skills or ["explain_concept"]),
    )


def _legacy_skill_artifact_with_contract(
    *,
    name: str,
    scope: str,
    status: str,
    compatibility_contract: dict,
) -> SkillArtifact:
    now = datetime.now(timezone.utc)
    artifact_id = str(uuid4())
    return SkillArtifact(
        id=artifact_id,
        name=name,
        version="1.0.1",
        lineage_id=artifact_id,
        parent_artifact_id=None,
        supersedes_artifact_id=None,
        skill_type="baseline",
        scope=scope,
        status=status,
        description="Legacy skill artifact.",
        definition={},
        runtime_directives={},
        tool_plan=[],
        compatibility_contract=compatibility_contract,
        source_reflection_ids=[],
        source_memory_ids=[],
        source_proposal_id=None,
        quality_score=1.0,
        created_by="legacy_seed",
        approved_by=None,
        approved_at=None,
        created_at=now,
        updated_at=now,
    )


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
    assert artifact.lineage_id == artifact.id
    assert artifact.compatibility_contract["implementation_binding"] == "explain_concept"

    event = SkillUsageEvent.build(
        skill_artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        skill_status_at_use=artifact.status,
        surface="chat",
        outcome_status="completed",
        latency_ms=1,
        outcome_signals={"accepted_by_user": True, "confidence": 0.8},
    )
    assert event.skill_version == "1.0.0"
    assert event.outcome_signals["accepted_by_user"] is True

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

    try:
        SkillUsageEvent.build(
            skill_artifact_id=None,
            skill_name="explain_concept",
            skill_version=None,
            surface="chat",
            outcome_status="completed",
            outcome_signals={"raw_output": "unsafe"},
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("unsupported outcome signal should fail")


def test_skill_artifact_validates_type_and_scope():
    for kwargs in (
        {"skill_type": "unknown", "scope": "chat"},
        {"skill_type": "baseline", "scope": "unknown"},
    ):
        try:
            SkillArtifact.build(
                name="explain_concept",
                version="1.0.0",
                status="active",
                description="Explain concepts.",
                quality_score=1.0,
                **kwargs,
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("unsupported skill artifact type or scope should fail")


def test_skill_artifact_requires_scope_in_contract_surfaces():
    try:
        SkillArtifact.build(
            name="explain_concept",
            version="1.0.0",
            skill_type="baseline",
            scope="chat",
            status="active",
            description="Bad contract.",
            compatibility_contract={
                "surfaces": ["hint"],
                "implementation_binding": "explain_concept",
                "dynamic_execution": False,
            },
            quality_score=1.0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("artifact scope must be included in compatibility contract surfaces")


def test_skill_registry_traces_registered_non_interactive_surfaces():
    registry = SkillRegistry.from_allowed_skills(["plan_study_path", "schedule_review"])

    assert registry.trace_for_mode("plan_generation") == ["plan_study_path"]
    assert registry.trace_for_mode("review_scheduling") == ["schedule_review"]


def test_skill_usage_response_reads_entity_and_orm_metadata():
    event = SkillUsageEvent.build(
        skill_artifact_id=None,
        skill_name="explain_concept",
        skill_version=None,
        surface="chat",
        outcome_status="completed",
        metadata={"source": "entity"},
    )
    entity_response = SkillUsageEventResponse.model_validate(event)
    assert entity_response.metadata == {"source": "entity"}

    model = SkillUsageEventModel(
        id="usage-1",
        skill_artifact_id=None,
        skill_name="explain_concept",
        skill_version=None,
        skill_status_at_use=None,
        learner_profile_id=None,
        learner_goal_id=None,
        session_id=None,
        daily_task_id=None,
        workflow_run_id=None,
        surface="chat",
        topic_key=None,
        trigger_source=None,
        outcome_status="completed",
        latency_ms=None,
        cost_units=None,
        input_summary=None,
        input_fingerprint=None,
        output_summary=None,
        output_fingerprint=None,
        error_code=None,
        resolver_status="missing_artifact",
        selection_reason="artifact_missing_static_fallback",
        outcome_signals={},
        usage_metadata={"source": "orm"},
        created_at=datetime.now(timezone.utc),
    )
    orm_response = SkillUsageEventResponse.model_validate(model)
    assert orm_response.metadata == {"source": "orm"}


def test_skill_artifact_model_has_partial_unique_selectable_name_scope_index():
    indexes = {index.name: index for index in SkillArtifactModel.__table__.indexes}

    index = indexes["uq_skill_artifacts_selectable_name_scope"]
    assert index.unique is True
    assert [column.name for column in index.columns] == ["name", "scope"]
    assert index.dialect_options["sqlite"]["where"] is not None
    assert index.dialect_options["postgresql"]["where"] is not None


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
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        skill_resolver=_skill_resolver(artifact, audit_repository),
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
    assert usage_repository.events[0].skill_status_at_use == "active"
    assert usage_repository.events[0].resolver_status == "resolved"
    assert usage_repository.events[0].selection_reason == "production_default"
    assert any(item.event_type == "skill.usage.recorded" for item in audit_repository.events)


async def test_skill_usage_service_degrades_when_artifact_missing():
    audit_repository = StubAuditRepository()
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        skill_resolver=_skill_resolver(None, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
    )

    assert event is not None
    assert event.skill_artifact_id is None
    assert event.resolver_status == "missing_artifact"
    assert event.selection_reason == "artifact_missing_static_fallback"
    assert any(item.event_type == "skill.resolution.missing_artifact" for item in audit_repository.events)


async def test_skill_resolver_dry_run_does_not_audit_missing_artifact():
    audit_repository = StubAuditRepository()
    resolver = _skill_resolver(None, audit_repository)

    resolution = await resolver.resolve(skill_name="explain_concept", surface="chat", audit=False)

    assert resolution.resolver_status == "missing_artifact"
    assert audit_repository.events == []


async def test_skill_usage_service_rejects_unregistered_skill():
    audit_repository = StubAuditRepository()
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(),
        skill_resolver=_skill_resolver(None, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.record_usage(
            skill_name="schedule_review",
            surface="review_scheduling",
            outcome_status="completed",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("unregistered skill usage should fail")


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
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(fail=True),
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
    )

    assert event is None
    assert any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)


async def test_skill_resolver_blocks_suppressed_artifact_without_fallback():
    artifact = SkillArtifact.build(
        name="explain_concept",
        version="1.0.1",
        skill_type="baseline",
        scope="chat",
        status="suppressed",
        description="Suppressed concept explainer.",
        quality_score=0.0,
    )
    audit_repository = StubAuditRepository()
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(),
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.resolve_for_runtime(skill_name="explain_concept", surface="chat")
    except ValidationError:
        pass
    else:
        raise AssertionError("suppressed skill should fail closed")

    assert any(item.event_type == "skill.resolution.blocked" for item in audit_repository.events)


async def test_skill_usage_records_incompatible_legacy_contract_without_write_failure():
    artifact = _legacy_skill_artifact_with_contract(
        name="explain_concept",
        scope="chat",
        status="active",
        compatibility_contract={
            "surfaces": ["hint"],
            "implementation_binding": "explain_concept",
            "dynamic_execution": False,
        },
    )
    audit_repository = StubAuditRepository()
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    resolution = await service.resolve_for_runtime(skill_name="explain_concept", surface="chat")
    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="failed",
        resolution=resolution,
    )

    assert resolution.resolver_status == "incompatible"
    assert event is not None
    assert event.resolver_status == "incompatible"
    assert usage_repository.events[0].selection_reason == "contract_incompatible"
    assert any(item.event_type == "skill.resolution.incompatible" for item in audit_repository.events)
    assert not any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)
