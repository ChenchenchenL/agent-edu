from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skills import (
    SkillArtifactLifecycleService,
    SkillCandidateService,
    SkillResolver,
    SkillUsageService,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import ValidationError
from agent_core.domain.schemas.skill import SkillUsageEventResponse
from agent_core.infrastructure.db.models import SkillArtifactModel, SkillUsageEventModel
from agent_core.infrastructure.db.repositories import SkillArtifactRepository

pytestmark = pytest.mark.asyncio


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

    async def update(self, entity: SkillArtifact):
        for index, artifact in enumerate(self.artifacts):
            if artifact.id == entity.id:
                self.artifacts[index] = entity
                self.artifact = entity
                return

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

    async def max_candidate_patch_version(self, name: str):
        max_patch = -1
        for artifact in self.artifacts:
            if artifact.name != name or not artifact.version.startswith("0.1."):
                continue
            patch = artifact.version.removeprefix("0.1.")
            if patch.isdecimal():
                max_patch = max(max_patch, int(patch))
        return max_patch


class StubScalarResult:
    def __init__(self, model):
        self._model = model

    def scalars(self):
        return self

    def first(self):
        return self._model


class StubExecuteSession:
    def __init__(self, models):
        self._models = list(models)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return StubScalarResult(self._models.pop(0))


def _skill_artifact_model(*, status: str, version: str = "1.0.0") -> SkillArtifactModel:
    now = datetime.now(timezone.utc)
    artifact_id = str(uuid4())
    return SkillArtifactModel(
        id=artifact_id,
        name="explain_concept",
        version=version,
        lineage_id=artifact_id,
        parent_artifact_id=None,
        supersedes_artifact_id=None,
        skill_type="baseline",
        scope="chat",
        status=status,
        description="Explain concepts.",
        definition={},
        runtime_directives={},
        tool_plan=[],
        compatibility_contract={
            "surfaces": ["chat"],
            "implementation_binding": "explain_concept",
            "dynamic_execution": False,
        },
        source_reflection_ids=[],
        source_memory_ids=[],
        source_proposal_id=None,
        quality_score=1.0,
        created_by="system_seed",
        approved_by=None,
        approved_at=None,
        created_at=now,
        updated_at=now,
    )


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
    def __init__(self, fail: bool = False, events: list[SkillUsageEvent] | None = None):
        self.fail = fail
        self.events: list[SkillUsageEvent] = list(events or [])

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
        skill_name=None,
        learner_goal_id=None,
        session_id=None,
        surface=None,
        outcome_status=None,
        resolver_status=None,
        created_at_from=None,
        limit=50,
    ):
        events = list(self.events)
        if artifact_id is not None:
            events = [item for item in events if item.skill_artifact_id == artifact_id]
        if skill_name is not None:
            events = [item for item in events if item.skill_name == skill_name]
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
        if created_at_from is not None:
            events = [item for item in events if item.created_at >= created_at_from]
        return events[:limit]


class StubProposalRolloutRepository:
    def __init__(self, rollout: ReflectionProposalRollout | None = None):
        self.rollout = rollout

    async def get_by_proposal(self, proposal_id: str):
        if self.rollout is not None and self.rollout.proposal_id == proposal_id:
            return self.rollout
        return None


class StubProposalRolloutObservationRepository:
    def __init__(self, observation: ReflectionProposalRolloutObservation | None = None):
        self.observation = observation

    async def get_by_id(self, observation_id: str):
        if self.observation is not None and self.observation.id == observation_id:
            return self.observation
        return None


class StubGoalSkillBindingRepository:
    def __init__(self, binding: GoalSkillBinding | None = None):
        self.binding = binding

    async def get_by_rollout(self, rollout_id: str):
        if self.binding is not None and self.binding.rollout_id == rollout_id:
            return self.binding
        return None


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


def test_skill_artifact_requires_exact_scope_contract_surface():
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

    try:
        SkillArtifact.build(
            name="explain_concept",
            version="1.0.0",
            skill_type="baseline",
            scope="chat",
            status="active",
            description="Overbroad contract.",
            compatibility_contract={
                "surfaces": ["chat", "quiz"],
                "implementation_binding": "explain_concept",
                "dynamic_execution": False,
            },
            quality_score=1.0,
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("artifact contract surfaces should exactly match artifact scope in V2")


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


async def test_skill_artifact_repository_prefers_stable_without_case_ordering():
    stable_model = _skill_artifact_model(status="stable", version="1.0.1")
    session = StubExecuteSession([stable_model])
    repository = SkillArtifactRepository(session)

    artifact = await repository.get_selectable_by_name_scope(name="explain_concept", scope="chat")

    assert artifact is not None
    assert artifact.status == "stable"
    assert artifact.version == "1.0.1"
    assert len(session.statements) == 1
    compiled = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert "CASE" not in compiled.upper()
    assert "stable" in compiled


async def test_skill_artifact_repository_falls_back_to_active_when_stable_missing():
    active_model = _skill_artifact_model(status="active", version="1.0.0")
    session = StubExecuteSession([None, active_model])
    repository = SkillArtifactRepository(session)

    artifact = await repository.get_selectable_by_name_scope(name="explain_concept", scope="chat")

    assert artifact is not None
    assert artifact.status == "active"
    assert artifact.version == "1.0.0"
    assert len(session.statements) == 2
    compiled_stable = str(session.statements[0].compile(compile_kwargs={"literal_binds": True}))
    compiled_active = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "stable" in compiled_stable
    assert "active" in compiled_active


def _approved_skill_package_proposal(
    *,
    proposal_type: str = "skill_package",
    evaluation_status: str = "effective",
) -> tuple[ReflectionProposal, ReflectionProposalEvaluation]:
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type=proposal_type,
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Reusable quiz remediation helps.",
        change_summary="Create quiz skill package.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "bundle_id": "bundle-1",
            "surface": "quiz",
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        }
        if proposal_type == "skill_package"
        else {"response_preference_bias": "guided"},
        expected_improvement="Reuse verified quiz remediation.",
        risk_level="low",
        evidence_snapshot={"memory_corpus": {"items": [{"memory_id": "memory-1"}, {"memory_id": "memory-1"}]}},
    ).enqueue_sandbox(
        sandbox_run_id="sandbox-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-1",
        evaluation_status=evaluation_status,
        evaluation_summary="sandbox:0.20",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    evaluation = ReflectionProposalEvaluation.build(
        proposal_id=proposal.id,
        comparison_window_size=3,
        baseline_policy_snapshot={},
        candidate_policy_snapshot=proposal.structured_patch_payload,
        evaluator_type="rule",
        sandbox_run_id="sandbox-1",
    ).with_result(
        evaluation_status=evaluation_status,
        simulated_outcome_summary={"score_delta": 0.2},
        score_delta=0.2,
        sandbox_run_id="sandbox-1",
    )
    return proposal, evaluation


def replace_payload(proposal: ReflectionProposal, patch: dict[str, object]) -> ReflectionProposal:
    payload = dict(proposal.structured_patch_payload)
    payload.update(patch)
    return replace(proposal, structured_patch_payload=payload)


async def _staged_artifact_from_proposal(
    proposal: ReflectionProposal,
    evaluation: ReflectionProposalEvaluation,
) -> SkillArtifact:
    artifact_repository = StubSkillArtifactRepository()
    candidate_service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )
    candidate = await candidate_service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")
    return candidate.mark_staged()


def _activation_rollout_bundle(
    proposal: ReflectionProposal,
) -> tuple[ReflectionProposalRollout, GoalSkillBinding, ReflectionProposalRolloutObservation, SkillUsageEvent]:
    payload = proposal.structured_patch_payload
    rollout = ReflectionProposalRollout.build(
        proposal_id=proposal.id,
        learner_goal_id=proposal.learner_goal_id,
        surface=str(payload["surface"]),
        baseline_snapshot=payload,
        runtime_overlay_payload={
            "skill_name": payload["skill_name"],
            "surface": payload["surface"],
            "match_rules": dict(payload["match_rules"]),
            "runtime_directives": dict(payload["runtime_directives"]),
            "tool_plan": [dict(item) for item in payload["tool_plan"]],
        },
        activated_by="operator",
    )
    binding = GoalSkillBinding.build(
        proposal_id=proposal.id,
        rollout_id=rollout.id,
        learner_goal_id=proposal.learner_goal_id,
        surface=str(payload["surface"]),
        priority_score=proposal.priority_score,
        match_rules=dict(payload["match_rules"]),
        runtime_directives=dict(payload["runtime_directives"]),
        tool_plan=[dict(item) for item in payload["tool_plan"]],
    ).with_status("rolled_out")
    observation = ReflectionProposalRolloutObservation.build(
        rollout_id=rollout.id,
        proposal_id=proposal.id,
        learner_goal_id=proposal.learner_goal_id,
        surface=str(payload["surface"]),
        recommendation="promote",
        observed_sample_count=3,
        positive_score=0.8,
        negative_score=0.0,
        signal_summary={"completed_usage_count": 1},
        reason_codes=["usage_promoted"],
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation.id)
    usage_event = SkillUsageEvent.build(
        skill_artifact_id=None,
        skill_name=str(payload["skill_name"]),
        skill_version=None,
        skill_status_at_use=None,
        learner_goal_id=proposal.learner_goal_id,
        surface=str(payload["surface"]),
        outcome_status="completed",
        resolver_status="missing_artifact",
        selection_reason="artifact_missing_static_fallback",
        metadata={
            "skill_package_rollout": {
                "proposal_id": proposal.id,
                "rollout_id": rollout.id,
                "binding_id": binding.id,
                "skill_name": payload["skill_name"],
                "surface": payload["surface"],
            }
        },
    )
    return rollout, binding, observation, usage_event


def _skill_artifact_lifecycle_service(
    artifact_repository: StubSkillArtifactRepository,
    proposal: ReflectionProposal | None,
    evaluation: ReflectionProposalEvaluation | None,
    audit_repository: StubAuditRepository,
    *,
    rollout: ReflectionProposalRollout | None = None,
    observation: ReflectionProposalRolloutObservation | None = None,
    binding: GoalSkillBinding | None = None,
    usage_events: list[SkillUsageEvent] | None = None,
    allowed_skills: list[str] | None = None,
) -> SkillArtifactLifecycleService:
    return SkillArtifactLifecycleService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        rollout_repository=StubProposalRolloutRepository(rollout),
        rollout_observation_repository=StubProposalRolloutObservationRepository(observation),
        goal_skill_binding_repository=StubGoalSkillBindingRepository(binding),
        usage_repository=StubSkillUsageEventRepository(events=usage_events),
        skill_registry=SkillRegistry.from_allowed_skills(allowed_skills or ["create_quiz"]),
        audit_service=AuditService(audit_repository),
    )


async def test_skill_candidate_service_creates_candidate_from_approved_effective_proposal():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository()
    audit_repository = StubAuditRepository()
    service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(audit_repository),
    )

    artifact = await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    assert artifact.status == "candidate"
    assert artifact.name == "create_quiz"
    assert artifact.version == "0.1.0"
    assert artifact.skill_type == "learned"
    assert artifact.scope == "quiz"
    assert artifact.runtime_directives == {"feedback_style": "guided_correction"}
    assert artifact.tool_plan == []
    assert artifact.compatibility_contract["dynamic_execution"] is False
    assert artifact.compatibility_contract["implementation_binding"] == "create_quiz"
    assert artifact.source_reflection_ids == ["reflection-1"]
    assert artifact.source_memory_ids == ["memory-1"]
    assert artifact.source_proposal_id == proposal.id
    assert artifact.quality_score == 0.7
    assert artifact.approved_by is None
    assert artifact.approved_at is None
    assert artifact_repository.artifacts == [artifact]
    assert any(item.event_type == "skill.artifact.candidate_created" for item in audit_repository.events)


async def test_skill_candidate_service_is_idempotent_per_source_proposal():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository()
    audit_repository = StubAuditRepository()
    service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(audit_repository),
    )

    first = await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")
    second = await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    assert first.id == second.id
    assert len(artifact_repository.artifacts) == 1
    assert any(item.event_type == "skill.artifact.candidate_reused" for item in audit_repository.events)


async def test_skill_candidate_service_rejects_unapproved_or_ineffective_sources():
    proposal, evaluation = _approved_skill_package_proposal()
    unapproved = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type="skill_package",
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Reusable quiz remediation helps.",
        change_summary="Create quiz skill package.",
        structured_patch_payload=proposal.structured_patch_payload,
        expected_improvement="Reuse verified quiz remediation.",
        risk_level="low",
        evidence_snapshot=proposal.evidence_snapshot,
    ).enqueue_sandbox(
        sandbox_run_id="sandbox-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    )
    service = SkillCandidateService(
        artifact_repository=StubSkillArtifactRepository(),
        proposal_repository=StubProposalRepository(unapproved),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError):
        await service.create_candidate_from_proposal(proposal_id=unapproved.id, operator_id="operator")

    proposal, evaluation = _approved_skill_package_proposal(evaluation_status="inconclusive")
    service = SkillCandidateService(
        artifact_repository=StubSkillArtifactRepository(),
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError):
        await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")


async def test_skill_candidate_service_rejects_non_skill_package_and_unknown_tool():
    proposal, evaluation = _approved_skill_package_proposal(proposal_type="prompt_optimization")
    service = SkillCandidateService(
        artifact_repository=StubSkillArtifactRepository(),
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError):
        await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    proposal, evaluation = _approved_skill_package_proposal()
    proposal = replace_payload(proposal, {"tool_plan": [{"tool_name": "shell"}]})
    service = SkillCandidateService(
        artifact_repository=StubSkillArtifactRepository(),
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )

    with pytest.raises(ValidationError):
        await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")


async def test_skill_candidate_service_increments_candidate_patch_version():
    proposal, evaluation = _approved_skill_package_proposal()
    existing = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="candidate",
        description="Existing candidate.",
    )
    artifact_repository = StubSkillArtifactRepository(existing)
    service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )

    artifact = await service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    assert artifact.version == "0.1.1"


async def test_skill_artifact_lifecycle_service_stages_candidate_without_approval_fields():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository()
    audit_repository = StubAuditRepository()
    candidate_service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )
    candidate = await candidate_service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")
    service = _skill_artifact_lifecycle_service(artifact_repository, proposal, evaluation, audit_repository)

    staged = await service.stage_candidate(
        artifact_id=candidate.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Operator reviewed package.",
    )

    assert staged.id == candidate.id
    assert staged.status == "staged"
    assert staged.version == candidate.version
    assert staged.approved_by is None
    assert staged.approved_at is None
    assert staged.updated_at > candidate.updated_at
    assert artifact_repository.artifacts == [staged]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.staged"
    assert event.event_data["artifact_id"] == candidate.id
    assert event.event_data["source_proposal_id"] == proposal.id
    assert event.event_data["evaluation_id"] == evaluation.id
    assert event.event_data["score_delta"] == evaluation.score_delta
    assert event.event_data["operator_id"] == "operator"
    assert event.event_data["reason_code"] == "reviewed"
    assert event.event_data["reason_note"] == "Operator reviewed package."


async def test_skill_artifact_lifecycle_service_reuses_already_staged_artifact():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Already staged.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        runtime_directives={"feedback_style": "guided_correction"},
        tool_plan=[],
        source_reflection_ids=["reflection-1"],
        source_proposal_id=proposal.id,
    )
    artifact_repository = StubSkillArtifactRepository(staged)
    audit_repository = StubAuditRepository()
    service = _skill_artifact_lifecycle_service(artifact_repository, None, None, audit_repository)

    reused = await service.stage_candidate(
        artifact_id=staged.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note=None,
    )

    assert reused == staged
    assert artifact_repository.artifacts == [staged]
    assert audit_repository.events[-1].event_type == "skill.artifact.stage_reused"


async def test_skill_artifact_lifecycle_service_rejects_invalid_stage_sources():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository()
    candidate_service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )
    candidate = await candidate_service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    non_candidate_repository = StubSkillArtifactRepository(replace(candidate, status="active"))
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            non_candidate_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    missing_source_repository = StubSkillArtifactRepository(replace(candidate, source_proposal_id=None))
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            missing_source_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(candidate),
            None,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    ineffective_evaluation = replace(evaluation, evaluation_status="ineffective")
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(candidate),
            proposal,
            ineffective_evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    low_score_evaluation = replace(evaluation, score_delta=0.09)
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(candidate),
            proposal,
            low_score_evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_rejects_invalid_artifact_contract_or_payload():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository()
    candidate_service = SkillCandidateService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        audit_service=AuditService(StubAuditRepository()),
    )
    candidate = await candidate_service.create_candidate_from_proposal(proposal_id=proposal.id, operator_id="operator")

    missing_reflection = replace(candidate, source_reflection_ids=[])
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(missing_reflection),
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    dynamic_contract = replace(
        candidate,
        compatibility_contract={
            "surfaces": ["quiz"],
            "implementation_binding": "create_quiz",
            "dynamic_execution": True,
        },
    )
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(dynamic_contract),
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    wrong_binding = replace(
        candidate,
        compatibility_contract={
            "surfaces": ["quiz"],
            "implementation_binding": "other_skill",
            "dynamic_execution": False,
        },
    )
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(wrong_binding),
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    overbroad_surfaces = replace(
        candidate,
        compatibility_contract={
            "surfaces": ["quiz", "chat"],
            "implementation_binding": "create_quiz",
            "dynamic_execution": False,
        },
    )
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(overbroad_surfaces),
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    unknown_tool_proposal = replace_payload(proposal, {"tool_plan": [{"tool_name": "shell"}]})
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(candidate),
            unknown_tool_proposal,
            evaluation,
            StubAuditRepository(),
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_activates_staged_artifact_with_rollout_usage_evidence():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    artifact_repository = StubSkillArtifactRepository(staged)
    audit_repository = StubAuditRepository()
    service = _skill_artifact_lifecycle_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
        rollout=rollout,
        observation=observation,
        binding=binding,
        usage_events=[usage_event],
    )

    activated = await service.activate_staged(
        artifact_id=staged.id,
        operator_id="operator",
        reason_code="rollout_promoted",
        reason_note="Rollout usage supports promotion.",
    )

    assert activated.id == staged.id
    assert activated.status == "active"
    assert activated.version == staged.version
    assert activated.source_proposal_id == proposal.id
    assert activated.approved_by == "operator"
    assert activated.approved_at is not None
    assert activated.updated_at > staged.updated_at
    assert artifact_repository.artifacts == [activated]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.activated"
    assert event.event_data["artifact_id"] == staged.id
    assert event.event_data["source_proposal_id"] == proposal.id
    assert event.event_data["evaluation_id"] == evaluation.id
    assert event.event_data["score_delta"] == evaluation.score_delta
    assert event.event_data["rollout_id"] == rollout.id
    assert event.event_data["binding_id"] == binding.id
    assert event.event_data["observation_id"] == observation.id
    assert event.event_data["usage_event_ids"] == [usage_event.id]
    assert event.event_data["operator_id"] == "operator"
    assert event.event_data["reason_code"] == "rollout_promoted"


async def test_skill_artifact_lifecycle_service_reuses_already_active_artifact():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    active = staged.mark_active(operator_id="operator")
    artifact_repository = StubSkillArtifactRepository(active)
    audit_repository = StubAuditRepository()
    service = _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    )

    reused = await service.activate_staged(
        artifact_id=active.id,
        operator_id="operator",
        reason_code="rollout_promoted",
        reason_note=None,
    )

    assert reused == active
    assert artifact_repository.artifacts == [active]
    assert audit_repository.events[-1].event_type == "skill.artifact.activate_reused"
    assert audit_repository.events[-1].event_data["usage_event_ids"] == []


async def test_skill_artifact_lifecycle_service_rejects_activation_without_required_rollout_evidence():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
            usage_events=[usage_event],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )

    staged_rollout = replace(rollout, status="staged")
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=staged_rollout,
            observation=observation,
            binding=binding,
            usage_events=[usage_event],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )

    missing_observation_rollout = replace(rollout, latest_observation_id=None)
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=missing_observation_rollout,
            binding=binding,
            usage_events=[usage_event],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )

    rollback_observation = replace(observation, recommendation="rollback")
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observation=rollback_observation,
            binding=binding,
            usage_events=[usage_event],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_rejects_activation_without_attributed_usage():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    wrong_metadata = replace(
        usage_event,
        metadata={
            "skill_package_rollout": {
                "proposal_id": proposal.id,
                "rollout_id": rollout.id,
                "binding_id": "other-binding",
                "skill_name": "create_quiz",
                "surface": "quiz",
            }
        },
    )
    old_usage = replace(usage_event, created_at=rollout.activated_at - timedelta(seconds=1))

    for events in ([], [wrong_metadata], [replace(usage_event, outcome_status="failed")], [old_usage]):
        with pytest.raises(ValidationError):
            await _skill_artifact_lifecycle_service(
                StubSkillArtifactRepository(staged),
                proposal,
                evaluation,
                StubAuditRepository(),
                rollout=rollout,
                observation=observation,
                binding=binding,
                usage_events=events,
            ).activate_staged(
                artifact_id=staged.id,
                operator_id="operator",
                reason_code="rollout_promoted",
                reason_note=None,
            )


async def test_skill_artifact_lifecycle_service_rejects_activation_conflict_or_disabled_skill():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    conflicting_active = SkillArtifact.build(
        name="create_quiz",
        version="1.0.0",
        skill_type="baseline",
        scope="quiz",
        status="active",
        description="Existing selectable quiz skill.",
        quality_score=1.0,
    )
    conflict_repository = StubSkillArtifactRepository(staged)
    conflict_repository.artifacts.append(conflicting_active)
    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            conflict_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observation=observation,
            binding=binding,
            usage_events=[usage_event],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observation=observation,
            binding=binding,
            usage_events=[usage_event],
            allowed_skills=["explain_concept"],
        ).activate_staged(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_promoted",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_deactivates_active_artifact():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Active learned quiz skill.",
        source_proposal_id="proposal-1",
        quality_score=0.8,
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )
    artifact_repository = StubSkillArtifactRepository(active)
    audit_repository = StubAuditRepository()

    deactivated = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).deactivate_active(
        artifact_id=active.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note="Rollback source rollout.",
    )

    assert deactivated.id == active.id
    assert deactivated.status == "deprecated"
    assert deactivated.approved_by == active.approved_by
    assert deactivated.approved_at == active.approved_at
    assert deactivated.updated_at > active.updated_at
    assert artifact_repository.artifacts == [deactivated]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.deactivated"
    assert event.event_data["artifact_id"] == active.id
    assert event.event_data["source_proposal_id"] == "proposal-1"
    assert event.event_data["operator_id"] == "operator"
    assert event.event_data["reason_code"] == "rollout_rollback"


async def test_skill_artifact_lifecycle_service_reuses_deactivated_artifact():
    deprecated = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="deprecated",
        description="Deprecated learned quiz skill.",
        quality_score=0.8,
    )
    artifact_repository = StubSkillArtifactRepository(deprecated)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).deactivate_active(
        artifact_id=deprecated.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note=None,
    )

    assert reused == deprecated
    assert artifact_repository.artifacts == [deprecated]
    assert audit_repository.events[-1].event_type == "skill.artifact.deactivate_reused"


async def test_skill_artifact_lifecycle_service_rejects_deactivation_for_non_active_artifact():
    staged = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Staged learned quiz skill.",
        quality_score=0.8,
    )

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            None,
            None,
            StubAuditRepository(),
        ).deactivate_active(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="rollout_rollback",
            reason_note=None,
        )


async def test_skill_resolver_ignores_deprecated_artifact_after_deactivation():
    deprecated = SkillArtifact.build(
        name="explain_concept",
        version="1.0.0",
        skill_type="baseline",
        scope="chat",
        status="deprecated",
        description="Deprecated skill.",
        quality_score=1.0,
    )
    audit_repository = StubAuditRepository()
    resolver = _skill_resolver(deprecated, audit_repository)

    resolution = await resolver.resolve(skill_name="explain_concept", surface="chat")

    assert resolution.resolver_status == "missing_artifact"
    assert resolution.artifact_id is None


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


async def test_skill_usage_service_records_unregistered_skill_resolution_failure_without_raising():
    audit_repository = StubAuditRepository()
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        skill_resolver=_skill_resolver(None, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="schedule_review",
        surface="review_scheduling",
        outcome_status="failed",
    )

    assert event is not None
    assert event.skill_artifact_id is None
    assert event.resolver_status == "blocked"
    assert event.selection_reason == "runtime_resolution_failed"
    assert event.error_code == "SkillResolutionValidationError"
    assert usage_repository.events[0].resolver_status == "blocked"
    assert any(item.event_type == "skill.usage.recorded" for item in audit_repository.events)
    assert not any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)


async def test_skill_usage_service_rejects_invalid_surface_in_resolution_failure_fallback():
    audit_repository = StubAuditRepository()
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(),
        skill_resolver=_skill_resolver(None, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    with pytest.raises(ValidationError):
        await service.record_usage(
            skill_name="explain_concept",
            surface="unsupported_surface",
            outcome_status="failed",
        )


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


async def test_skill_usage_service_records_blocked_resolution_without_raising():
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
    usage_repository = StubSkillUsageEventRepository()
    service = SkillUsageService(
        usage_repository=usage_repository,
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="skipped",
        error_code="SkillResolutionBlocked",
    )

    assert event is not None
    assert event.skill_artifact_id == artifact.id
    assert event.resolver_status == "blocked"
    assert event.selection_reason == "suppressed_artifact"
    assert usage_repository.events[0].resolver_status == "blocked"
    assert any(item.event_type == "skill.resolution.blocked" for item in audit_repository.events)
    assert not any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)


async def test_skill_runtime_rejects_incompatible_legacy_contract():
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
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(),
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    with pytest.raises(ValidationError):
        await service.resolve_for_runtime(skill_name="explain_concept", surface="chat")

    assert any(item.event_type == "skill.resolution.incompatible" for item in audit_repository.events)


async def test_skill_runtime_rejects_overbroad_legacy_contract_surfaces():
    artifact = _legacy_skill_artifact_with_contract(
        name="explain_concept",
        scope="chat",
        status="active",
        compatibility_contract={
            "surfaces": ["chat", "quiz"],
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

    with pytest.raises(ValidationError):
        await service.resolve_for_runtime(skill_name="explain_concept", surface="chat")

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="failed",
    )

    assert event is not None
    assert event.resolver_status == "incompatible"
    assert event.selection_reason == "contract_incompatible"
    assert usage_repository.events[0].resolver_status == "incompatible"
    assert any(item.event_type == "skill.resolution.incompatible" for item in audit_repository.events)
    assert not any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)


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

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="failed",
    )

    assert event is not None
    assert event.resolver_status == "incompatible"
    assert usage_repository.events[0].selection_reason == "contract_incompatible"
    assert any(item.event_type == "skill.resolution.incompatible" for item in audit_repository.events)
    assert not any(item.event_type == "skill.usage.record_failed" for item in audit_repository.events)


async def test_skill_usage_service_fingerprints_empty_strings_distinct_from_missing_values():
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

    blank_event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
        input_summary="   ",
        output_summary="\n",
    )
    missing_event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
    )

    empty_fingerprint = sha256(b"").hexdigest()
    assert blank_event is not None
    assert blank_event.input_fingerprint == empty_fingerprint
    assert blank_event.output_fingerprint == empty_fingerprint
    assert missing_event is not None
    assert missing_event.input_fingerprint is None
    assert missing_event.output_fingerprint is None
