"""Skill candidate artifact creation service.

This module handles the materialization of approved skill_package proposals
into candidate artifacts. It validates proposal type, status, evaluation,
payload, tool plan, and implementation binding. It writes audit events
for candidate creation but does not perform subsequent state transitions.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.constants import (
    ALLOWED_SKILL_PACKAGE_TOOLS,
    CANDIDATE_MIN_SCORE_DELTA,
)
from agent_core.application.services.skill.observability import refresh_skill_observability_metrics
from agent_core.application.services.tool_plan_contracts import validate_tool_plan_contract
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalEvaluation,
)
from agent_core.domain.entities.skill import SkillArtifact
from agent_core.domain.constants import SkillArtifactStatus
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects import require_non_empty
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
    SkillArtifactRepository,
)


class SkillCandidateService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        audit_service: AuditService,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._audit_service = audit_service

    async def create_candidate_from_proposal(
        self,
        *,
        proposal_id: str,
        operator_id: str,
    ) -> SkillArtifact:
        existing = await self._artifact_repository.get_by_source_proposal_id(proposal_id)
        if existing is not None:
            await self._audit_candidate(
                existing,
                event_type="skill.artifact.candidate_reused",
                operator_id=operator_id,
            )
            return existing

        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal_id)
        self._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = self._validated_payload(proposal)
        skill_name = str(payload["skill_name"])
        surface = str(payload["surface"])
        implementation_binding = await self._implementation_binding_for_candidate(
            proposal=proposal,
            skill_name=skill_name,
        )
        artifact = SkillArtifact.build(
            name=skill_name,
            version=await self._next_candidate_version(skill_name),
            lineage_id=self._replacement_lineage_id(proposal),
            parent_artifact_id=self._replacement_parent_artifact_id(proposal),
            supersedes_artifact_id=self._replacement_supersedes_artifact_id(proposal),
            skill_type="learned",
            scope=surface,
            status=SkillArtifactStatus.CANDIDATE.value,
            description=proposal.change_summary,
            definition={
                "artifact_kind": payload["artifact_kind"],
                "hypothesis": proposal.hypothesis,
                "change_summary": proposal.change_summary,
                "expected_improvement": proposal.expected_improvement,
                "match_rules": dict(payload["match_rules"]),
                "scoring_contract": dict(payload["scoring_contract"]),
                "source_proposal": {
                    "id": proposal.id,
                    "risk_level": proposal.risk_level,
                    "evaluation_status": evaluation.evaluation_status if evaluation else None,
                    "score_delta": evaluation.score_delta if evaluation else None,
                    "sandbox_run_id": evaluation.sandbox_run_id if evaluation else None,
                },
            },
            runtime_directives=dict(payload["runtime_directives"]),
            tool_plan=[dict(item) for item in payload["tool_plan"]],
            compatibility_contract={
                "surfaces": [surface],
                "implementation_binding": implementation_binding,
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=[proposal.reflection_record_id],
            source_memory_ids=self._source_memory_ids(proposal.evidence_snapshot),
            source_proposal_id=proposal.id,
            quality_score=self._quality_score(evaluation.score_delta if evaluation else 0.0),
            created_by=operator_id,
        )
        await self._artifact_repository.create(artifact)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_candidate(artifact, event_type="skill.artifact.candidate_created", operator_id=operator_id)
        return artifact

    @staticmethod
    def _validate_candidate_source(
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
    ) -> None:
        if proposal.proposal_type != "skill_package":
            raise ValidationError("Only skill_package proposals can create skill candidates.")
        if proposal.status != "approved":
            raise ValidationError("Only approved skill_package proposals can create skill candidates.")
        if evaluation is None or evaluation.evaluation_status != "effective":
            raise ValidationError("Skill candidate creation requires an effective evaluation.")
        if evaluation.score_delta is None or evaluation.score_delta < CANDIDATE_MIN_SCORE_DELTA:
            raise ValidationError("Skill candidate creation requires sufficient evaluation score_delta.")

    @staticmethod
    def _validated_payload(proposal: ReflectionProposal) -> dict[str, object]:
        payload = dict(proposal.structured_patch_payload)
        if payload.get("artifact_kind") != "declarative_skill_package":
            raise ValidationError("Unsupported skill package artifact_kind.")
        skill_name = payload.get("skill_name")
        skill_name = require_non_empty(skill_name, "skill_name") if isinstance(skill_name, str) else ""
        if not skill_name:
            raise ValidationError("Skill package skill_name is required.")
        surface = payload.get("surface")
        if surface != proposal.target_scope:
            raise ValidationError("Skill package surface must match proposal target scope.")
        for key in ("match_rules", "runtime_directives", "scoring_contract"):
            if not isinstance(payload.get(key), dict):
                raise ValidationError(f"Skill package {key} must be an object.")
        tool_plan = payload.get("tool_plan")
        if not isinstance(tool_plan, list):
            raise ValidationError("Skill package tool_plan must be a list.")
        for item in tool_plan:
            if not isinstance(item, dict):
                raise ValidationError("Skill package tool_plan items must be objects.")
            tool_name = item.get("tool_name")
            if tool_name not in ALLOWED_SKILL_PACKAGE_TOOLS:
                raise ValidationError("Unsupported skill package tool.")
        validate_tool_plan_contract(str(surface), [dict(item) for item in tool_plan])
        return {
            "artifact_kind": payload["artifact_kind"],
            "skill_name": skill_name.strip(),
            "surface": str(surface),
            "match_rules": dict(payload["match_rules"]),
            "runtime_directives": dict(payload["runtime_directives"]),
            "tool_plan": [dict(item) for item in tool_plan],
            "scoring_contract": dict(payload["scoring_contract"]),
        }

    async def _next_candidate_version(self, name: str) -> str:
        max_patch = await self._artifact_repository.max_candidate_patch_version(name)
        return f"0.1.{max_patch + 1}"

    async def _implementation_binding_for_candidate(
        self,
        *,
        proposal: ReflectionProposal,
        skill_name: str,
    ) -> str:
        source_artifact_id = proposal.evidence_snapshot.get("source_artifact_id")
        if isinstance(source_artifact_id, str) and source_artifact_id.strip():
            source_artifact = await self._artifact_repository.get_by_id(source_artifact_id)
            if source_artifact is not None:
                binding = str(source_artifact.compatibility_contract.get("implementation_binding") or "").strip()
                if binding:
                    return binding
        return self._skill_registry_handler(skill_name)

    def _skill_registry_handler(self, skill_name: str) -> str:
        return skill_name

    @staticmethod
    def _source_memory_ids(evidence_snapshot: dict[str, Any]) -> list[str]:
        items = list((evidence_snapshot.get("memory_corpus") or {}).get("items") or [])
        memory_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_id = item.get("memory_id")
            if isinstance(memory_id, str) and memory_id and memory_id not in memory_ids:
                memory_ids.append(memory_id)
        return memory_ids

    @staticmethod
    def _quality_score(score_delta: float) -> float:
        return min(1.0, max(0.0, 0.5 + score_delta))

    @staticmethod
    def _replacement_lineage_id(proposal: ReflectionProposal) -> str | None:
        value = proposal.evidence_snapshot.get("source_artifact_lineage_id")
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _replacement_parent_artifact_id(proposal: ReflectionProposal) -> str | None:
        value = proposal.evidence_snapshot.get("source_artifact_id")
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _replacement_supersedes_artifact_id(proposal: ReflectionProposal) -> str | None:
        value = proposal.evidence_snapshot.get("source_artifact_id")
        return value if isinstance(value, str) and value.strip() else None

    async def _audit_candidate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str | None = None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id or "system",
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "source_reflection_ids": artifact.source_reflection_ids,
                "source_memory_ids": artifact.source_memory_ids,
                "quality_score": artifact.quality_score,
                "operator_id": operator_id,
            },
        )
