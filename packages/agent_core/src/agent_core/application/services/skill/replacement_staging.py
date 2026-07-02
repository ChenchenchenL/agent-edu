"""Skill replacement staging service.

This module orchestrates replacement proposal staging: it obtains the source
artifact, validates the replacement anchor, and calls candidate/lifecycle
services to complete staging. It writes staged replacement audit events
but does not directly activate or replace artifacts.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.candidates import SkillCandidateService
from agent_core.application.services.skill.lifecycle import SkillArtifactLifecycleService
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalEvaluation,
)
from agent_core.domain.entities.skill import SkillArtifact
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects import require_non_empty
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
    SkillArtifactRepository,
)


class SkillReplacementStagingService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        candidate_service: SkillCandidateService,
        lifecycle_service: SkillArtifactLifecycleService,
        audit_service: AuditService,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._candidate_service = candidate_service
        self._lifecycle_service = lifecycle_service
        self._audit_service = audit_service

    async def stage_replacement_from_proposal(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        proposal = await self._replacement_proposal(proposal_id)
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(proposal=proposal, evaluation=evaluation)
        payload = SkillCandidateService._validated_payload(proposal)
        source_artifact = await self._source_artifact(proposal)
        self._validate_replacement_anchor(
            proposal=proposal,
            payload=payload,
            source_artifact=source_artifact,
        )

        candidate = await self._candidate_service.create_candidate_from_proposal(
            proposal_id=proposal.id,
            operator_id=operator_id,
        )
        staged = await self._lifecycle_service.stage_candidate(
            artifact_id=candidate.id,
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        self._validate_staged_replacement(staged=staged, source_artifact=source_artifact)
        await self._audit_staged_replacement(
            staged,
            source_artifact=source_artifact,
            proposal=proposal,
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return staged

    async def _replacement_proposal(self, proposal_id: str) -> ReflectionProposal:
        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
        if proposal.proposal_type != "skill_package":
            raise ValidationError("Only skill_package proposals can be staged as replacement artifacts.")
        if proposal.evidence_snapshot.get("source") not in {
            "skill_patch_request_realization",
            "skill_curator_merge_recommendation",
        }:
            raise ValidationError("Only governed replacement skill_package proposals can be staged.")
        return proposal

    async def _source_artifact(self, proposal: ReflectionProposal) -> SkillArtifact:
        source_artifact_id = proposal.evidence_snapshot.get("source_artifact_id")
        if not isinstance(source_artifact_id, str) or not source_artifact_id.strip():
            raise ValidationError("Replacement proposal requires source_artifact_id evidence.")
        artifact = await self._artifact_repository.get_by_id_for_update(source_artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{source_artifact_id}' was not found.")
        return artifact

    @staticmethod
    def _validate_replacement_anchor(
        *,
        proposal: ReflectionProposal,
        payload: dict[str, object],
        source_artifact: SkillArtifact,
    ) -> None:
        if source_artifact.status not in {"active", "stable"}:
            raise ValidationError("Replacement staging requires an active or stable source artifact.")
        if payload["skill_name"] != source_artifact.name or payload["surface"] != source_artifact.scope:
            raise ValidationError("Replacement proposal payload does not match source artifact.")
        source_lineage_id = proposal.evidence_snapshot.get("source_artifact_lineage_id")
        if not isinstance(source_lineage_id, str) or not source_lineage_id.strip():
            raise ValidationError("Replacement proposal requires source_artifact_lineage_id evidence.")
        if source_lineage_id != source_artifact.lineage_id:
            raise ValidationError("Replacement proposal lineage does not match source artifact.")

    @staticmethod
    def _validate_staged_replacement(*, staged: SkillArtifact, source_artifact: SkillArtifact) -> None:
        if staged.status != "staged":
            raise ValidationError("Replacement proposal staging must produce a staged artifact.")
        if staged.lineage_id != source_artifact.lineage_id:
            raise ValidationError("Staged replacement lineage does not match source artifact.")
        if staged.parent_artifact_id != source_artifact.id or staged.supersedes_artifact_id != source_artifact.id:
            raise ValidationError("Staged replacement is missing source artifact lineage links.")

    async def _audit_staged_replacement(
        self,
        artifact: SkillArtifact,
        *,
        source_artifact: SkillArtifact,
        proposal: ReflectionProposal,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type="skill.artifact.replacement_proposal_staged",
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "proposal_id": proposal.id,
                "proposal_source": proposal.evidence_snapshot.get("source"),
                "recommendation_id": proposal.evidence_snapshot.get("recommendation_id"),
                "source_skill_patch_request_id": proposal.evidence_snapshot.get("source_skill_patch_request_id"),
                "merge_source_artifact_ids": list(proposal.evidence_snapshot.get("merge_source_artifact_ids") or []),
                "source_artifact_id": source_artifact.id,
                "source_artifact_status": source_artifact.status,
                "lineage_id": artifact.lineage_id,
                "parent_artifact_id": artifact.parent_artifact_id,
                "supersedes_artifact_id": artifact.supersedes_artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

