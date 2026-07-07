from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.skills import (
    SkillArtifactLifecycleService,
    SkillCandidateService,
    SkillCuratorJobConfig,
    SkillCuratorJobService,
    SkillCuratorRecommendationService,
    SkillReplacementReadinessService,
    SkillReplacementStagingService,
    SkillResolver,
    SkillUsageService,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.memory import ConflictStatusImpact, MemoryConflictSet
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutDecision,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation, SkillResolution, SkillUsageEvent
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.skill import (
    DeactivateSkillArtifactRequest,
    ReplaceSkillArtifactRequest,
    RestoreSkillArtifactRequest,
    SkillUsageEventResponse,
    SuppressSkillArtifactRequest,
)
from agent_core.infrastructure.db.models import SkillArtifactModel, SkillCuratorRecommendationModel, SkillUsageEventModel
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

    async def get_by_id_for_update(self, artifact_id: str):
        return await self.get_by_id(artifact_id)

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

    async def get_selectable_by_name_scope_for_update(self, *, name: str, scope: str):
        return await self.get_selectable_by_name_scope(name=name, scope=scope)

    async def get_suppressed_by_name_scope(self, *, name: str, scope: str):
        for artifact in self.artifacts:
            if artifact.name == name and artifact.scope == scope and artifact.status == "suppressed":
                return artifact
        return None

    async def get_suppressed_by_name_scope_for_update(self, *, name: str, scope: str):
        return await self.get_suppressed_by_name_scope(name=name, scope=scope)

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
        deprecated_by=None,
        deprecated_at=None,
        suppressed_reason_code=None,
        suppressed_reason_note=None,
        suppressed_by=None,
        suppressed_at=None,
        suppressed_previous_status=None,
        created_at=now,
        updated_at=now,
    )


class StubProposalRepository:
    def __init__(self, proposal: ReflectionProposal | list[ReflectionProposal] | None = None):
        if proposal is None:
            self.proposals: list[ReflectionProposal] = []
        elif isinstance(proposal, list):
            self.proposals = list(proposal)
        else:
            self.proposals = [proposal]

    async def get_by_id(self, proposal_id: str):
        for proposal in self.proposals:
            if proposal.id == proposal_id:
                return proposal
        return None

    async def create(self, entity: ReflectionProposal):
        self.proposals.append(entity)

    async def update(self, entity: ReflectionProposal):
        for index, proposal in enumerate(self.proposals):
            if proposal.id == entity.id:
                self.proposals[index] = entity
                return
        self.proposals.append(entity)

    async def list_queue(self, **kwargs):
        items = list(self.proposals)
        statuses = kwargs.get("statuses")
        if statuses is not None:
            items = [item for item in items if item.status in statuses]
        learner_goal_id = kwargs.get("learner_goal_id")
        if learner_goal_id is not None:
            items = [item for item in items if item.learner_goal_id == learner_goal_id]
        proposal_type = kwargs.get("proposal_type")
        if proposal_type is not None:
            items = [item for item in items if item.proposal_type == proposal_type]
        target_scope = kwargs.get("target_scope")
        if target_scope is not None:
            items = [item for item in items if item.target_scope == target_scope]
        offset = int(kwargs.get("offset") or 0)
        limit = int(kwargs.get("limit") or 50)
        return items[offset : offset + limit]

    async def count_queue(self, **kwargs):
        return len(await self.list_queue(**kwargs))


class StubProposalEvaluationRepository:
    def __init__(self, evaluation: ReflectionProposalEvaluation | list[ReflectionProposalEvaluation] | None = None):
        if evaluation is None:
            self.evaluations: list[ReflectionProposalEvaluation] = []
        elif isinstance(evaluation, list):
            self.evaluations = list(evaluation)
        else:
            self.evaluations = [evaluation]

    async def get_by_proposal(self, proposal_id: str):
        for evaluation in self.evaluations:
            if evaluation.proposal_id == proposal_id:
                return evaluation
        return None


class StubSkillPatchProposalService:
    def __init__(self, *, source_proposal: ReflectionProposal | None = None, fail: bool = False):
        self.source_proposal = source_proposal
        self.fail = fail
        self.created: list[dict[str, object]] = []
        self.proposals: list[ReflectionProposal] = []

    async def get(self, proposal_id: str):
        if self.source_proposal is not None and self.source_proposal.id == proposal_id:
            return self.source_proposal
        for proposal in self.proposals:
            if proposal.id == proposal_id:
                return proposal
        raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")

    async def create_skill_patch_request_from_recommendation(self, **kwargs):
        if self.fail:
            raise ValidationError("proposal creation failed")
        self.created.append(dict(kwargs))
        proposal = ReflectionProposal.build(
            reflection_record_id=str(kwargs["reflection_record_id"]),
            learner_goal_id=str(kwargs["learner_goal_id"]),
            proposal_type="skill_patch_request",
            target_scope=str(kwargs["surface"]),
            priority_score=0.65,
            hypothesis="Patch request from curator evidence.",
            change_summary="Create a governed skill patch request.",
            structured_patch_payload={
                "artifact_id": kwargs["artifact_id"],
                "skill_name": kwargs["skill_name"],
                "skill_version": kwargs["skill_version"],
                "scope": kwargs["scope"],
                "surface": kwargs["surface"],
                "recommendation_id": kwargs["recommendation_id"],
                "recommendation_reason_code": kwargs["recommendation_reason_code"],
                "usage_event_ids": list(kwargs["evidence_snapshot"].get("usage_event_ids") or []),
                "related_artifact_ids": list(kwargs["related_artifact_ids"]),
                "evidence_snapshot": dict(kwargs["evidence_snapshot"]),
                "metrics_snapshot": dict(kwargs["metrics_snapshot"]),
            },
            expected_improvement="Route curator evidence through proposal governance.",
            risk_level="medium",
            evidence_snapshot={},
        )
        self.proposals.append(proposal)
        return proposal

    async def create_skill_merge_package_from_recommendation(self, **kwargs):
        if self.fail:
            raise ValidationError("proposal creation failed")
        self.created.append(dict(kwargs))
        proposal = ReflectionProposal.build(
            reflection_record_id=str(kwargs["reflection_record_id"]),
            learner_goal_id=str(kwargs["learner_goal_id"]),
            proposal_type="skill_package",
            target_scope=str(kwargs["surface"]),
            priority_score=0.7,
            hypothesis="Merge package from curator evidence.",
            change_summary="Create a governed skill merge proposal.",
            structured_patch_payload={
                "artifact_kind": "declarative_skill_package",
                "skill_name": kwargs["skill_name"],
                "surface": kwargs["surface"],
                "match_rules": {"task_types": ["practice", "review"]},
                "runtime_directives": {"feedback_style": "guided_correction"},
                "tool_plan": [],
                "scoring_contract": {"mode": "rule_replay_live_llm"},
            },
            expected_improvement="Route curator merge evidence through proposal governance.",
            risk_level="medium",
            evidence_snapshot={
                "source": "skill_curator_merge_recommendation",
                "recommendation_id": kwargs["recommendation_id"],
                "source_artifact_id": kwargs["artifact_id"],
                "source_artifact_lineage_id": "lineage-1",
                "merge_source_artifact_ids": list(kwargs["related_artifact_ids"]),
            },
        )
        self.proposals.append(proposal)
        return proposal


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


class StubSkillCuratorRecommendationRepository:
    def __init__(self, recommendations: list[SkillCuratorRecommendation] | None = None):
        self.recommendations: list[SkillCuratorRecommendation] = list(recommendations or [])
        self.operations: list[str] = []

    async def create(self, entity: SkillCuratorRecommendation):
        self.operations.append("create")
        self.recommendations.append(entity)

    async def update(self, entity: SkillCuratorRecommendation):
        self.operations.append("update")
        for index, recommendation in enumerate(self.recommendations):
            if recommendation.id == entity.id:
                self.recommendations[index] = entity
                return

    async def get_by_id(self, recommendation_id: str):
        for recommendation in self.recommendations:
            if recommendation.id == recommendation_id:
                return recommendation
        return None

    async def get_by_source_job_id(self, source_job_id: str):
        for recommendation in self.recommendations:
            if recommendation.source_job_id == source_job_id:
                return recommendation
        return None

    async def find_pending_duplicate(
        self,
        *,
        artifact_id=None,
        skill_name,
        scope,
        surface,
        recommendation_type,
        recommended_action,
        reason_code,
    ):
        for recommendation in self.recommendations:
            if (
                recommendation.status == "pending"
                and recommendation.artifact_id == artifact_id
                and recommendation.skill_name == skill_name
                and recommendation.scope == scope
                and recommendation.surface == surface
                and recommendation.recommendation_type == recommendation_type
                and recommendation.recommended_action == recommended_action
                and recommendation.reason_code == reason_code
            ):
                return recommendation
        return None

    async def list_recommendations(
        self,
        *,
        status=None,
        recommendation_type=None,
        recommended_action=None,
        artifact_id=None,
        skill_name=None,
        scope=None,
        surface=None,
        limit=50,
    ):
        recommendations = list(self.recommendations)
        if status is not None:
            recommendations = [item for item in recommendations if item.status == status]
        if recommendation_type is not None:
            recommendations = [item for item in recommendations if item.recommendation_type == recommendation_type]
        if recommended_action is not None:
            recommendations = [item for item in recommendations if item.recommended_action == recommended_action]
        if artifact_id is not None:
            recommendations = [item for item in recommendations if item.artifact_id == artifact_id]
        if skill_name is not None:
            recommendations = [item for item in recommendations if item.skill_name == skill_name]
        if scope is not None:
            recommendations = [item for item in recommendations if item.scope == scope]
        if surface is not None:
            recommendations = [item for item in recommendations if item.surface == surface]
        return recommendations[:limit]


class StubSkillLifecycleForRecommendation:
    def __init__(self, artifact: SkillArtifact | None = None, *, fail: bool = False):
        self.artifact = artifact
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self.operations: list[str] = []

    async def stabilize_active(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "stabilize_active",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("stable evidence missing")
        assert self.artifact is not None
        return replace(self.artifact, status="stable")

    async def activate_staged(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "activate_staged",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("activation failed")
        assert self.artifact is not None
        return self.artifact.mark_active(operator_id=operator_id)

    async def suppress_selectable(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "suppress_selectable",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("suppression failed")
        assert self.artifact is not None
        return self.artifact.mark_suppressed(operator_id=operator_id, reason_code=reason_code, reason_note=reason_note)

    async def deactivate_active(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "deactivate_active",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("deactivation failed")
        assert self.artifact is not None
        return self.artifact.mark_deprecated(operator_id=operator_id)

    async def restore_suppressed(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "restore_suppressed",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("restore failed")
        assert self.artifact is not None
        return self.artifact.restore_suppressed(operator_id=operator_id)

    async def replace_selectable(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "replace_selectable",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("replacement failed")
        assert self.artifact is not None
        return self.artifact.mark_active(operator_id=operator_id)

    async def archive_deprecated(self, *, artifact_id: str, operator_id: str, reason_code: str, reason_note: str | None):
        self.operations.append("lifecycle")
        self.calls.append(
            {
                "action": "archive_deprecated",
                "artifact_id": artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            }
        )
        if self.fail:
            raise ValidationError("archive failed")
        assert self.artifact is not None
        return self.artifact.mark_archived(operator_id=operator_id)


class StubProposalRolloutRepository:
    def __init__(self, rollout: ReflectionProposalRollout | None = None):
        self.rollout = rollout

    async def get_by_proposal(self, proposal_id: str):
        if self.rollout is not None and self.rollout.proposal_id == proposal_id:
            return self.rollout
        return None

    async def list_by_proposal_and_statuses(self, proposal_id: str, *, statuses: list[str]):
        if (
            self.rollout is not None
            and self.rollout.proposal_id == proposal_id
            and self.rollout.status in statuses
        ):
            return [self.rollout]
        return []


class StubProposalRolloutObservationRepository:
    def __init__(self, observations: list[ReflectionProposalRolloutObservation] | None = None):
        self.observations: list[ReflectionProposalRolloutObservation] = list(observations or [])

    async def get_by_id(self, observation_id: str):
        for observation in self.observations:
            if observation.id == observation_id:
                return observation
        return None

    async def list_by_rollout(self, rollout_id: str):
        return [item for item in self.observations if item.rollout_id == rollout_id]


class StubProposalRolloutDecisionRepository:
    def __init__(self, decisions: list[ReflectionProposalRolloutDecision] | None = None):
        self.decisions: list[ReflectionProposalRolloutDecision] = list(decisions or [])

    async def list_by_rollout(self, rollout_id: str):
        return [item for item in self.decisions if item.rollout_id == rollout_id]


class StubGoalSkillBindingRepository:
    def __init__(self, binding: GoalSkillBinding | None = None):
        self.binding = binding

    async def get_by_rollout(self, rollout_id: str):
        if self.binding is not None and self.binding.rollout_id == rollout_id:
            return self.binding
        return None

    async def list_by_proposal_and_statuses(self, proposal_id: str, *, statuses: list[str]):
        if (
            self.binding is not None
            and self.binding.proposal_id == proposal_id
            and self.binding.status in statuses
        ):
            return [self.binding]
        return []


class StubMemoryConflictRepository:
    def __init__(self, conflicts: list[MemoryConflictSet] | None = None):
        self.conflicts: list[MemoryConflictSet] = list(conflicts or [])

    async def list_open_sets_by_goal_topics(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str] | None = None,
        updated_at_from: datetime | None = None,
        limit: int = 20,
    ):
        conflicts = [
            item
            for item in self.conflicts
            if item.learner_goal_id == learner_goal_id and item.status == "open"
        ]
        if topic_keys:
            conflicts = [item for item in conflicts if item.topic_key in topic_keys]
        if updated_at_from is not None:
            conflicts = [item for item in conflicts if item.updated_at >= updated_at_from]
        return conflicts[:limit]


class StubReflectionOutcomeEvaluationRepository:
    def __init__(self, outcomes: list[ReflectionOutcomeEvaluation] | None = None):
        self.outcomes: list[ReflectionOutcomeEvaluation] = list(outcomes or [])

    async def list_by_goal_topics(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str] | None = None,
        statuses: set[str] | None = None,
        updated_at_from: datetime | None = None,
        limit: int = 20,
    ):
        outcomes = [item for item in self.outcomes if item.learner_goal_id == learner_goal_id]
        if topic_keys:
            outcomes = [item for item in outcomes if item.topic_key in topic_keys]
        if statuses:
            outcomes = [item for item in outcomes if item.evaluation_status in statuses]
        if updated_at_from is not None:
            outcomes = [item for item in outcomes if item.updated_at >= updated_at_from]
        return outcomes[:limit]


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
        plan_templates=[],
        compatibility_contract=compatibility_contract,
        source_reflection_ids=[],
        source_memory_ids=[],
        source_proposal_id=None,
        quality_score=1.0,
        created_by="legacy_seed",
        approved_by=None,
        approved_at=None,
        deprecated_by=None,
        deprecated_at=None,
        suppressed_reason_code=None,
        suppressed_reason_note=None,
        suppressed_by=None,
        suppressed_at=None,
        suppressed_previous_status=None,
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


def test_deactivate_skill_artifact_request_rejects_unknown_reason_code():
    DeactivateSkillArtifactRequest(reason_code="rollout_rollback")
    ReplaceSkillArtifactRequest(reason_code="superseded")
    SuppressSkillArtifactRequest(reason_code="safety_risk")
    RestoreSkillArtifactRequest(reason_code="operator_restore")

    with pytest.raises(ValueError):
        DeactivateSkillArtifactRequest(reason_code="freeform_reason")
    with pytest.raises(ValueError):
        ReplaceSkillArtifactRequest(reason_code="freeform_reason")
    with pytest.raises(ValueError):
        SuppressSkillArtifactRequest(reason_code="freeform_reason")
    with pytest.raises(ValueError):
        RestoreSkillArtifactRequest(reason_code="freeform_reason")


def test_skill_artifact_model_has_partial_unique_selectable_name_scope_index():
    indexes = {index.name: index for index in SkillArtifactModel.__table__.indexes}

    index = indexes["uq_skill_artifacts_selectable_name_scope"]
    assert index.unique is True
    assert [column.name for column in index.columns] == ["name", "scope"]
    assert index.dialect_options["sqlite"]["where"] is not None
    assert index.dialect_options["postgresql"]["where"] is not None

    suppressed_index = indexes["uq_skill_artifacts_suppressed_name_scope"]
    assert suppressed_index.unique is True
    assert [column.name for column in suppressed_index.columns] == ["name", "scope"]
    assert suppressed_index.dialect_options["sqlite"]["where"] is not None
    assert suppressed_index.dialect_options["postgresql"]["where"] is not None


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
    target_scope: str = "quiz",
    structured_patch_payload: dict[str, object] | None = None,
) -> tuple[ReflectionProposal, ReflectionProposalEvaluation]:
    payload = (
        structured_patch_payload
        if structured_patch_payload is not None
        else {
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "bundle_id": "bundle-1",
            "surface": target_scope,
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        }
    )
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-1",
        learner_goal_id="goal-1",
        proposal_type=proposal_type,
        target_scope=target_scope,
        priority_score=0.8,
        hypothesis="Reusable quiz remediation helps.",
        change_summary="Create quiz skill package.",
        structured_patch_payload=payload if proposal_type == "skill_package" else {"response_preference_bias": "guided"},
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


def _realized_replacement_skill_package_proposal(
    source_artifact: SkillArtifact,
    *,
    status: str = "approved",
    evaluation_status: str = "effective",
    source: str = "skill_patch_request_realization",
) -> tuple[ReflectionProposal, ReflectionProposalEvaluation]:
    evidence_snapshot = {
        "source": source,
        "source_artifact_id": source_artifact.id,
        "source_artifact_lineage_id": source_artifact.lineage_id,
        "usage_event_ids": ["usage-1", "usage-2"],
    }
    if source == "skill_patch_request_realization":
        evidence_snapshot["source_skill_patch_request_id"] = "patch-request-1"
    if source == "skill_curator_merge_recommendation":
        evidence_snapshot["recommendation_id"] = "recommendation-merge-1"
        evidence_snapshot["merge_source_artifact_ids"] = ["artifact-merge-source"]
    proposal = ReflectionProposal.build(
        reflection_record_id="reflection-replacement",
        learner_goal_id="goal-1",
        proposal_type="skill_package",
        target_scope=source_artifact.scope,
        priority_score=0.8,
        hypothesis=f"A governed replacement for {source_artifact.name} can address curator evidence.",
        change_summary=f"Replace {source_artifact.name} skill package.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": source_artifact.name,
            "surface": source_artifact.scope,
            "match_rules": dict(source_artifact.definition["match_rules"]),
            "runtime_directives": dict(source_artifact.runtime_directives),
            "tool_plan": [dict(item) for item in source_artifact.tool_plan],
            "scoring_contract": dict(source_artifact.definition["scoring_contract"]),
        },
        expected_improvement="Evaluate replacement through existing skill lifecycle gates.",
        risk_level="medium",
        evidence_snapshot=evidence_snapshot,
    ).enqueue_sandbox(
        sandbox_run_id="sandbox-replacement-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-replacement-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-replacement-1",
        evaluation_status=evaluation_status,
        evaluation_summary="sandbox:0.20",
    )
    if status == "approved":
        proposal = proposal.approve(
            operator_id="operator",
            reason_code="validated",
            reason_note=None,
        )
    evaluation = ReflectionProposalEvaluation.build(
        proposal_id=proposal.id,
        comparison_window_size=3,
        baseline_policy_snapshot={"source_artifact_id": source_artifact.id},
        candidate_policy_snapshot=proposal.structured_patch_payload,
        evaluator_type="rule",
        sandbox_run_id="sandbox-replacement-1",
    ).with_result(
        evaluation_status=evaluation_status,
        simulated_outcome_summary={"score_delta": 0.2},
        score_delta=0.2,
        sandbox_run_id="sandbox-replacement-1",
    )
    return proposal, evaluation


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


def _stable_rollout_observation(
    *,
    proposal: ReflectionProposal,
    rollout: ReflectionProposalRollout,
    recommendation: str,
    created_at: datetime,
) -> ReflectionProposalRolloutObservation:
    return replace(
        ReflectionProposalRolloutObservation.build(
            rollout_id=rollout.id,
            proposal_id=proposal.id,
            learner_goal_id=proposal.learner_goal_id,
            surface=rollout.surface,
            recommendation=recommendation,
            observed_sample_count=5,
            positive_score=0.9 if recommendation == "promote" else 0.2,
            negative_score=0.0 if recommendation == "promote" else 0.8,
            signal_summary={"stable_window": True},
            reason_codes=["stable_evidence" if recommendation == "promote" else "negative_signal"],
        ),
        created_at=created_at,
    )


def _stable_usage_event(
    *,
    artifact: SkillArtifact,
    proposal: ReflectionProposal,
    rollout: ReflectionProposalRollout,
    binding: GoalSkillBinding,
    outcome_status: str,
    created_at: datetime,
) -> SkillUsageEvent:
    payload = proposal.structured_patch_payload
    return replace(
        SkillUsageEvent.build(
            skill_artifact_id=artifact.id,
            skill_name=str(payload["skill_name"]),
            skill_version=artifact.version,
            skill_status_at_use=artifact.status,
            learner_goal_id=proposal.learner_goal_id,
            surface=str(payload["surface"]),
            outcome_status=outcome_status,
            resolver_status="resolved",
            selection_reason="production_default",
            metadata={
                "skill_package_rollout": {
                    "proposal_id": proposal.id,
                    "rollout_id": rollout.id,
                    "binding_id": binding.id,
                    "skill_name": payload["skill_name"],
                    "surface": payload["surface"],
                }
            },
        ),
        created_at=created_at,
    )


def _stable_evidence_bundle(
    *,
    artifact: SkillArtifact,
    proposal: ReflectionProposal,
    rollout: ReflectionProposalRollout,
    binding: GoalSkillBinding,
    negative_usage_count: int = 0,
) -> tuple[list[ReflectionProposalRolloutObservation], list[SkillUsageEvent]]:
    evidence_started_at = artifact.approved_at or artifact.updated_at
    observations = [
        _stable_rollout_observation(
            proposal=proposal,
            rollout=rollout,
            recommendation="promote",
            created_at=evidence_started_at + timedelta(minutes=1),
        ),
        _stable_rollout_observation(
            proposal=proposal,
            rollout=rollout,
            recommendation="promote",
            created_at=evidence_started_at + timedelta(minutes=2),
        ),
    ]
    usage_events = [
        _stable_usage_event(
            artifact=artifact,
            proposal=proposal,
            rollout=rollout,
            binding=binding,
            outcome_status="completed",
            created_at=evidence_started_at + timedelta(minutes=3 + index),
        )
        for index in range(5)
    ]
    usage_events.extend(
        _stable_usage_event(
            artifact=artifact,
            proposal=proposal,
            rollout=rollout,
            binding=binding,
            outcome_status="failed",
            created_at=evidence_started_at + timedelta(minutes=10 + index),
        )
        for index in range(negative_usage_count)
    )
    return observations, usage_events


def _source_artifact_for_replacement(*, status: str = "stable") -> SkillArtifact:
    return SkillArtifact.build(
        name="create_quiz",
        version="0.1.77",
        skill_type="learned",
        scope="quiz",
        status=status,
        description="Current quiz skill package.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {"task_types": ["practice"], "topic_keys": ["algebra"]},
            "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
        },
        runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
        tool_plan=[],
        compatibility_contract={
            "surfaces": ["quiz"],
            "implementation_binding": "create_quiz",
            "input_schema_version": "1.0",
            "output_schema_version": "1.0",
            "dynamic_execution": False,
        },
        source_reflection_ids=["reflection-source"],
        source_memory_ids=["memory-source"],
        source_proposal_id="proposal-source",
        quality_score=0.8,
        created_by="operator",
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )


def _overlap_skill_artifact(
    *,
    name: str = "create_quiz",
    version: str = "0.1.80",
    scope: str = "quiz",
    status: str = "stable",
    task_types: list[str] | None = None,
    topic_keys: list[str] | None = None,
    implementation_binding: str = "create_quiz",
    source_proposal_id: str | None = None,
    source_reflection_ids: list[str] | None = None,
) -> SkillArtifact:
    return SkillArtifact.build(
        name=name,
        version=version,
        skill_type="learned",
        scope=scope,
        status=status,
        description=f"{name} skill package.",
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {
                "task_types": list(task_types or ["practice"]),
                "topic_keys": list(topic_keys or ["algebra"]),
            },
            "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
        },
        runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
        tool_plan=[],
        compatibility_contract={
            "surfaces": [scope],
            "implementation_binding": implementation_binding,
            "input_schema_version": "1.0",
            "output_schema_version": "1.0",
            "dynamic_execution": False,
        },
        source_reflection_ids=list(source_reflection_ids or ["reflection-source"]),
        source_memory_ids=["memory-source"],
        source_proposal_id=source_proposal_id,
        quality_score=0.8,
        created_by="operator",
        approved_by="operator" if status in {"active", "stable"} else None,
        approved_at=datetime.now(timezone.utc) if status in {"active", "stable"} else None,
    )


def _memory_conflict_set(
    *,
    learner_goal_id: str = "goal-1",
    topic_key: str = "algebra",
    severity_score: float = 0.8,
) -> MemoryConflictSet:
    return MemoryConflictSet.build(
        learner_profile_id="profile-1",
        learner_goal_id=learner_goal_id,
        topic_key=topic_key,
        conflict_type="contradictory_evidence",
        severity_score=severity_score,
        summary=f"Conflicting memory evidence for {topic_key}.",
        reason_code="contradictory_evidence",
        handling_result="operator_review_required",
        status_impact=ConflictStatusImpact.build(
            validation_status="conflict_open",
            recommended_use="review_before_use",
            governance_effect="curator_review",
            direct_status_change=False,
            severity_score=severity_score,
            handling_result="operator_review_required",
        ),
    )


def _reflection_outcome_evaluation(
    *,
    learner_goal_id: str = "goal-1",
    topic_key: str = "algebra",
    evaluation_status: str = "ineffective",
    improvement_score: float = -0.5,
) -> ReflectionOutcomeEvaluation:
    return ReflectionOutcomeEvaluation.build(
        reflection_record_id=f"reflection-outcome-{evaluation_status}-{topic_key}",
        learner_goal_id=learner_goal_id,
        topic_key=topic_key,
        window_size=3,
        baseline_snapshot={"topic_key": topic_key},
    ).with_result(
        evaluation_status=evaluation_status,
        observed_attempt_count=3,
        outcome_snapshot={"attempt_ids": ["attempt-1", "attempt-2", "attempt-3"]},
        improvement_score=improvement_score,
        evaluation_note=f"reflection outcome {evaluation_status}",
        evaluated=True,
    )


def _skill_artifact_lifecycle_service(
    artifact_repository: StubSkillArtifactRepository,
    proposal: ReflectionProposal | None,
    evaluation: ReflectionProposalEvaluation | None,
    audit_repository: StubAuditRepository,
    *,
    rollout: ReflectionProposalRollout | None = None,
    observation: ReflectionProposalRolloutObservation | None = None,
    observations: list[ReflectionProposalRolloutObservation] | None = None,
    binding: GoalSkillBinding | None = None,
    usage_events: list[SkillUsageEvent] | None = None,
    allowed_skills: list[str] | None = None,
) -> SkillArtifactLifecycleService:
    rollout_observations = observations if observations is not None else ([observation] if observation is not None else [])
    return SkillArtifactLifecycleService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        evaluation_repository=StubProposalEvaluationRepository(evaluation),
        rollout_repository=StubProposalRolloutRepository(rollout),
        rollout_observation_repository=StubProposalRolloutObservationRepository(rollout_observations),
        goal_skill_binding_repository=StubGoalSkillBindingRepository(binding),
        usage_repository=StubSkillUsageEventRepository(events=usage_events),
        skill_registry=SkillRegistry.from_allowed_skills(allowed_skills or ["create_quiz"]),
        audit_service=AuditService(audit_repository),
    )


def _skill_replacement_staging_service(
    artifact_repository: StubSkillArtifactRepository,
    proposal: ReflectionProposal,
    evaluation: ReflectionProposalEvaluation | None,
    audit_repository: StubAuditRepository,
) -> SkillReplacementStagingService:
    proposal_repository = StubProposalRepository(proposal)
    evaluation_repository = StubProposalEvaluationRepository(evaluation)
    audit_service = AuditService(audit_repository)
    return SkillReplacementStagingService(
        artifact_repository=artifact_repository,
        proposal_repository=proposal_repository,
        evaluation_repository=evaluation_repository,
        candidate_service=SkillCandidateService(
            artifact_repository=artifact_repository,
            proposal_repository=proposal_repository,
            evaluation_repository=evaluation_repository,
            audit_service=audit_service,
        ),
        lifecycle_service=SkillArtifactLifecycleService(
            artifact_repository=artifact_repository,
            proposal_repository=proposal_repository,
            evaluation_repository=evaluation_repository,
            rollout_repository=StubProposalRolloutRepository(),
            rollout_observation_repository=StubProposalRolloutObservationRepository(),
            goal_skill_binding_repository=StubGoalSkillBindingRepository(),
            usage_repository=StubSkillUsageEventRepository(),
            skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
            audit_service=audit_service,
        ),
        audit_service=audit_service,
    )


def _skill_curator_recommendation_service(
    *,
    recommendation_repository: StubSkillCuratorRecommendationRepository,
    artifact_repository: StubSkillArtifactRepository,
    lifecycle_service: StubSkillLifecycleForRecommendation,
    audit_repository: StubAuditRepository,
    proposal_service: StubSkillPatchProposalService | None = None,
) -> SkillCuratorRecommendationService:
    return SkillCuratorRecommendationService(
        recommendation_repository=recommendation_repository,
        artifact_repository=artifact_repository,
        lifecycle_service=lifecycle_service,
        audit_service=AuditService(audit_repository),
        proposal_service=proposal_service,
    )


def _skill_curator_job_service(
    *,
    artifact_repository: StubSkillArtifactRepository,
    recommendation_repository: StubSkillCuratorRecommendationRepository,
    lifecycle_service: StubSkillLifecycleForRecommendation,
    audit_repository: StubAuditRepository,
    rollout: ReflectionProposalRollout | None = None,
    observations: list[ReflectionProposalRolloutObservation] | None = None,
    decisions: list[ReflectionProposalRolloutDecision] | None = None,
    binding: GoalSkillBinding | None = None,
    usage_events: list[SkillUsageEvent] | None = None,
    memory_conflicts: list[MemoryConflictSet] | None = None,
    reflection_outcomes: list[ReflectionOutcomeEvaluation] | None = None,
    config: SkillCuratorJobConfig | None = None,
    proposal: ReflectionProposal | None = None,
) -> SkillCuratorJobService:
    recommendation_service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=artifact_repository,
        lifecycle_service=lifecycle_service,
        audit_repository=audit_repository,
    )
    return SkillCuratorJobService(
        artifact_repository=artifact_repository,
        usage_repository=StubSkillUsageEventRepository(events=usage_events),
        proposal_repository=StubProposalRepository(proposal),
        rollout_repository=StubProposalRolloutRepository(rollout),
        rollout_observation_repository=StubProposalRolloutObservationRepository(observations),
        rollout_decision_repository=StubProposalRolloutDecisionRepository(decisions),
        goal_skill_binding_repository=StubGoalSkillBindingRepository(binding),
        recommendation_repository=recommendation_repository,
        recommendation_service=recommendation_service,
        audit_service=AuditService(audit_repository),
        memory_conflict_repository=StubMemoryConflictRepository(memory_conflicts),
        reflection_outcome_evaluation_repository=StubReflectionOutcomeEvaluationRepository(reflection_outcomes),
        config=config,
    )


def _active_curator_artifact() -> SkillArtifact:
    staged = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Active quiz skill package.",
        source_reflection_ids=["reflection-1"],
        source_proposal_id="proposal-1",
    )
    return staged.mark_active(operator_id="operator")


def test_skill_curator_recommendation_entity_validates_action_mapping():
    artifact = _active_curator_artifact()
    staged_artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.2",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Governed staged replacement.",
        quality_score=0.8,
    )
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="promote_candidate",
        recommended_action="stabilize_active",
        reason_code="stable_evidence",
        created_by="curator",
    )
    assert recommendation.status == "pending"

    activate_recommendation = SkillCuratorRecommendation.build(
        artifact_id=staged_artifact.id,
        skill_name=staged_artifact.name,
        skill_version=staged_artifact.version,
        artifact_status=staged_artifact.status,
        lineage_id=staged_artifact.lineage_id,
        scope=staged_artifact.scope,
        surface=staged_artifact.scope,
        recommendation_type="activate_candidate",
        recommended_action="activate_staged",
        reason_code="activation_evidence_ready",
        created_by="curator",
    )
    assert activate_recommendation.status == "pending"

    with pytest.raises(ValidationError, match="promote_candidate"):
        SkillCuratorRecommendation.build(
            artifact_id=artifact.id,
            skill_name=artifact.name,
            scope=artifact.scope,
            surface=artifact.scope,
            recommendation_type="promote_candidate",
            recommended_action="none",
            reason_code="stable_evidence",
            created_by="curator",
        )

    with pytest.raises(ValidationError, match="activate_candidate"):
        SkillCuratorRecommendation.build(
            artifact_id=staged_artifact.id,
            skill_name=staged_artifact.name,
            scope=staged_artifact.scope,
            surface=staged_artifact.scope,
            recommendation_type="activate_candidate",
            recommended_action="none",
            reason_code="activation_evidence_ready",
            created_by="curator",
        )

    with pytest.raises(ValidationError, match="Executable"):
        SkillCuratorRecommendation.build(
            skill_name=artifact.name,
            scope=artifact.scope,
            surface=artifact.scope,
            recommendation_type="flag_for_review",
            recommended_action="suppress_selectable",
            reason_code="quality_regression",
            created_by="curator",
        )

    archive_recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="archive_candidate",
        recommended_action="archive_deprecated",
        reason_code="stale_deprecated",
        created_by="curator",
    )
    assert archive_recommendation.recommended_action == "archive_deprecated"

    with pytest.raises(ValidationError, match="archive_candidate"):
        SkillCuratorRecommendation.build(
            artifact_id=artifact.id,
            skill_name=artifact.name,
            scope=artifact.scope,
            surface=artifact.scope,
            recommendation_type="archive_candidate",
            recommended_action="deactivate_active",
            reason_code="stale_deprecated",
            created_by="curator",
        )

    with pytest.raises(ValidationError, match="archive_deprecated"):
        SkillCuratorRecommendation.build(
            artifact_id=artifact.id,
            skill_name=artifact.name,
            scope=artifact.scope,
            surface=artifact.scope,
            recommendation_type="flag_for_review",
            recommended_action="archive_deprecated",
            reason_code="stale_deprecated",
            created_by="curator",
        )


def test_skill_curator_recommendation_model_has_governance_indexes():
    indexes = {index.name: index for index in SkillCuratorRecommendationModel.__table__.indexes}

    assert "ix_skill_curator_recs_status_type_created" in indexes
    assert "ix_skill_curator_recs_artifact_status_created" in indexes
    assert "ix_skill_curator_recs_skill_scope_surface_status" in indexes


def test_skill_observability_assets_reference_expected_metrics():
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (repo_root / "ops/grafana/dashboards/agent-edu-overview.json").read_text()
    alerts = (repo_root / "ops/prometheus/alerts.yml").read_text()

    for metric_name in (
        "agent_edu_skill_usage_events_total",
        "agent_edu_skill_resolutions_total",
        "agent_edu_skill_artifacts",
        "agent_edu_skill_curator_pending_recommendations",
        "agent_edu_skill_curator_recommendations_total",
        "agent_edu_skill_curator_job_duration_seconds",
        "agent_edu_skill_rollout_auto_decisions_total",
    ):
        assert metric_name in dashboard
    for metric_name in (
        "agent_edu_skill_usage_events_total",
        "agent_edu_skill_curator_pending_recommendations",
        "agent_edu_skill_curator_recommendations_total",
        "agent_edu_skill_curator_job_duration_seconds",
        "agent_edu_skill_rollout_auto_decisions_total",
    ):
        assert metric_name in alerts
    for alert_name in (
        "SkillResolverFailureRateHigh",
        "SkillNegativeUsageRateHigh",
        "SkillCuratorPendingBacklogHigh",
        "SkillCoverageRegressionRecommendationRateHigh",
        "SkillCuratorJobSlow",
        "SkillRolloutAutoRollbackRateHigh",
        "SkillRolloutAutoDecisionSkipRateHigh",
    ):
        assert alert_name in alerts


async def test_skill_curator_recommendation_service_creates_artifact_snapshot_and_reuses_pending_duplicate():
    artifact = _active_curator_artifact()
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    audit_repository = StubAuditRepository()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=audit_repository,
    )

    first = await service.create_recommendation(
        artifact_id=artifact.id,
        recommendation_type="promote_candidate",
        recommended_action="stabilize_active",
        reason_code="stable_evidence",
        reason_note="Usage looks stable.",
        evidence_snapshot={"usage_event_ids": ["usage-1"]},
        metrics_snapshot={"success_count": 5},
        created_by="skill_curator",
    )
    second = await service.create_recommendation(
        artifact_id=artifact.id,
        recommendation_type="promote_candidate",
        recommended_action="stabilize_active",
        reason_code="stable_evidence",
        reason_note="Usage looks stable.",
        created_by="skill_curator",
    )

    assert first.id == second.id
    assert first.artifact_id == artifact.id
    assert first.skill_name == artifact.name
    assert first.skill_version == artifact.version
    assert first.artifact_status == artifact.status
    assert first.lineage_id == artifact.lineage_id
    assert first.scope == "quiz"
    assert first.surface == "quiz"
    assert first.evidence_snapshot == {"usage_event_ids": ["usage-1"]}
    assert first.metrics_snapshot == {"success_count": 5}
    assert len(recommendation_repository.recommendations) == 1
    assert [event.event_type for event in audit_repository.events] == [
        "skill.curator.recommendation.created",
        "skill.curator.recommendation.reused",
    ]


async def test_skill_curator_recommendation_accept_calls_lifecycle_before_marking_accepted():
    artifact = _active_curator_artifact()
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="promote_candidate",
        recommended_action="stabilize_active",
        reason_code="stable_evidence",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    audit_repository = StubAuditRepository()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=audit_repository,
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="stable_evidence",
        reason_note="Accept curator recommendation.",
    )

    assert accepted.status == "accepted"
    assert accepted.accepted_by == "operator"
    assert accepted.action_result == {
        "executed": True,
        "recommended_action": "stabilize_active",
        "artifact_id": artifact.id,
        "artifact_status": "stable",
        "skill_name": artifact.name,
        "skill_version": artifact.version,
        "scope": artifact.scope,
    }
    assert lifecycle_service.calls == [
        {
            "action": "stabilize_active",
            "artifact_id": artifact.id,
            "operator_id": "operator",
            "reason_code": "stable_evidence",
            "reason_note": "Accept curator recommendation.",
        }
    ]
    assert lifecycle_service.operations == ["lifecycle"]
    assert recommendation_repository.operations == ["update"]
    assert recommendation_repository.recommendations[0].status == "accepted"
    assert audit_repository.events[-1].event_type == "skill.curator.recommendation.accepted"

    reused = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="stable_evidence",
        reason_note="Repeat accept.",
    )
    assert reused.id == accepted.id
    assert len(lifecycle_service.calls) == 1
    assert audit_repository.events[-1].event_type == "skill.curator.recommendation.accept_reused"


@pytest.mark.parametrize(
    ("recommendation_type", "recommended_action"),
    [
        ("activate_candidate", "activate_staged"),
        ("replace_candidate", "replace_selectable"),
    ],
)
async def test_skill_curator_recommendation_accept_executes_replacement_readiness_actions(
    recommendation_type: str,
    recommended_action: str,
):
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.99",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Governed staged replacement.",
        quality_score=0.8,
    )
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type=recommendation_type,
        recommended_action=recommended_action,
        reason_code="replacement_evidence_ready" if recommendation_type == "replace_candidate" else "activation_evidence_ready",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="superseded" if recommended_action == "replace_selectable" else "operator_reviewed",
        reason_note="Execute governed staged replacement action.",
    )

    assert accepted.status == "accepted"
    assert accepted.action_result["executed"] is True
    assert accepted.action_result["recommended_action"] == recommended_action
    assert accepted.action_result["replacement_readiness"] is None
    assert lifecycle_service.calls == [
        {
            "action": recommended_action,
            "artifact_id": artifact.id,
            "operator_id": "operator",
            "reason_code": "superseded" if recommended_action == "replace_selectable" else "operator_reviewed",
            "reason_note": "Execute governed staged replacement action.",
        }
    ]


async def test_skill_curator_recommendation_accept_keeps_pending_when_lifecycle_fails():
    artifact = _active_curator_artifact()
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="promote_candidate",
        recommended_action="stabilize_active",
        reason_code="stable_evidence",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact, fail=True)
    audit_repository = StubAuditRepository()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=audit_repository,
    )

    with pytest.raises(ValidationError, match="stable evidence missing"):
        await service.accept_recommendation(
            recommendation_id=recommendation.id,
            operator_id="operator",
            reason_code="stable_evidence",
            reason_note=None,
        )

    assert recommendation_repository.recommendations[0].status == "pending"
    assert recommendation_repository.operations == []
    assert len(lifecycle_service.calls) == 1
    assert audit_repository.events[-1].event_type == "skill.curator.recommendation.accept_failed"


@pytest.mark.parametrize("recommended_action", ["archive_deprecated", "none"])
async def test_skill_curator_recommendation_accept_archives_deprecated_artifact(recommended_action: str):
    artifact = _active_curator_artifact().mark_deprecated(operator_id="operator")
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="archive_candidate",
        recommended_action=recommended_action,
        reason_code="stale_deprecated",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="stale_deprecated",
        reason_note="Archive stale deprecated artifact.",
    )

    assert accepted.status == "accepted"
    assert accepted.action_result == {
        "executed": True,
        "recommended_action": "archive_deprecated",
        "artifact_id": artifact.id,
        "artifact_status": "archived",
        "skill_name": artifact.name,
        "skill_version": artifact.version,
        "scope": artifact.scope,
    }
    assert lifecycle_service.calls == [
        {
            "action": "archive_deprecated",
            "artifact_id": artifact.id,
            "operator_id": "operator",
            "reason_code": "stale_deprecated",
            "reason_note": "Archive stale deprecated artifact.",
        }
    ]
    assert recommendation_repository.recommendations[0].status == "accepted"


async def test_skill_curator_recommendation_accept_archive_keeps_pending_when_lifecycle_fails():
    artifact = _active_curator_artifact().mark_deprecated(operator_id="operator")
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="archive_candidate",
        recommended_action="archive_deprecated",
        reason_code="stale_deprecated",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact, fail=True)
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
    )

    with pytest.raises(ValidationError, match="archive failed"):
        await service.accept_recommendation(
            recommendation_id=recommendation.id,
            operator_id="operator",
            reason_code="stale_deprecated",
            reason_note=None,
        )

    assert recommendation_repository.recommendations[0].status == "pending"
    assert recommendation_repository.operations == []
    assert len(lifecycle_service.calls) == 1


async def test_skill_curator_recommendation_accept_merge_candidate_creates_skill_merge_proposal():
    artifact = _active_curator_artifact()
    related_artifact = SkillArtifact.build(
        name=artifact.name,
        version="0.1.2",
        skill_type="learned",
        scope=artifact.scope,
        status="stable",
        description="Related quiz skill package.",
    )
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="merge_candidate",
        recommended_action="none",
        reason_code="merge_candidate",
        reason_note="Overlapping package coverage.",
        evidence_snapshot={
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
            "overlap_reason": "duplicate topic coverage",
        },
        metrics_snapshot={"overlap_score": 0.8},
        related_artifact_ids=[related_artifact.id],
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation()
    proposal_service = StubSkillPatchProposalService()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note=None,
    )

    assert accepted.status == "accepted"
    assert accepted.action_result == {
        "executed": True,
        "recommended_action": "create_skill_merge_proposal",
        "proposal_id": proposal_service.proposals[0].id,
        "proposal_type": "skill_package",
        "proposal_status": "proposed",
        "artifact_id": artifact.id,
        "skill_name": artifact.name,
        "skill_version": artifact.version,
        "scope": artifact.scope,
        "merge_source_artifact_ids": [related_artifact.id],
    }
    assert proposal_service.created == [
        {
            "recommendation_id": recommendation.id,
            "artifact_id": artifact.id,
            "skill_name": artifact.name,
            "skill_version": artifact.version,
            "scope": artifact.scope,
            "surface": artifact.scope,
            "recommendation_reason_code": "merge_candidate",
            "evidence_snapshot": {
                "learner_goal_id": "goal-1",
                "reflection_record_id": "reflection-1",
                "overlap_reason": "duplicate topic coverage",
            },
            "metrics_snapshot": {"overlap_score": 0.8},
            "related_artifact_ids": [related_artifact.id],
            "reflection_record_id": "reflection-1",
            "learner_goal_id": "goal-1",
            "operator_id": "operator",
        }
    ]
    assert lifecycle_service.calls == []

    reused = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Repeat.",
    )
    assert reused.id == accepted.id
    assert len(proposal_service.created) == 1


async def test_skill_curator_recommendation_accept_patch_needed_creates_skill_patch_proposal_from_evidence_anchor():
    artifact = _active_curator_artifact()
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="patch_needed",
        recommended_action="none",
        reason_code="quality_regression",
        reason_note="Negative usage increased.",
        evidence_snapshot={
            "learner_goal_id": "goal-1",
            "reflection_record_id": "reflection-1",
            "usage_event_ids": ["usage-1", "usage-2"],
        },
        metrics_snapshot={"negative_usage_rate": 0.5},
        related_artifact_ids=["artifact-related"],
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    proposal_service = StubSkillPatchProposalService()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Create governed patch request.",
    )

    assert accepted.status == "accepted"
    assert accepted.action_result == {
        "executed": True,
        "recommended_action": "create_skill_patch_proposal",
        "proposal_id": proposal_service.proposals[0].id,
        "proposal_type": "skill_patch_request",
        "proposal_status": "proposed",
        "artifact_id": artifact.id,
        "skill_name": artifact.name,
        "skill_version": artifact.version,
        "scope": artifact.scope,
    }
    assert proposal_service.created == [
        {
            "recommendation_id": recommendation.id,
            "artifact_id": artifact.id,
            "skill_name": artifact.name,
            "skill_version": artifact.version,
            "scope": artifact.scope,
            "surface": artifact.scope,
            "recommendation_reason_code": "quality_regression",
            "evidence_snapshot": {
                "learner_goal_id": "goal-1",
                "reflection_record_id": "reflection-1",
                "usage_event_ids": ["usage-1", "usage-2"],
            },
            "metrics_snapshot": {"negative_usage_rate": 0.5},
            "related_artifact_ids": ["artifact-related"],
            "reflection_record_id": "reflection-1",
            "learner_goal_id": "goal-1",
            "operator_id": "operator",
        }
    ]
    assert lifecycle_service.calls == []
    assert recommendation_repository.operations == ["update"]

    reused = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Repeat accept.",
    )
    assert reused.id == accepted.id
    assert len(proposal_service.created) == 1


async def test_skill_curator_recommendation_accept_patch_needed_uses_source_proposal_anchor_fallback():
    source_proposal = ReflectionProposal.build(
        reflection_record_id="reflection-from-source",
        learner_goal_id="goal-from-source",
        proposal_type="skill_package",
        target_scope="quiz",
        priority_score=0.8,
        hypothesis="Seed package.",
        change_summary="Seed skill package.",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "bundle_id": "bundle-1",
            "surface": "quiz",
            "match_rules": {"required_root_causes": ["knowledge_gap"]},
            "runtime_directives": {"feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
        expected_improvement="Improve quiz remediation.",
        risk_level="low",
        evidence_snapshot={},
    )
    artifact = replace(_active_curator_artifact(), source_proposal_id=source_proposal.id, source_reflection_ids=[])
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="patch_needed",
        recommended_action="none",
        reason_code="quality_regression",
        evidence_snapshot={"usage_event_ids": ["usage-1"]},
        created_by="skill_curator",
    )
    proposal_service = StubSkillPatchProposalService(source_proposal=source_proposal)
    service = _skill_curator_recommendation_service(
        recommendation_repository=StubSkillCuratorRecommendationRepository([recommendation]),
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    accepted = await service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note=None,
    )

    assert accepted.status == "accepted"
    assert proposal_service.created[0]["learner_goal_id"] == "goal-from-source"
    assert proposal_service.created[0]["reflection_record_id"] == "reflection-from-source"


async def test_skill_curator_recommendation_accept_patch_needed_requires_anchor_and_keeps_pending():
    artifact = _active_curator_artifact()
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="patch_needed",
        recommended_action="none",
        reason_code="quality_regression",
        evidence_snapshot={"usage_event_ids": ["usage-1"]},
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    proposal_service = StubSkillPatchProposalService()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    with pytest.raises(ValidationError, match="learner_goal_id and reflection_record_id"):
        await service.accept_recommendation(
            recommendation_id=recommendation.id,
            operator_id="operator",
            reason_code="operator_reviewed",
            reason_note=None,
        )

    assert recommendation_repository.recommendations[0].status == "pending"
    assert recommendation_repository.operations == []
    assert proposal_service.created == []


async def test_skill_curator_recommendation_accept_patch_needed_keeps_pending_when_proposal_creation_fails():
    recommendation = SkillCuratorRecommendation.build(
        skill_name="create_quiz",
        scope="quiz",
        surface="quiz",
        recommendation_type="patch_needed",
        recommended_action="none",
        reason_code="quality_regression",
        evidence_snapshot={"learner_goal_id": "goal-1", "reflection_record_id": "reflection-1"},
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    proposal_service = StubSkillPatchProposalService(fail=True)
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(),
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    with pytest.raises(ValidationError, match="proposal creation failed"):
        await service.accept_recommendation(
            recommendation_id=recommendation.id,
            operator_id="operator",
            reason_code="operator_reviewed",
            reason_note=None,
        )

    assert recommendation_repository.recommendations[0].status == "pending"
    assert recommendation_repository.operations == []
    assert len(proposal_service.created) == 0


async def test_skill_curator_recommendation_dismiss_is_idempotent_and_blocks_accepted_items():
    recommendation = SkillCuratorRecommendation.build(
        skill_name="create_quiz",
        scope="quiz",
        surface="quiz",
        recommendation_type="flag_for_review",
        recommended_action="none",
        reason_code="manual_review",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    audit_repository = StubAuditRepository()
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(),
        audit_repository=audit_repository,
    )

    dismissed = await service.dismiss_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="false_positive",
        reason_note="No action needed.",
    )
    repeated = await service.dismiss_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="false_positive",
        reason_note="Repeat dismiss.",
    )

    assert dismissed.status == "dismissed"
    assert repeated.id == dismissed.id
    assert audit_repository.events[-1].event_type == "skill.curator.recommendation.dismiss_reused"

    accepted = recommendation.accept(
        operator_id="operator",
        reason_code="accepted",
        reason_note=None,
        action_result={"executed": False},
    )
    service = _skill_curator_recommendation_service(
        recommendation_repository=StubSkillCuratorRecommendationRepository([accepted]),
        artifact_repository=StubSkillArtifactRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(),
        audit_repository=StubAuditRepository(),
    )
    with pytest.raises(ValidationError, match="pending"):
        await service.dismiss_recommendation(
            recommendation_id=accepted.id,
            operator_id="operator",
            reason_code="false_positive",
            reason_note=None,
        )


async def test_skill_curator_recommendation_accept_reuses_lifecycle_reason_code_allowlists():
    artifact = _active_curator_artifact()
    recommendation = SkillCuratorRecommendation.build(
        artifact_id=artifact.id,
        skill_name=artifact.name,
        skill_version=artifact.version,
        artifact_status=artifact.status,
        lineage_id=artifact.lineage_id,
        scope=artifact.scope,
        surface=artifact.scope,
        recommendation_type="flag_for_review",
        recommended_action="suppress_selectable",
        reason_code="quality_regression",
        created_by="skill_curator",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([recommendation])
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
    )

    with pytest.raises(ValidationError, match="Unsupported reason_code"):
        await service.accept_recommendation(
            recommendation_id=recommendation.id,
            operator_id="operator",
            reason_code="freeform_reason",
            reason_note=None,
        )

    assert recommendation_repository.recommendations[0].status == "pending"
    assert lifecycle_service.calls == []


async def test_skill_curator_job_recommends_promote_from_stable_usage_and_observations():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact = replace(await _staged_artifact_from_proposal(proposal, evaluation), status="active")
    artifact = replace(artifact, approved_by="operator", approved_at=artifact.updated_at)
    rollout, binding, _, _ = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=artifact,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observations[0].id)
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        observations=observations,
        binding=binding,
        usage_events=usage_events,
    )

    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert result.scanned_count == 1
    assert result.created_count == 1
    assert lifecycle_service.calls == []
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "promote_candidate"
    assert recommendation.recommended_action == "stabilize_active"
    assert recommendation.reason_code == "stable_evidence"
    assert recommendation.metrics_snapshot["successful_count"] == 5
    assert recommendation.metrics_snapshot["promote_observation_count"] == 2
    assert recommendation.evidence_snapshot["rollout_id"] == rollout.id


async def test_skill_curator_job_skips_promote_when_evidence_is_not_enough():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact = replace(await _staged_artifact_from_proposal(proposal, evaluation), status="active")
    artifact = replace(artifact, approved_by="operator", approved_at=artifact.updated_at)
    rollout, binding, _, _ = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=artifact,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observations[0].id)
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        observations=observations[:1],
        binding=binding,
        usage_events=usage_events[:4],
    )

    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert result.created_count == 0


async def test_skill_curator_job_flags_negative_usage_without_lifecycle_side_effect():
    artifact = _active_curator_artifact()
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                surface=artifact.scope,
                outcome_status="failed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=lifecycle_service,
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    assert lifecycle_service.calls == []
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "flag_for_review"
    assert recommendation.recommended_action == "none"
    assert recommendation.reason_code == "quality_regression"
    assert recommendation.metrics_snapshot["negative_count"] == 3
    assert recommendation.metrics_snapshot["negative_usage_rate"] == 1.0


async def test_skill_curator_job_flags_high_severity_memory_conflict_without_lifecycle_side_effect():
    proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=proposal.id,
        topic_keys=["algebra"],
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    conflict = _memory_conflict_set(
        learner_goal_id=proposal.learner_goal_id,
        topic_key="algebra",
        severity_score=0.8,
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    lifecycle_service = StubSkillLifecycleForRecommendation(artifact)
    audit_repository = StubAuditRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=lifecycle_service,
        audit_repository=audit_repository,
        rollout=rollout,
        binding=binding,
        memory_conflicts=[conflict],
    )
    now = artifact.updated_at + timedelta(days=1)

    first = await service.run_once(now=now)
    second = await service.run_once(now=now)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert lifecycle_service.calls == []
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "patch_skill_package"
    assert recommendation.recommended_action == "none"
    assert recommendation.reason_code == "memory_retrieval_conflict"
    governance_evidence = recommendation.evidence_snapshot["governance_evidence"]
    assert governance_evidence["memory_conflicts"]["conflict_set_ids"] == [conflict.id]
    assert governance_evidence["memory_conflicts"]["high_severity_count"] == 1
    assert recommendation.metrics_snapshot["governance_memory_conflict_high_severity_count"] == 1

    review_service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=StubSkillArtifactRepository(artifact),
        lifecycle_service=lifecycle_service,
        audit_repository=audit_repository,
        proposal_service=StubSkillPatchProposalService(source_proposal=proposal),
    )
    accepted = await review_service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Reviewed governance evidence.",
    )
    assert accepted.status == "accepted"
    assert accepted.action_result["executed"] is True
    assert accepted.action_result["recommended_action"] == "create_skill_patch_proposal"
    assert lifecycle_service.calls == []


async def test_skill_curator_job_skips_low_severity_memory_conflict():
    proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=proposal.id,
        topic_keys=["algebra"],
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        binding=binding,
        memory_conflicts=[
            _memory_conflict_set(
                learner_goal_id=proposal.learner_goal_id,
                topic_key="algebra",
                severity_score=0.4,
            )
        ],
    )

    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert result.created_count == 0


async def test_skill_curator_job_flags_reflection_outcome_regression():
    proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=proposal.id,
        topic_keys=["algebra"],
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    ineffective = _reflection_outcome_evaluation(
        learner_goal_id=proposal.learner_goal_id,
        topic_key="algebra",
        evaluation_status="ineffective",
        improvement_score=-0.5,
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        binding=binding,
        reflection_outcomes=[ineffective],
    )

    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.reason_code == "governance_evidence_regression"
    reflection_evidence = recommendation.evidence_snapshot["governance_evidence"]["reflection_outcomes"]
    assert reflection_evidence["ineffective_evaluation_ids"] == [ineffective.id]
    assert recommendation.metrics_snapshot["governance_reflection_ineffective_count"] == 1


async def test_skill_curator_job_requires_inconclusive_reflection_threshold():
    proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=proposal.id,
        topic_keys=["algebra"],
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    one_inconclusive = _reflection_outcome_evaluation(
        learner_goal_id=proposal.learner_goal_id,
        topic_key="algebra",
        evaluation_status="inconclusive",
        improvement_score=0.0,
    )
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        binding=binding,
        reflection_outcomes=[one_inconclusive],
    )
    skipped = await service.run_once(now=artifact.updated_at + timedelta(days=1))
    assert skipped.created_count == 0

    two_inconclusive = replace(
        _reflection_outcome_evaluation(
            learner_goal_id=proposal.learner_goal_id,
            topic_key="algebra",
            evaluation_status="inconclusive",
            improvement_score=0.0,
        ),
        reflection_record_id="reflection-outcome-inconclusive-algebra-2",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        binding=binding,
        reflection_outcomes=[one_inconclusive, two_inconclusive],
    )

    created = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert created.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.metrics_snapshot["governance_reflection_inconclusive_count"] == 2
    assert recommendation.evidence_snapshot["governance_evidence"]["reflection_outcomes"][
        "inconclusive_evaluation_ids"
    ] == [one_inconclusive.id, two_inconclusive.id]


async def test_skill_curator_job_attaches_governance_evidence_to_quality_regression():
    artifact = _overlap_skill_artifact(status="stable", topic_keys=["algebra"])
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                learner_goal_id="goal-1",
                surface=artifact.scope,
                outcome_status="failed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    conflict = _memory_conflict_set(learner_goal_id="goal-1", topic_key="algebra", severity_score=0.8)
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
        memory_conflicts=[conflict],
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "patch_skill_package"
    assert recommendation.reason_code == "memory_retrieval_conflict"
    assert recommendation.evidence_snapshot["governance_evidence"]["memory_conflicts"]["conflict_set_ids"] == [
        conflict.id
    ]
    assert recommendation.metrics_snapshot["governance_memory_conflict_high_severity_count"] == 1


async def test_skill_curator_job_flags_tool_plan_sequence_regression() -> None:
    proposal, _evaluation = _approved_skill_package_proposal(
        target_scope="replan",
        structured_patch_payload={
            "artifact_kind": "declarative_skill_package",
            "skill_name": "plan_study_path",
            "bundle_id": "bundle-replan-1",
            "surface": "replan",
            "match_rules": {"topic_keys": ["algebra"]},
            "runtime_directives": {"replan_bias": "normal"},
            "tool_plan": [
                {"step_id": "repair", "tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}},
                {
                    "step_id": "followup_review",
                    "tool_name": "review_scheduling",
                    "payload_template": {"source_task_id": "$steps.repair.created_task_ids[0]"},
                },
            ],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        },
    )
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=proposal.id,
        topic_keys=["algebra"],
    )
    artifact = replace(
        artifact,
        name="plan_study_path",
        scope="replan",
        tool_plan=[dict(item) for item in proposal.structured_patch_payload["tool_plan"]],
        runtime_directives={"replan_bias": "normal"},
        definition={
            **artifact.definition,
            "match_rules": {"topic_keys": ["algebra"]},
        },
    )
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                learner_goal_id="goal-1",
                surface=artifact.scope,
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
                metadata={
                    "tool_plan_sequence": ["partial_replan"],
                    "tool_plan_step_count": 1,
                    "skill_package_rollout": {
                        "proposal_id": proposal.id,
                        "rollout_id": "rollout-1",
                        "binding_id": "binding-1",
                        "skill_name": artifact.name,
                        "surface": artifact.scope,
                    },
                },
            ),
            created_at=now - timedelta(hours=1),
        )
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "patch_template_policy"
    assert recommendation.reason_code == "template_sequence_mismatch"
    sequence_evidence = recommendation.evidence_snapshot["governance_evidence"]["tool_plan_sequence"]
    assert sequence_evidence["sequence_mismatch_count"] == 1
    assert sequence_evidence["step_count_mismatch_count"] == 1
    assert recommendation.metrics_snapshot["governance_tool_plan_sequence_mismatch_count"] == 1


async def test_skill_curator_job_recommends_rollback_review_until_decision_exists():
    proposal, evaluation = _approved_skill_package_proposal()
    artifact = replace(await _staged_artifact_from_proposal(proposal, evaluation), status="active")
    artifact = replace(artifact, approved_by="operator", approved_at=artifact.updated_at)
    rollout, binding, _, _ = _activation_rollout_bundle(proposal)
    observation = _stable_rollout_observation(
        proposal=proposal,
        rollout=rollout,
        recommendation="rollback",
        created_at=artifact.updated_at + timedelta(minutes=5),
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation.id)
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        observations=[observation],
        binding=binding,
    )

    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))

    assert result.created_count == 1
    assert recommendation_repository.recommendations[0].recommendation_type == "rollback_review"
    decision = ReflectionProposalRolloutDecision.build(
        rollout_id=rollout.id,
        proposal_id=proposal.id,
        decision_type="rollback",
        previous_status="rolled_out",
        new_status="rolled_back",
        reason_code="operator_rollback",
        reason_note=None,
        operator_id="operator",
    )
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        rollout=rollout,
        observations=[observation],
        decisions=[replace(decision, created_at=observation.created_at + timedelta(minutes=1))],
        binding=binding,
    )
    result = await service.run_once(now=artifact.updated_at + timedelta(days=1))
    assert result.created_count == 0


async def test_skill_curator_job_recommends_archive_for_stale_deprecated_artifact():
    artifact = _active_curator_artifact().mark_deprecated(operator_id="operator")
    stale_at = artifact.updated_at - timedelta(days=31)
    artifact = replace(artifact, deprecated_at=stale_at, updated_at=stale_at)
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=[],
    )

    result = await service.run_once(now=stale_at + timedelta(days=31))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "archive_candidate"
    assert recommendation.recommended_action == "archive_deprecated"
    assert recommendation.reason_code == "stale_deprecated"


async def test_skill_curator_job_dedupes_same_window_after_dismiss():
    artifact = _active_curator_artifact()
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                surface=artifact.scope,
                outcome_status="failed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )
    first = await service.run_once(now=now)
    recommendation_repository.recommendations[0] = recommendation_repository.recommendations[0].dismiss(
        operator_id="operator",
        reason_code="false_positive",
        reason_note=None,
    )
    second = await service.run_once(now=now)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert len(recommendation_repository.recommendations) == 1


async def test_skill_curator_job_recommends_patch_needed_for_coverage_regression():
    source_proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=source_proposal.id,
        topic_keys=["algebra"],
    )
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                learner_goal_id="goal-coverage",
                surface=artifact.scope,
                topic_key="geometry",
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "patch_needed"
    assert recommendation.recommended_action == "none"
    assert recommendation.reason_code == "coverage_regression"
    assert recommendation.evidence_snapshot["learner_goal_id"] == "goal-coverage"
    coverage = recommendation.evidence_snapshot["coverage_regression"]
    assert coverage["declared_topic_keys"] == ["algebra"]
    assert coverage["drift_topic_keys"] == ["geometry"]
    assert coverage["hole_topic_keys"] == ["geometry"]
    assert coverage["uncovered_topic_keys"] == ["geometry"]
    assert coverage["topic_counts"]["geometry"] == {
        "attributed_count": 3,
        "binding_gap_count": 3,
        "unresolved_count": 0,
    }
    assert coverage["binding_gap_event_ids_by_topic"]["geometry"] == [item.id for item in usage_events]
    assert recommendation.metrics_snapshot["coverage_drift_topic_count"] == 1
    assert recommendation.metrics_snapshot["coverage_hole_topic_count"] == 1
    assert recommendation.metrics_snapshot["coverage_binding_gap_count"] == 3


async def test_skill_curator_job_skips_coverage_regression_without_attributed_outside_declared_usage():
    artifact = _overlap_skill_artifact(status="stable", topic_keys=["algebra"])
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=None,
                skill_name=artifact.name,
                skill_version=None,
                learner_goal_id="goal-coverage",
                surface=artifact.scope,
                topic_key="geometry",
                outcome_status="failed",
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 0


async def test_skill_curator_job_skips_coverage_regression_without_declared_topic_keys():
    artifact = replace(
        _overlap_skill_artifact(status="stable"),
        definition={
            "artifact_kind": "declarative_skill_package",
            "match_rules": {"task_types": ["practice"], "topic_keys": []},
            "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
        },
    )
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                surface=artifact.scope,
                topic_key="geometry",
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=1),
        )
    ]
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=StubSkillCuratorRecommendationRepository(),
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 0


async def test_skill_curator_job_reuses_pending_coverage_regression_duplicate():
    artifact = _overlap_skill_artifact(status="stable", topic_keys=["algebra"])
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                surface=artifact.scope,
                topic_key="geometry",
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=StubSkillArtifactRepository(artifact),
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    first = await service.run_once(now=now)
    second = await service.run_once(now=now)

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.existing_count == 1
    assert len(recommendation_repository.recommendations) == 1


async def test_skill_curator_job_ignores_sibling_coverage_for_coverage_regression():
    source_proposal, _evaluation = _approved_skill_package_proposal()
    source = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=source_proposal.id,
        topic_keys=["algebra"],
        task_types=["practice"],
    )
    sibling = _overlap_skill_artifact(
        version="0.1.81",
        status="candidate",
        topic_keys=["geometry"],
        task_types=["review"],
    )
    now = source.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=source.id,
                skill_name=source.name,
                skill_version=source.version,
                skill_status_at_use=source.status,
                learner_goal_id="goal-coverage",
                surface=source.scope,
                topic_key="geometry",
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, sibling]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.reason_code == "coverage_regression"
    assert recommendation.evidence_snapshot["coverage_regression"]["uncovered_topic_keys"] == ["geometry"]


async def test_skill_curator_coverage_recommendation_accepts_to_patch_proposal():
    source_proposal, _evaluation = _approved_skill_package_proposal()
    artifact = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=source_proposal.id,
        source_reflection_ids=[],
        topic_keys=["algebra"],
    )
    now = artifact.updated_at + timedelta(days=1)
    usage_events = [
        replace(
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id,
                skill_name=artifact.name,
                skill_version=artifact.version,
                skill_status_at_use=artifact.status,
                learner_goal_id=source_proposal.learner_goal_id,
                surface=artifact.scope,
                topic_key="geometry",
                outcome_status="completed",
                resolver_status="resolved",
                selection_reason="production_default",
            ),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    artifact_repository = StubSkillArtifactRepository(artifact)
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        usage_events=usage_events,
    )

    result = await service.run_once(now=now)

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    proposal_service = StubSkillPatchProposalService(source_proposal=source_proposal)
    review_service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=artifact_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(artifact),
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    accepted = await review_service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Create governed patch request.",
    )

    assert accepted.status == "accepted"
    assert accepted.action_result["recommended_action"] == "create_skill_patch_proposal"
    assert proposal_service.created[0]["recommendation_reason_code"] == "coverage_regression"
    assert proposal_service.created[0]["artifact_id"] == artifact.id


async def test_skill_curator_job_recommends_merge_candidate_for_overlapping_artifacts():
    source = _overlap_skill_artifact(
        status="stable",
        task_types=["practice", "review"],
        topic_keys=["algebra", "linear-systems"],
    )
    same_name_related = _overlap_skill_artifact(
        version="0.1.81",
        status="deprecated",
        task_types=["practice"],
        topic_keys=["geometry"],
    )
    same_binding_related = _overlap_skill_artifact(
        name="quiz_practice_variant",
        version="0.1.82",
        status="candidate",
        task_types=["assessment"],
        topic_keys=["linear-systems"],
        implementation_binding="create_quiz",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, same_name_related, same_binding_related]
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
    )

    result = await service.run_once(now=source.updated_at + timedelta(days=1))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "merge_candidate"
    assert recommendation.recommended_action == "none"
    assert recommendation.reason_code == "merge_candidate"
    assert recommendation.related_artifact_ids == [same_name_related.id, same_binding_related.id]
    assert recommendation.evidence_snapshot["source_artifact_id"] == source.id
    assert recommendation.evidence_snapshot["related_artifact_ids"] == [
        same_name_related.id,
        same_binding_related.id,
    ]
    assert recommendation.evidence_snapshot["overlap_match_rules"] == {
        "task_types": ["practice"],
        "topic_keys": ["linear-systems"],
    }
    assert recommendation.evidence_snapshot["related_overlap_match_rules"] == {
        same_name_related.id: {"task_types": ["practice"]},
        same_binding_related.id: {"topic_keys": ["linear-systems"]},
    }
    assert recommendation.evidence_snapshot["related_artifact_statuses"] == {
        same_name_related.id: "deprecated",
        same_binding_related.id: "candidate",
    }
    assert recommendation.metrics_snapshot["overlap_shared_value_count"] == 2
    assert recommendation.metrics_snapshot["related_artifact_count"] == 2


async def test_skill_curator_job_skips_merge_candidate_without_overlap():
    source = _overlap_skill_artifact(
        status="stable",
        task_types=["practice"],
        topic_keys=["algebra"],
    )
    related = _overlap_skill_artifact(
        version="0.1.81",
        status="deprecated",
        task_types=["review"],
        topic_keys=["geometry"],
    )
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, related]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
    )

    result = await service.run_once(now=source.updated_at + timedelta(days=1))

    assert result.created_count == 0
    assert recommendation_repository.recommendations == []


async def test_skill_curator_job_filters_disallowed_merge_related_statuses():
    source = _overlap_skill_artifact(status="stable")
    valid_related = _overlap_skill_artifact(version="0.1.81", status="staged")
    suppressed = _overlap_skill_artifact(version="0.1.82", status="suppressed")
    archived = _overlap_skill_artifact(version="0.1.83", status="archived")
    rejected = _overlap_skill_artifact(version="0.1.84", status="rejected")
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, valid_related, suppressed, archived, rejected]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
    )

    result = await service.run_once(now=source.updated_at + timedelta(days=1))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.related_artifact_ids == [valid_related.id]
    assert recommendation.evidence_snapshot["related_artifact_ids"] == [valid_related.id]
    assert set(recommendation.evidence_snapshot["related_artifacts"]) == {valid_related.id}


async def test_skill_curator_job_reuses_pending_merge_candidate_duplicate():
    source = _overlap_skill_artifact(status="stable")
    related = _overlap_skill_artifact(version="0.1.81", status="deprecated")
    existing = SkillCuratorRecommendation.build(
        artifact_id=source.id,
        skill_name=source.name,
        skill_version=source.version,
        artifact_status=source.status,
        lineage_id=source.lineage_id,
        scope=source.scope,
        surface=source.scope,
        recommendation_type="merge_candidate",
        recommended_action="none",
        reason_code="merge_candidate",
        related_artifact_ids=[related.id],
        created_by="skill_curator_job",
    )
    recommendation_repository = StubSkillCuratorRecommendationRepository([existing])
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, related]
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
    )

    result = await service.run_once(now=source.updated_at + timedelta(days=1))

    assert result.created_count == 0
    assert result.existing_count == 1
    assert recommendation_repository.recommendations == [existing]


async def test_skill_curator_job_recommends_replace_candidate_for_ready_governed_staged_replacement():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    observation_2 = _stable_rollout_observation(
        proposal=proposal,
        rollout=rollout,
        recommendation="promote",
        created_at=rollout.activated_at + timedelta(minutes=2),
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation_2.id)
    usage_events = [
        replace(usage_event, id=f"usage-curator-{index}", created_at=rollout.activated_at + timedelta(minutes=index + 1))
        for index in range(3)
    ]
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [staged, source_artifact]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(staged),
        audit_repository=StubAuditRepository(),
        proposal=proposal,
        rollout=rollout,
        observations=[observation, observation_2],
        binding=binding,
        usage_events=usage_events,
        config=SkillCuratorJobConfig(merge_overlap_min_shared_values=99),
    )

    result = await service.run_once(now=rollout.activated_at + timedelta(days=1))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    assert recommendation.recommendation_type == "replace_candidate"
    assert recommendation.recommended_action == "replace_selectable"
    assert recommendation.reason_code == "replacement_evidence_ready"
    assert recommendation.evidence_snapshot["ready_action"] == "replace_selectable"
    assert recommendation.evidence_snapshot["source_anchor"]["source_artifact_id"] == source_artifact.id
    assert recommendation.metrics_snapshot["replacement_successful_usage_count"] == 3
    assert recommendation_repository.operations == ["create"]


async def test_skill_curator_overlap_recommendation_accepts_to_merge_proposal_and_staged_replacement():
    source_proposal, _source_evaluation = _approved_skill_package_proposal()
    source = _overlap_skill_artifact(
        status="stable",
        source_proposal_id=source_proposal.id,
        source_reflection_ids=[],
        task_types=["practice"],
        topic_keys=["algebra"],
    )
    related = _overlap_skill_artifact(
        version="0.1.81",
        status="deprecated",
        task_types=["review", "practice"],
        topic_keys=["algebra", "linear-systems"],
    )
    artifact_repository = StubSkillArtifactRepository()
    artifact_repository.artifacts = [source, related]
    recommendation_repository = StubSkillCuratorRecommendationRepository()
    service = _skill_curator_job_service(
        artifact_repository=artifact_repository,
        recommendation_repository=recommendation_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
    )

    result = await service.run_once(now=source.updated_at + timedelta(days=1))

    assert result.created_count == 1
    recommendation = recommendation_repository.recommendations[0]
    proposal_repository = StubProposalRepository(source_proposal)
    proposal_service = ReflectionProposalService(
        repository=proposal_repository,
        approval_decision_repository=None,
        evaluation_repository=StubProposalEvaluationRepository(),
        artifact_repository=artifact_repository,
        autonomy_job_service=None,
        audit_service=AuditService(StubAuditRepository()),
    )
    recommendation_service = _skill_curator_recommendation_service(
        recommendation_repository=recommendation_repository,
        artifact_repository=artifact_repository,
        lifecycle_service=StubSkillLifecycleForRecommendation(source),
        audit_repository=StubAuditRepository(),
        proposal_service=proposal_service,
    )

    accepted = await recommendation_service.accept_recommendation(
        recommendation_id=recommendation.id,
        operator_id="operator",
        reason_code="operator_reviewed",
        reason_note="Create governed merge proposal.",
    )

    assert accepted.status == "accepted"
    assert accepted.action_result["recommended_action"] == "create_skill_merge_proposal"
    merge_proposal = proposal_repository.proposals[-1]
    assert merge_proposal.proposal_type == "skill_package"
    assert merge_proposal.evidence_snapshot["source"] == "skill_curator_merge_recommendation"
    assert merge_proposal.evidence_snapshot["source_artifact_id"] == source.id
    assert merge_proposal.evidence_snapshot["merge_source_artifact_ids"] == [related.id]
    assert merge_proposal.structured_patch_payload["match_rules"] == {
        "task_types": ["practice", "review"],
        "topic_keys": ["algebra", "linear-systems"],
    }

    approved_merge = merge_proposal.enqueue_sandbox(
        sandbox_run_id="sandbox-merge-1",
    ).start_sandbox(
        sandbox_run_id="sandbox-merge-1",
    ).complete_sandbox(
        sandbox_run_id="sandbox-merge-1",
        evaluation_status="effective",
        evaluation_summary="sandbox:0.20",
    ).approve(
        operator_id="operator",
        reason_code="validated",
        reason_note=None,
    )
    evaluation = ReflectionProposalEvaluation.build(
        proposal_id=approved_merge.id,
        comparison_window_size=3,
        baseline_policy_snapshot={"source_artifact_id": source.id},
        candidate_policy_snapshot=approved_merge.structured_patch_payload,
        evaluator_type="rule",
        sandbox_run_id="sandbox-merge-1",
    ).with_result(
        evaluation_status="effective",
        simulated_outcome_summary={"score_delta": 0.2},
        score_delta=0.2,
        sandbox_run_id="sandbox-merge-1",
    )
    staging_audit_repository = StubAuditRepository()
    staging_service = _skill_replacement_staging_service(
        artifact_repository,
        approved_merge,
        evaluation,
        staging_audit_repository,
    )
    staged = await staging_service.stage_replacement_from_proposal(
        proposal_id=approved_merge.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Stage governed merge replacement.",
    )

    assert staged.status == "staged"
    assert staged.lineage_id == source.lineage_id
    assert staged.parent_artifact_id == source.id
    assert staged.supersedes_artifact_id == source.id
    assert artifact_repository.artifacts[0].status == "stable"
    assert staging_audit_repository.events[-1].event_data["proposal_source"] == "skill_curator_merge_recommendation"


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

    proposal, evaluation = _approved_skill_package_proposal()
    proposal = replace_payload(
        proposal,
        {
            "surface": "review_scheduling",
            "tool_plan": [{"tool_name": "review_scheduling", "payload_template": {"source_task_id": "$learner_goal_id"}}],
        },
    )
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


async def test_skill_replacement_staging_service_stages_realized_replacement_proposal():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    staged = await service.stage_replacement_from_proposal(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Stage governed replacement.",
    )

    assert staged.status == "staged"
    assert staged.source_proposal_id == proposal.id
    assert staged.lineage_id == source_artifact.lineage_id
    assert staged.parent_artifact_id == source_artifact.id
    assert staged.supersedes_artifact_id == source_artifact.id
    assert staged.name == source_artifact.name
    assert staged.scope == source_artifact.scope
    assert staged.approved_by is None
    assert staged.approved_at is None
    assert artifact_repository.artifacts[0] == source_artifact
    assert artifact_repository.artifacts[0].status == "stable"
    assert artifact_repository.artifacts[-1] == staged
    event_types = [event.event_type for event in audit_repository.events]
    assert event_types == [
        "skill.artifact.candidate_created",
        "skill.artifact.staged",
        "skill.artifact.replacement_proposal_staged",
    ]
    event = audit_repository.events[-1]
    assert event.event_data["artifact_id"] == staged.id
    assert event.event_data["proposal_id"] == proposal.id
    assert event.event_data["proposal_source"] == "skill_patch_request_realization"
    assert event.event_data["source_skill_patch_request_id"] == "patch-request-1"
    assert event.event_data["source_artifact_id"] == source_artifact.id
    assert event.event_data["source_artifact_status"] == "stable"
    assert event.event_data["lineage_id"] == source_artifact.lineage_id
    assert event.event_data["parent_artifact_id"] == source_artifact.id
    assert event.event_data["supersedes_artifact_id"] == source_artifact.id
    assert event.event_data["reason_code"] == "reviewed"


async def test_skill_replacement_staging_service_stages_merge_sourced_replacement_proposal():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(
        source_artifact,
        source="skill_curator_merge_recommendation",
    )
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    staged = await service.stage_replacement_from_proposal(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Stage governed merge replacement.",
    )

    assert staged.status == "staged"
    assert staged.source_proposal_id == proposal.id
    assert staged.lineage_id == source_artifact.lineage_id
    assert staged.parent_artifact_id == source_artifact.id
    assert staged.supersedes_artifact_id == source_artifact.id
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.replacement_proposal_staged"
    assert event.event_data["proposal_source"] == "skill_curator_merge_recommendation"
    assert event.event_data["recommendation_id"] == "recommendation-merge-1"
    assert event.event_data["source_skill_patch_request_id"] is None
    assert event.event_data["merge_source_artifact_ids"] == ["artifact-merge-source"]


async def test_skill_replacement_staging_service_reuses_existing_staged_replacement():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    first = await service.stage_replacement_from_proposal(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note=None,
    )
    second = await service.stage_replacement_from_proposal(
        proposal_id=proposal.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note="Repeat.",
    )

    assert second.id == first.id
    assert second.status == "staged"
    assert len(artifact_repository.artifacts) == 2
    event_types = [event.event_type for event in audit_repository.events]
    assert event_types.count("skill.artifact.candidate_created") == 1
    assert event_types.count("skill.artifact.staged") == 1
    assert event_types.count("skill.artifact.candidate_reused") == 1
    assert event_types.count("skill.artifact.stage_reused") == 1
    assert event_types.count("skill.artifact.replacement_proposal_staged") == 2


async def test_skill_replacement_staging_service_rejects_non_replacement_proposal_without_artifact_side_effect():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _approved_skill_package_proposal()
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    with pytest.raises(ValidationError, match="governed replacement"):
        await service.stage_replacement_from_proposal(
            proposal_id=proposal.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [source_artifact]
    assert audit_repository.events == []


async def test_skill_replacement_staging_service_rejects_unapproved_or_ineffective_replacement_proposal():
    source_artifact = _source_artifact_for_replacement()
    unapproved, unapproved_evaluation = _realized_replacement_skill_package_proposal(
        source_artifact,
        status="sandbox_completed",
    )
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    service = _skill_replacement_staging_service(
        artifact_repository,
        unapproved,
        unapproved_evaluation,
        StubAuditRepository(),
    )

    with pytest.raises(ValidationError, match="Only approved"):
        await service.stage_replacement_from_proposal(
            proposal_id=unapproved.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    ineffective, ineffective_evaluation = _realized_replacement_skill_package_proposal(
        source_artifact,
        evaluation_status="inconclusive",
    )
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    service = _skill_replacement_staging_service(
        artifact_repository,
        ineffective,
        ineffective_evaluation,
        StubAuditRepository(),
    )

    with pytest.raises(ValidationError, match="effective evaluation"):
        await service.stage_replacement_from_proposal(
            proposal_id=ineffective.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [source_artifact]


@pytest.mark.parametrize("status", ["candidate", "staged", "suppressed", "deprecated", "archived", "rejected"])
async def test_skill_replacement_staging_service_rejects_non_selectable_source_status(status: str):
    source_artifact = _source_artifact_for_replacement(status=status)
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    with pytest.raises(ValidationError, match="active or stable source artifact"):
        await service.stage_replacement_from_proposal(
            proposal_id=proposal.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [source_artifact]
    assert audit_repository.events == []


async def test_skill_replacement_staging_service_rejects_mismatched_replacement_anchor():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    proposal = replace(
        proposal,
        evidence_snapshot={
            **proposal.evidence_snapshot,
            "source_artifact_lineage_id": "other-lineage",
        },
    )
    artifact_repository = StubSkillArtifactRepository(source_artifact)
    audit_repository = StubAuditRepository()
    service = _skill_replacement_staging_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
    )

    with pytest.raises(ValidationError, match="lineage"):
        await service.stage_replacement_from_proposal(
            proposal_id=proposal.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [source_artifact]
    assert audit_repository.events == []


async def test_skill_replacement_readiness_service_reports_ready_replaceable_governed_staged_replacement():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    observation_2 = replace(
        _stable_rollout_observation(
            proposal=proposal,
            rollout=rollout,
            recommendation="promote",
            created_at=rollout.activated_at + timedelta(minutes=2),
        ),
        signal_summary={"completed_usage_count": 3},
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation_2.id)
    usage_events = [
        replace(usage_event, id=f"usage-ready-{index}", created_at=rollout.activated_at + timedelta(minutes=index + 1))
        for index in range(3)
    ]
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.append(source_artifact)
    service = SkillReplacementReadinessService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        rollout_repository=StubProposalRolloutRepository(rollout),
        rollout_observation_repository=StubProposalRolloutObservationRepository([observation, observation_2]),
        goal_skill_binding_repository=StubGoalSkillBindingRepository(binding),
        usage_repository=StubSkillUsageEventRepository(events=usage_events),
    )

    readiness = await service.get_replacement_readiness(artifact_id=staged.id)

    assert readiness.proposal_source == "skill_patch_request_realization"
    assert readiness.source_anchor["source_artifact_id"] == source_artifact.id
    assert readiness.source_anchor["anchor_status"] == "anchored"
    assert readiness.activate_readiness.status == "blocked"
    assert "current_selectable_conflict" in readiness.activate_readiness.reason_codes
    assert readiness.replace_readiness.status == "ready"
    assert readiness.recommended_action == "replace_selectable"
    assert readiness.rollout_evidence["latest_observation_id"] == observation_2.id
    assert len(readiness.rollout_evidence["promote_observation_ids"]) == 2
    assert readiness.usage_evidence["successful_count"] == 3
    assert readiness.thresholds.successful_usage_min == 3


async def test_skill_replacement_readiness_service_blocks_when_source_anchor_changes():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    observation_2 = _stable_rollout_observation(
        proposal=proposal,
        rollout=rollout,
        recommendation="promote",
        created_at=rollout.activated_at + timedelta(minutes=2),
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation_2.id)
    deprecated_source = source_artifact.mark_deprecated(operator_id="operator")
    new_selectable = replace(
        _source_artifact_for_replacement(),
        version="0.1.88",
        lineage_id="lineage-new",
    )
    usage_events = [
        replace(usage_event, id=f"usage-drift-{index}", created_at=rollout.activated_at + timedelta(minutes=index + 1))
        for index in range(3)
    ]
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.extend([deprecated_source, new_selectable])
    service = SkillReplacementReadinessService(
        artifact_repository=artifact_repository,
        proposal_repository=StubProposalRepository(proposal),
        rollout_repository=StubProposalRolloutRepository(rollout),
        rollout_observation_repository=StubProposalRolloutObservationRepository([observation, observation_2]),
        goal_skill_binding_repository=StubGoalSkillBindingRepository(binding),
        usage_repository=StubSkillUsageEventRepository(events=usage_events),
    )

    readiness = await service.get_replacement_readiness(artifact_id=staged.id)

    assert readiness.source_anchor["current_source_status"] == "deprecated"
    assert readiness.source_anchor["current_selectable_artifact_id"] == new_selectable.id
    assert readiness.replace_readiness.status == "blocked"
    assert readiness.recommended_action is None
    assert "existing_selectable_not_source_anchor" in readiness.replace_readiness.reason_codes


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
            allowed_skills=["create_quiz"],
        ).stage_candidate(
            artifact_id=candidate.id,
            operator_id="operator",
            reason_code="reviewed",
            reason_note=None,
        )

    alternate_binding = replace(
        candidate,
        compatibility_contract={
            "surfaces": ["quiz"],
            "implementation_binding": "llm_create_quiz_v1",
            "dynamic_execution": False,
        },
    )
    staged = await _skill_artifact_lifecycle_service(
        StubSkillArtifactRepository(alternate_binding),
        proposal,
        evaluation,
        StubAuditRepository(),
        allowed_skills=["create_quiz"],
    ).stage_candidate(
        artifact_id=candidate.id,
        operator_id="operator",
        reason_code="reviewed",
        reason_note=None,
    )
    assert staged.compatibility_contract["implementation_binding"] == "llm_create_quiz_v1"

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


@pytest.mark.parametrize("current_status", ["active", "stable"])
async def test_skill_artifact_lifecycle_service_replaces_selectable_artifact(current_status: str):
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    current = SkillArtifact.build(
        name="create_quiz",
        version="0.1.99",
        skill_type="learned",
        scope="quiz",
        status=current_status,
        description="Current selectable quiz skill.",
        quality_score=0.8,
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.append(current)
    audit_repository = StubAuditRepository()

    replacement = await _skill_artifact_lifecycle_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
        rollout=rollout,
        observation=observation,
        binding=binding,
        usage_events=[usage_event],
    ).replace_selectable(
        artifact_id=staged.id,
        operator_id="operator",
        reason_code="superseded",
        reason_note="Replace current selectable artifact.",
    )

    replaced = await artifact_repository.get_by_id(current.id)
    assert replaced is not None
    assert replaced.status == "deprecated"
    assert replaced.deprecated_by == "operator"
    assert replaced.deprecated_at is not None
    assert replacement.id == staged.id
    assert replacement.status == "active"
    assert replacement.lineage_id == current.lineage_id
    assert replacement.parent_artifact_id == current.id
    assert replacement.supersedes_artifact_id == current.id
    assert replacement.approved_by == "operator"
    assert replacement.approved_at is not None
    assert replacement.updated_at > staged.updated_at

    deactivation_event = audit_repository.events[-2]
    assert deactivation_event.event_type == "skill.artifact.deactivated"
    assert deactivation_event.event_data["artifact_id"] == current.id
    assert deactivation_event.event_data["previous_status"] == current_status
    assert deactivation_event.event_data["superseded_by_artifact_id"] == replacement.id
    assert deactivation_event.event_data["reason_code"] == "superseded"
    replace_event = audit_repository.events[-1]
    assert replace_event.event_type == "skill.artifact.replaced"
    assert replace_event.event_data["artifact_id"] == replacement.id
    assert replace_event.event_data["replaced_artifact_id"] == current.id
    assert replace_event.event_data["replaced_artifact_previous_status"] == current_status
    assert replace_event.event_data["replaced_artifact_status"] == "deprecated"
    assert replace_event.event_data["lineage_id"] == current.lineage_id
    assert replace_event.event_data["parent_artifact_id"] == current.id
    assert replace_event.event_data["supersedes_artifact_id"] == current.id
    assert replace_event.event_data["evaluation_id"] == evaluation.id
    assert replace_event.event_data["rollout_id"] == rollout.id
    assert replace_event.event_data["binding_id"] == binding.id
    assert replace_event.event_data["observation_id"] == observation.id
    assert replace_event.event_data["usage_event_ids"] == [usage_event.id]


async def test_skill_artifact_lifecycle_service_reuses_completed_replacement():
    current = SkillArtifact.build(
        name="create_quiz",
        version="0.1.99",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Current selectable quiz skill.",
        quality_score=0.8,
    )
    replacement = SkillArtifact.build(
        name="create_quiz",
        version="0.1.100",
        skill_type="learned",
        scope="quiz",
        status="staged",
        description="Replacement quiz skill.",
        quality_score=0.9,
    ).mark_replacement_active(operator_id="operator", superseded_artifact=current)
    deprecated_current = current.mark_deprecated(operator_id="operator")
    artifact_repository = StubSkillArtifactRepository(replacement)
    artifact_repository.artifacts.append(deprecated_current)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).replace_selectable(
        artifact_id=replacement.id,
        operator_id="operator",
        reason_code="superseded",
        reason_note="Repeat replacement.",
    )

    assert reused == replacement
    assert artifact_repository.artifacts == [replacement, deprecated_current]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.replace_reused"
    assert event.event_data["artifact_id"] == replacement.id
    assert event.event_data["replaced_artifact_id"] == deprecated_current.id
    assert event.event_data["usage_event_ids"] == []


async def test_skill_artifact_lifecycle_service_rejects_replacement_without_existing_selectable():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    artifact_repository = StubSkillArtifactRepository(staged)

    with pytest.raises(ValidationError, match="existing selectable"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observation=observation,
            binding=binding,
            usage_events=[usage_event],
        ).replace_selectable(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="superseded",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [staged]


async def test_skill_artifact_lifecycle_service_rejects_replacement_without_required_evidence():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    current = SkillArtifact.build(
        name="create_quiz",
        version="0.1.99",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Current selectable quiz skill.",
        quality_score=0.8,
    )
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.append(current)

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
        ).replace_selectable(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="superseded",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [staged, current]


async def test_skill_artifact_lifecycle_service_rejects_replacement_when_source_anchor_drifts():
    source_artifact = _source_artifact_for_replacement()
    proposal, evaluation = _realized_replacement_skill_package_proposal(source_artifact)
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    observation_2 = _stable_rollout_observation(
        proposal=proposal,
        rollout=rollout,
        recommendation="promote",
        created_at=rollout.activated_at + timedelta(minutes=2),
    )
    rollout = rollout.with_status("rolled_out", latest_observation_id=observation_2.id)
    drifted_selectable = replace(
        _source_artifact_for_replacement(),
        version="0.1.88",
        lineage_id="lineage-drifted",
    )
    deprecated_source = source_artifact.mark_deprecated(operator_id="operator")
    usage_events = [
        replace(usage_event, id=f"usage-anchor-{index}", created_at=rollout.activated_at + timedelta(minutes=index + 1))
        for index in range(3)
    ]
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.extend([deprecated_source, drifted_selectable])

    with pytest.raises(ValidationError, match="existing_selectable_not_source_anchor"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observation=observation_2,
            observations=[observation, observation_2],
            binding=binding,
            usage_events=usage_events,
        ).replace_selectable(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="superseded",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [staged, deprecated_source, drifted_selectable]


async def test_skill_resolver_selects_replacement_after_supersede():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    rollout, binding, observation, usage_event = _activation_rollout_bundle(proposal)
    current = SkillArtifact.build(
        name="create_quiz",
        version="0.1.99",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Current selectable quiz skill.",
        quality_score=0.8,
    )
    artifact_repository = StubSkillArtifactRepository(staged)
    artifact_repository.artifacts.append(current)
    audit_repository = StubAuditRepository()
    replacement = await _skill_artifact_lifecycle_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
        rollout=rollout,
        observation=observation,
        binding=binding,
        usage_events=[usage_event],
    ).replace_selectable(
        artifact_id=staged.id,
        operator_id="operator",
        reason_code="superseded",
        reason_note=None,
    )
    resolver = SkillResolver(
        artifact_repository=artifact_repository,
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
    )

    resolution = await resolver.resolve(skill_name="create_quiz", surface="quiz")

    assert resolution.resolver_status == "resolved"
    assert resolution.artifact_id == replacement.id
    assert resolution.artifact_status == "active"


async def test_skill_artifact_lifecycle_service_stabilizes_active_artifact_with_stronger_evidence():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    active = staged.mark_active(operator_id="operator")
    rollout, binding, _activation_observation, _activation_usage = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=active,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
        negative_usage_count=1,
    )
    artifact_repository = StubSkillArtifactRepository(active)
    audit_repository = StubAuditRepository()

    stable = await _skill_artifact_lifecycle_service(
        artifact_repository,
        proposal,
        evaluation,
        audit_repository,
        rollout=rollout,
        observations=observations,
        binding=binding,
        usage_events=usage_events,
    ).stabilize_active(
        artifact_id=active.id,
        operator_id="operator-stable",
        reason_code="stable_evidence",
        reason_note="Production window is stable.",
    )

    assert stable.id == active.id
    assert stable.status == "stable"
    assert stable.approved_by == "operator-stable"
    assert stable.approved_at is not None
    assert stable.approved_at > active.approved_at
    assert stable.updated_at > active.updated_at
    assert artifact_repository.artifacts == [stable]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.stabilized"
    assert event.event_data["artifact_id"] == active.id
    assert event.event_data["source_proposal_id"] == proposal.id
    assert event.event_data["rollout_id"] == rollout.id
    assert event.event_data["binding_id"] == binding.id
    assert event.event_data["observation_ids"] == [observations[1].id, observations[0].id]
    assert event.event_data["usage_event_ids"] == [item.id for item in usage_events[:5]]
    assert event.event_data["successful_usage_count"] == 5
    assert event.event_data["negative_usage_count"] == 1
    assert event.event_data["negative_usage_rate"] == pytest.approx(1 / 6)
    assert event.event_data["evidence_started_at"] == active.approved_at.isoformat()
    assert event.event_data["operator_id"] == "operator-stable"
    assert event.event_data["reason_code"] == "stable_evidence"


async def test_skill_artifact_lifecycle_service_reuses_already_stable_artifact():
    stable = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Stable learned quiz skill.",
        quality_score=0.9,
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )
    artifact_repository = StubSkillArtifactRepository(stable)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).stabilize_active(
        artifact_id=stable.id,
        operator_id="operator",
        reason_code="stable_evidence",
        reason_note=None,
    )

    assert reused == stable
    assert artifact_repository.artifacts == [stable]
    assert audit_repository.events[-1].event_type == "skill.artifact.stabilize_reused"
    assert audit_repository.events[-1].event_data["usage_event_ids"] == []


async def test_skill_artifact_lifecycle_service_rejects_stabilization_for_non_active_artifact():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(staged),
            proposal,
            evaluation,
            StubAuditRepository(),
        ).stabilize_active(
            artifact_id=staged.id,
            operator_id="operator",
            reason_code="stable_evidence",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_rejects_stabilization_without_strong_evidence():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    active = staged.mark_active(operator_id="operator")
    rollout, binding, _activation_observation, _activation_usage = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=active,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
    )
    evidence_started_at = active.approved_at or active.updated_at
    old_observation = replace(observations[0], created_at=evidence_started_at - timedelta(seconds=1))
    rollback_observation = replace(observations[1], recommendation="rollback")
    old_usage = replace(usage_events[0], created_at=evidence_started_at - timedelta(seconds=1))

    invalid_cases = [
        {"observations": observations[:1], "usage_events": usage_events},
        {"observations": [observations[0], rollback_observation], "usage_events": usage_events},
        {"observations": [old_observation, observations[1]], "usage_events": usage_events},
        {"observations": observations, "usage_events": usage_events[:4]},
        {"observations": observations, "usage_events": [old_usage, *usage_events[1:5]]},
    ]
    for item in invalid_cases:
        with pytest.raises(ValidationError):
            await _skill_artifact_lifecycle_service(
                StubSkillArtifactRepository(active),
                proposal,
                evaluation,
                StubAuditRepository(),
                rollout=rollout,
                observations=item["observations"],
                binding=binding,
                usage_events=item["usage_events"],
            ).stabilize_active(
                artifact_id=active.id,
                operator_id="operator",
                reason_code="stable_evidence",
                reason_note=None,
            )


async def test_skill_artifact_lifecycle_service_rejects_stabilization_when_negative_usage_rate_is_high():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    active = staged.mark_active(operator_id="operator")
    rollout, binding, _activation_observation, _activation_usage = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=active,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
        negative_usage_count=2,
    )

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(active),
            proposal,
            evaluation,
            StubAuditRepository(),
            rollout=rollout,
            observations=observations,
            binding=binding,
            usage_events=usage_events,
        ).stabilize_active(
            artifact_id=active.id,
            operator_id="operator",
            reason_code="stable_evidence",
            reason_note=None,
        )


async def test_skill_artifact_lifecycle_service_rejects_stabilization_when_rollout_or_binding_not_promoted():
    proposal, evaluation = _approved_skill_package_proposal()
    staged = await _staged_artifact_from_proposal(proposal, evaluation)
    active = staged.mark_active(operator_id="operator")
    rollout, binding, _activation_observation, _activation_usage = _activation_rollout_bundle(proposal)
    observations, usage_events = _stable_evidence_bundle(
        artifact=active,
        proposal=proposal,
        rollout=rollout,
        binding=binding,
    )

    for rollout_candidate, binding_candidate in (
        (replace(rollout, status="rolled_back"), binding),
        (rollout, replace(binding, status="staged")),
    ):
        with pytest.raises(ValidationError):
            await _skill_artifact_lifecycle_service(
                StubSkillArtifactRepository(active),
                proposal,
                evaluation,
                StubAuditRepository(),
                rollout=rollout_candidate,
                observations=observations,
                binding=binding_candidate,
                usage_events=usage_events,
            ).stabilize_active(
                artifact_id=active.id,
                operator_id="operator",
                reason_code="stable_evidence",
                reason_note=None,
            )


@pytest.mark.parametrize("current_status", ["active", "stable"])
async def test_skill_artifact_lifecycle_service_suppresses_selectable_artifact(current_status: str):
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status=current_status,
        description="Selectable quiz skill.",
        quality_score=0.8,
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )
    artifact_repository = StubSkillArtifactRepository(artifact)
    audit_repository = StubAuditRepository()

    suppressed = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).suppress_selectable(
        artifact_id=artifact.id,
        operator_id="operator-suppress",
        reason_code="safety_risk",
        reason_note="Disable while investigating.",
    )

    assert suppressed.id == artifact.id
    assert suppressed.status == "suppressed"
    assert suppressed.suppressed_reason_code == "safety_risk"
    assert suppressed.suppressed_reason_note == "Disable while investigating."
    assert suppressed.suppressed_by == "operator-suppress"
    assert suppressed.suppressed_at is not None
    assert suppressed.suppressed_previous_status == current_status
    assert artifact_repository.artifacts == [suppressed]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.suppressed"
    assert event.event_data["artifact_id"] == artifact.id
    assert event.event_data["status"] == "suppressed"
    assert event.event_data["previous_status"] == current_status
    assert event.event_data["suppressed_reason_code"] == "safety_risk"
    assert event.event_data["suppressed_reason_note"] == "Disable while investigating."
    assert event.event_data["suppressed_by"] == "operator-suppress"
    assert event.event_data["suppressed_previous_status"] == current_status
    assert event.event_data["reason_code"] == "safety_risk"


async def test_skill_artifact_lifecycle_service_reuses_already_suppressed_artifact():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Selectable quiz skill.",
        quality_score=0.8,
    )
    suppressed = active.mark_suppressed(
        operator_id="operator-suppress",
        reason_code="quality_regression",
        reason_note="Stop bad rollout.",
    )
    artifact_repository = StubSkillArtifactRepository(suppressed)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).suppress_selectable(
        artifact_id=suppressed.id,
        operator_id="operator-repeat",
        reason_code="operator_request",
        reason_note="Repeat suppression.",
    )

    assert reused == suppressed
    assert artifact_repository.artifacts == [suppressed]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.suppress_reused"
    assert event.event_data["artifact_id"] == suppressed.id
    assert event.event_data["previous_status"] == "active"
    assert event.event_data["suppressed_reason_code"] == "quality_regression"
    assert event.event_data["reason_code"] == "operator_request"


@pytest.mark.parametrize("status", ["candidate", "staged", "deprecated"])
async def test_skill_artifact_lifecycle_service_rejects_suppression_for_non_selectable_artifact(status: str):
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status=status,
        description="Non-selectable quiz skill.",
        quality_score=0.8,
    )
    artifact_repository = StubSkillArtifactRepository(artifact)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="active or stable"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            None,
            None,
            audit_repository,
        ).suppress_selectable(
            artifact_id=artifact.id,
            operator_id="operator",
            reason_code="operator_request",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [artifact]
    assert audit_repository.events == []


async def test_skill_artifact_lifecycle_service_rejects_suppression_conflict():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Selectable quiz skill.",
        quality_score=0.8,
    )
    other = SkillArtifact.build(
        name="create_quiz",
        version="0.1.1",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Already suppressed quiz skill.",
        quality_score=0.7,
    ).mark_suppressed(
        operator_id="operator",
        reason_code="safety_risk",
        reason_note=None,
    )
    artifact_repository = StubSkillArtifactRepository(active)
    artifact_repository.artifacts.append(other)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="suppressed skill artifact already exists"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            None,
            None,
            audit_repository,
        ).suppress_selectable(
            artifact_id=active.id,
            operator_id="operator",
            reason_code="operator_request",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [active, other]
    assert audit_repository.events == []


@pytest.mark.parametrize("previous_status", ["active", "stable"])
async def test_skill_artifact_lifecycle_service_restores_suppressed_artifact(previous_status: str):
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status=previous_status,
        description="Selectable quiz skill.",
        quality_score=0.8,
    )
    suppressed = artifact.mark_suppressed(
        operator_id="operator-suppress",
        reason_code="policy_violation",
        reason_note="Temporary policy stop.",
    )
    artifact_repository = StubSkillArtifactRepository(suppressed)
    audit_repository = StubAuditRepository()

    restored = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).restore_suppressed(
        artifact_id=suppressed.id,
        operator_id="operator-restore",
        reason_code="false_positive",
        reason_note="Policy stop was cleared.",
    )

    assert restored.id == suppressed.id
    assert restored.status == previous_status
    assert restored.suppressed_reason_code is None
    assert restored.suppressed_reason_note is None
    assert restored.suppressed_by is None
    assert restored.suppressed_at is None
    assert restored.suppressed_previous_status is None
    assert artifact_repository.artifacts == [restored]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.restored"
    assert event.event_data["artifact_id"] == suppressed.id
    assert event.event_data["status"] == previous_status
    assert event.event_data["previous_status"] == "suppressed"
    assert event.event_data["suppressed_reason_code"] == "policy_violation"
    assert event.event_data["suppressed_reason_note"] == "Temporary policy stop."
    assert event.event_data["suppressed_by"] == "operator-suppress"
    assert event.event_data["suppressed_previous_status"] == previous_status
    assert event.event_data["reason_code"] == "false_positive"


async def test_skill_artifact_lifecycle_service_rejects_restore_when_selectable_conflicts():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Suppressed quiz skill.",
        quality_score=0.8,
    )
    suppressed = active.mark_suppressed(
        operator_id="operator",
        reason_code="safety_risk",
        reason_note=None,
    )
    selectable = SkillArtifact.build(
        name="create_quiz",
        version="0.1.1",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Replacement selectable quiz skill.",
        quality_score=0.9,
    )
    artifact_repository = StubSkillArtifactRepository(suppressed)
    artifact_repository.artifacts.append(selectable)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="selectable skill artifact already exists"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            None,
            None,
            audit_repository,
        ).restore_suppressed(
            artifact_id=suppressed.id,
            operator_id="operator",
            reason_code="risk_mitigated",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [suppressed, selectable]
    assert audit_repository.events == []


async def test_skill_artifact_lifecycle_service_reuses_completed_restore():
    restored = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Restored quiz skill.",
        quality_score=0.8,
    )
    artifact_repository = StubSkillArtifactRepository(restored)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).restore_suppressed(
        artifact_id=restored.id,
        operator_id="operator",
        reason_code="operator_restore",
        reason_note="Repeat restore.",
    )

    assert reused == restored
    assert artifact_repository.artifacts == [restored]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.restore_reused"
    assert event.event_data["artifact_id"] == restored.id
    assert event.event_data["status"] == "stable"
    assert event.event_data["previous_status"] == "stable"
    assert event.event_data["suppressed_reason_code"] is None


async def test_skill_artifact_lifecycle_service_archives_deprecated_artifact():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Deprecated quiz skill.",
        source_reflection_ids=["reflection-1"],
        source_memory_ids=["memory-1"],
        source_proposal_id="proposal-1",
        quality_score=0.8,
    )
    deprecated = active.mark_deprecated(operator_id="operator-deprecate")
    artifact_repository = StubSkillArtifactRepository(deprecated)
    audit_repository = StubAuditRepository()

    archived = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).archive_deprecated(
        artifact_id=deprecated.id,
        operator_id="operator-archive",
        reason_code="stale_deprecated",
        reason_note="No recent attributed usage.",
    )

    assert archived.id == deprecated.id
    assert archived.status == "archived"
    assert archived.lineage_id == deprecated.lineage_id
    assert archived.source_proposal_id == "proposal-1"
    assert archived.source_reflection_ids == ["reflection-1"]
    assert archived.source_memory_ids == ["memory-1"]
    assert archived.deprecated_by == "operator-deprecate"
    assert archived.deprecated_at == deprecated.deprecated_at
    assert artifact_repository.artifacts == [archived]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.archived"
    assert event.event_data["artifact_id"] == deprecated.id
    assert event.event_data["status"] == "archived"
    assert event.event_data["previous_status"] == "deprecated"
    assert event.event_data["lineage_id"] == deprecated.lineage_id
    assert event.event_data["source_proposal_id"] == "proposal-1"
    assert event.event_data["source_reflection_ids"] == ["reflection-1"]
    assert event.event_data["source_memory_ids"] == ["memory-1"]
    assert event.event_data["deprecated_by"] == "operator-deprecate"
    assert event.event_data["operator_id"] == "operator-archive"
    assert event.event_data["reason_code"] == "stale_deprecated"


async def test_skill_artifact_lifecycle_service_reuses_already_archived_artifact():
    deprecated = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Deprecated quiz skill.",
        quality_score=0.8,
    ).mark_deprecated(operator_id="operator")
    archived = deprecated.mark_archived(operator_id="operator")
    artifact_repository = StubSkillArtifactRepository(archived)
    audit_repository = StubAuditRepository()

    reused = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).archive_deprecated(
        artifact_id=archived.id,
        operator_id="operator-repeat",
        reason_code="cleanup",
        reason_note="Repeat archive.",
    )

    assert reused == archived
    assert artifact_repository.artifacts == [archived]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.archive_reused"
    assert event.event_data["artifact_id"] == archived.id
    assert event.event_data["status"] == "archived"
    assert event.event_data["previous_status"] == "archived"
    assert event.event_data["reason_code"] == "cleanup"


@pytest.mark.parametrize("status", ["candidate", "staged", "active", "stable", "suppressed", "rejected"])
async def test_skill_artifact_lifecycle_service_rejects_archive_for_non_deprecated_artifact(status: str):
    base_status = "active" if status == "suppressed" else status
    artifact = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status=base_status,
        description="Non-deprecated quiz skill.",
        quality_score=0.8,
    )
    if status == "suppressed":
        artifact = artifact.mark_suppressed(
            operator_id="operator",
            reason_code="safety_risk",
            reason_note=None,
        )
    artifact_repository = StubSkillArtifactRepository(artifact)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="deprecated"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            None,
            None,
            audit_repository,
        ).archive_deprecated(
            artifact_id=artifact.id,
            operator_id="operator",
            reason_code="operator_request",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [artifact]
    assert audit_repository.events == []


async def test_skill_artifact_lifecycle_service_rejects_restore_for_archived_artifact():
    archived = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Archived quiz skill.",
        quality_score=0.8,
    ).mark_deprecated(operator_id="operator").mark_archived(operator_id="operator")

    with pytest.raises(ValidationError, match="suppressed"):
        await _skill_artifact_lifecycle_service(
            StubSkillArtifactRepository(archived),
            None,
            None,
            StubAuditRepository(),
        ).restore_suppressed(
            artifact_id=archived.id,
            operator_id="operator",
            reason_code="operator_restore",
            reason_note=None,
        )


async def test_skill_resolver_blocks_when_suppressed_artifact_coexists_with_selectable():
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Active quiz skill.",
        quality_score=0.8,
    )
    suppressed = SkillArtifact.build(
        name="create_quiz",
        version="0.1.1",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Suppressed quiz skill.",
        quality_score=0.9,
    ).mark_suppressed(
        operator_id="operator",
        reason_code="safety_risk",
        reason_note=None,
    )
    archived = SkillArtifact.build(
        name="create_quiz",
        version="0.1.2",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Archived quiz skill.",
        quality_score=0.6,
    ).mark_deprecated(operator_id="operator").mark_archived(operator_id="operator")
    artifact_repository = StubSkillArtifactRepository(active)
    artifact_repository.artifacts.append(suppressed)
    artifact_repository.artifacts.append(archived)
    audit_repository = StubAuditRepository()
    resolver = SkillResolver(
        artifact_repository=artifact_repository,
        audit_service=AuditService(audit_repository),
        skill_registry=SkillRegistry.from_allowed_skills(["create_quiz"]),
    )

    resolution = await resolver.resolve(skill_name="create_quiz", surface="quiz")

    assert resolution.resolver_status == "blocked"
    assert resolution.selection_reason == "suppressed_artifact"
    assert resolution.artifact_id == suppressed.id
    assert resolution.artifact_status == "suppressed"
    assert any(item.event_type == "skill.resolution.blocked" for item in audit_repository.events)


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
    assert deactivated.deprecated_by == "operator"
    assert deactivated.deprecated_at is not None
    assert deactivated.updated_at > active.updated_at
    assert artifact_repository.artifacts == [deactivated]
    event = audit_repository.events[-1]
    assert event.event_type == "skill.artifact.deactivated"
    assert event.event_data["artifact_id"] == active.id
    assert event.event_data["source_proposal_id"] == "proposal-1"
    assert event.event_data["operator_id"] == "operator"
    assert event.event_data["reason_code"] == "rollout_rollback"


async def test_skill_artifact_lifecycle_service_deactivates_stable_artifact():
    stable = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="stable",
        description="Stable learned quiz skill.",
        source_proposal_id="proposal-1",
        quality_score=0.9,
        approved_by="operator",
        approved_at=datetime.now(timezone.utc),
    )
    artifact_repository = StubSkillArtifactRepository(stable)
    audit_repository = StubAuditRepository()

    deactivated = await _skill_artifact_lifecycle_service(
        artifact_repository,
        None,
        None,
        audit_repository,
    ).deactivate_active(
        artifact_id=stable.id,
        operator_id="operator",
        reason_code="rollout_rollback",
        reason_note="Rollback source rollout.",
    )

    assert deactivated.id == stable.id
    assert deactivated.status == "deprecated"
    assert artifact_repository.artifacts == [deactivated]
    assert audit_repository.events[-1].event_type == "skill.artifact.deactivated"


async def test_skill_artifact_lifecycle_service_rejects_repeated_deactivation():
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

    with pytest.raises(ValidationError):
        await _skill_artifact_lifecycle_service(
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

    assert artifact_repository.artifacts == [deprecated]
    assert audit_repository.events == []


async def test_skill_artifact_lifecycle_service_rejects_deactivation_with_active_binding():
    proposal, _evaluation = _approved_skill_package_proposal()
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Active learned quiz skill.",
        source_proposal_id=proposal.id,
        quality_score=0.8,
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    artifact_repository = StubSkillArtifactRepository(active)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="active goal skill bindings"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            proposal,
            None,
            audit_repository,
            rollout=replace(rollout, status="rolled_back"),
            binding=binding,
        ).deactivate_active(
            artifact_id=active.id,
            operator_id="operator",
            reason_code="rollout_rollback",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [active]
    assert audit_repository.events == []


async def test_skill_artifact_lifecycle_service_rejects_deactivation_with_active_rollout():
    proposal, _evaluation = _approved_skill_package_proposal()
    active = SkillArtifact.build(
        name="create_quiz",
        version="0.1.0",
        skill_type="learned",
        scope="quiz",
        status="active",
        description="Active learned quiz skill.",
        source_proposal_id=proposal.id,
        quality_score=0.8,
    )
    rollout, binding, _observation, _usage = _activation_rollout_bundle(proposal)
    artifact_repository = StubSkillArtifactRepository(active)
    audit_repository = StubAuditRepository()

    with pytest.raises(ValidationError, match="active rollouts"):
        await _skill_artifact_lifecycle_service(
            artifact_repository,
            proposal,
            None,
            audit_repository,
            rollout=rollout,
            binding=replace(binding, status="rolled_back"),
        ).deactivate_active(
            artifact_id=active.id,
            operator_id="operator",
            reason_code="rollout_rollback",
            reason_note=None,
        )

    assert artifact_repository.artifacts == [active]
    assert audit_repository.events == []


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


async def test_skill_resolver_ignores_archived_artifact_after_archive():
    archived = SkillArtifact.build(
        name="explain_concept",
        version="1.0.0",
        skill_type="baseline",
        scope="chat",
        status="active",
        description="Archived skill.",
        quality_score=1.0,
    ).mark_deprecated(operator_id="operator").mark_archived(operator_id="operator")
    audit_repository = StubAuditRepository()
    resolver = _skill_resolver(archived, audit_repository)

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


async def test_skill_runtime_allows_registered_alternate_handler_binding():
    artifact = _legacy_skill_artifact_with_contract(
        name="explain_concept",
        scope="chat",
        status="active",
        compatibility_contract={
            "surfaces": ["chat"],
            "implementation_binding": "llm_explain_concept_v1",
            "dynamic_execution": False,
        },
    )
    audit_repository = StubAuditRepository()
    service = SkillUsageService(
        usage_repository=StubSkillUsageEventRepository(),
        skill_resolver=_skill_resolver(artifact, audit_repository),
        audit_service=AuditService(audit_repository),
    )

    resolution = await service.resolve_for_runtime(skill_name="explain_concept", surface="chat")

    assert resolution.resolver_status == "resolved"
    assert resolution.implementation_binding == "llm_explain_concept_v1"


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


# ---------------------------------------------------------------------------
# Phase 6: Runtime Explainability – SkillResolution & usage metadata merging
# ---------------------------------------------------------------------------

def test_skill_resolution_build_stores_explainability_fields():
    """SkillResolution.build accepts and stores Phase 6 explainability fields."""
    resolution = SkillResolution.build(
        skill_name="explain_concept",
        surface="chat",
        implementation_binding="explain_concept",
        winner_candidate={"candidate_id": "c-1", "source_type": "artifact"},
        loser_reason_summary={"c-2": ["low_trust"]},
        confidence=0.87,
        fallback_chain=["explain_concept_v1"],
        template_id="tpl-abc",
    )
    assert resolution.winner_candidate == {"candidate_id": "c-1", "source_type": "artifact"}
    assert resolution.loser_reason_summary == {"c-2": ["low_trust"]}
    assert resolution.confidence == 0.87
    assert resolution.fallback_chain == ["explain_concept_v1"]
    assert resolution.template_id == "tpl-abc"


def test_skill_resolution_build_defaults_explainability_to_none():
    """SkillResolution.build defaults new explainability fields to None for backward compat."""
    resolution = SkillResolution.build(
        skill_name="explain_concept",
        surface="chat",
        implementation_binding="explain_concept",
    )
    assert resolution.winner_candidate is None
    assert resolution.loser_reason_summary is None
    assert resolution.confidence is None
    assert resolution.fallback_chain is None
    assert resolution.template_id is None


@pytest.mark.asyncio
async def test_record_usage_merges_resolution_explainability_into_metadata():
    """record_usage propagates router explainability fields into persisted metadata."""
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
    winner_candidate = {"candidate_id": "c-1", "source_type": "artifact"}
    resolution = SkillResolution.build(
        skill_name="explain_concept",
        surface="chat",
        implementation_binding="explain_concept",
        artifact_id=artifact.id,
        artifact_status="active",
        resolver_status="resolved",
        selection_reason="production_default",
        winner_candidate=winner_candidate,
        loser_reason_summary={"c-2": ["low_trust"]},
        confidence=0.91,
        fallback_chain=["fallback_skill"],
        template_id="tpl-xyz",
    )

    event = await service.record_usage(
        skill_name="explain_concept",
        surface="chat",
        outcome_status="completed",
        resolution=resolution,
        metadata={"custom_key": "custom_val"},
    )

    assert event is not None
    meta = event.metadata or {}
    assert meta.get("winner_candidate") == winner_candidate
    assert meta.get("loser_reason_summary") == {"c-2": ["low_trust"]}
    assert meta.get("confidence") == 0.91
    assert meta.get("fallback_chain") == ["fallback_skill"]
    assert meta.get("template_id") == "tpl-xyz"
    # Caller-provided metadata is preserved
    assert meta.get("custom_key") == "custom_val"


@pytest.mark.asyncio
async def test_record_usage_omits_explainability_when_resolution_lacks_them():
    """record_usage omits router explainability keys when resolution has no router fields (backward compat)."""
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
    )

    assert event is not None
    meta = event.metadata or {}
    # None of the Phase 6 explainability keys should appear
    assert "winner_candidate" not in meta
    assert "loser_reason_summary" not in meta
    assert "confidence" not in meta
    assert "fallback_chain" not in meta
    assert "template_id" not in meta
