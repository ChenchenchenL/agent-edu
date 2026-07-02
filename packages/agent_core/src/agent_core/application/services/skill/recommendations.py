"""Skill curator recommendation service.

This module handles curator recommendation creation, querying, accept,
dismiss, and action handoff to lifecycle, patch proposal, merge package,
or replacement staging services. Accept failure writes durable audit
and keeps the recommendation recoverable.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.constants import (
    CURATOR_ACTIVATION_REASON_CODES,
    CURATOR_ARCHIVE_REASON_CODES,
    CURATOR_DEACTIVATION_REASON_CODES,
    CURATOR_RESTORE_REASON_CODES,
    CURATOR_SUPPRESSION_REASON_CODES,
)
from agent_core.application.services.skill.lifecycle import SkillArtifactLifecycleService
from agent_core.application.services.skill.observability import refresh_skill_observability_metrics
from agent_core.application.services.skill.protocols import SkillPatchProposalService
from agent_core.domain.entities.skill import (
    SKILL_CURATOR_RECOMMENDATION_STATUSES,
    SKILL_CURATOR_RECOMMENDATION_TYPES,
    SKILL_CURATOR_RECOMMENDED_ACTIONS,
    SKILL_SCOPES,
    SKILL_USAGE_SURFACES,
    SkillArtifact,
    SkillCuratorRecommendation,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import (
    SkillArtifactRepository,
    SkillCuratorRecommendationRepository,
)
from agent_core.infrastructure.observability.metrics import observe_skill_curator_recommendation


class SkillCuratorRecommendationService:
    def __init__(
        self,
        *,
        recommendation_repository: SkillCuratorRecommendationRepository,
        artifact_repository: SkillArtifactRepository,
        lifecycle_service: SkillArtifactLifecycleService,
        audit_service: AuditService,
        proposal_service: SkillPatchProposalService | None = None,
    ) -> None:
        self._recommendation_repository = recommendation_repository
        self._artifact_repository = artifact_repository
        self._lifecycle_service = lifecycle_service
        self._proposal_service = proposal_service
        self._audit_service = audit_service

    async def create_recommendation(
        self,
        *,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
        created_by: str,
        artifact_id: str | None = None,
        skill_name: str | None = None,
        scope: str | None = None,
        surface: str | None = None,
        reason_note: str | None = None,
        evidence_snapshot: dict[str, Any] | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        related_artifact_ids: list[str] | None = None,
        source_job_id: str | None = None,
    ) -> SkillCuratorRecommendation:
        artifact: SkillArtifact | None = None
        if artifact_id is not None:
            artifact = await self._artifact_repository.get_by_id(artifact_id)
            if artifact is None:
                raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
            skill_name = artifact.name
            scope = artifact.scope
            surface = artifact.scope
            skill_version = artifact.version
            artifact_status = artifact.status
            lineage_id = artifact.lineage_id
        else:
            skill_version = None
            artifact_status = None
            lineage_id = None
        if skill_name is None or scope is None or surface is None:
            raise ValidationError("skill_name, scope, and surface are required without artifact_id.")

        recommendation = SkillCuratorRecommendation.build(
            artifact_id=artifact_id,
            skill_name=skill_name,
            skill_version=skill_version,
            artifact_status=artifact_status,
            lineage_id=lineage_id,
            scope=scope,
            surface=surface,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            reason_code=reason_code,
            reason_note=reason_note,
            evidence_snapshot=evidence_snapshot,
            metrics_snapshot=metrics_snapshot,
            related_artifact_ids=related_artifact_ids,
            source_job_id=source_job_id,
            created_by=created_by,
        )
        existing = await self._recommendation_repository.find_pending_duplicate(
            artifact_id=recommendation.artifact_id,
            skill_name=recommendation.skill_name,
            scope=recommendation.scope,
            surface=recommendation.surface,
            recommendation_type=recommendation.recommendation_type,
            recommended_action=recommendation.recommended_action,
            reason_code=recommendation.reason_code,
        )
        if existing is not None:
            observe_skill_curator_recommendation(
                recommendation_type=existing.recommendation_type,
                reason_code=existing.reason_code,
                event="reused",
            )
            await self._audit_recommendation(
                existing,
                event_type="skill.curator.recommendation.reused",
                actor=created_by,
                reason_code=reason_code,
                reason_note=reason_note,
            )
            return existing
        await self._recommendation_repository.create(recommendation)
        observe_skill_curator_recommendation(
            recommendation_type=recommendation.recommendation_type,
            reason_code=recommendation.reason_code,
            event="created",
        )
        await refresh_skill_observability_metrics(
            artifact_repository=self._artifact_repository,
            recommendation_repository=self._recommendation_repository,
        )
        await self._audit_recommendation(
            recommendation,
            event_type="skill.curator.recommendation.created",
            actor=created_by,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return recommendation

    async def list_recommendations(
        self,
        *,
        status: str | None = None,
        recommendation_type: str | None = None,
        recommended_action: str | None = None,
        artifact_id: str | None = None,
        skill_name: str | None = None,
        scope: str | None = None,
        surface: str | None = None,
        limit: int = 50,
    ) -> list[SkillCuratorRecommendation]:
        self._validate_optional_filter("status", status, SKILL_CURATOR_RECOMMENDATION_STATUSES)
        self._validate_optional_filter("recommendation_type", recommendation_type, SKILL_CURATOR_RECOMMENDATION_TYPES)
        self._validate_optional_filter("recommended_action", recommended_action, SKILL_CURATOR_RECOMMENDED_ACTIONS)
        self._validate_optional_filter("scope", scope, SKILL_SCOPES)
        self._validate_optional_filter("surface", surface, SKILL_USAGE_SURFACES)
        return await self._recommendation_repository.list_recommendations(
            status=status,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            artifact_id=artifact_id,
            skill_name=skill_name,
            scope=scope,
            surface=surface,
            limit=bounded_limit(limit),
        )

    async def get_recommendation(self, recommendation_id: str) -> SkillCuratorRecommendation:
        recommendation = await self._recommendation_repository.get_by_id(recommendation_id)
        if recommendation is None:
            raise NotFoundError(f"Skill curator recommendation '{recommendation_id}' was not found.")
        return recommendation

    async def accept_recommendation(
        self,
        *,
        recommendation_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillCuratorRecommendation:
        recommendation = await self.get_recommendation(recommendation_id)
        if recommendation.status == "accepted":
            await self._audit_recommendation(
                recommendation,
                event_type="skill.curator.recommendation.accept_reused",
                actor=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
            return recommendation
        if recommendation.status != "pending":
            raise ValidationError("Only pending skill curator recommendations can be accepted.")

        try:
            action_result = await self._execute_recommended_action(
                recommendation,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        except Exception as exc:
            await self._audit_recommendation(
                recommendation,
                event_type="skill.curator.recommendation.accept_failed",
                actor=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                durable=True,
                error_code=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        accepted = recommendation.accept(
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            action_result=action_result,
        )
        await self._recommendation_repository.update(accepted)
        observe_skill_curator_recommendation(
            recommendation_type=accepted.recommendation_type,
            reason_code=accepted.reason_code,
            event="accepted",
        )
        await refresh_skill_observability_metrics(
            artifact_repository=self._artifact_repository,
            recommendation_repository=self._recommendation_repository,
        )
        await self._audit_recommendation(
            accepted,
            event_type="skill.curator.recommendation.accepted",
            actor=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return accepted

    async def dismiss_recommendation(
        self,
        *,
        recommendation_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillCuratorRecommendation:
        recommendation = await self.get_recommendation(recommendation_id)
        if recommendation.status == "dismissed":
            await self._audit_recommendation(
                recommendation,
                event_type="skill.curator.recommendation.dismiss_reused",
                actor=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
            return recommendation
        if recommendation.status != "pending":
            raise ValidationError("Only pending skill curator recommendations can be dismissed.")
        dismissed = recommendation.dismiss(
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        await self._recommendation_repository.update(dismissed)
        observe_skill_curator_recommendation(
            recommendation_type=dismissed.recommendation_type,
            reason_code=dismissed.reason_code,
            event="dismissed",
        )
        await refresh_skill_observability_metrics(
            artifact_repository=self._artifact_repository,
            recommendation_repository=self._recommendation_repository,
        )
        await self._audit_recommendation(
            dismissed,
            event_type="skill.curator.recommendation.dismissed",
            actor=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return dismissed

    async def _execute_recommended_action(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> dict[str, Any]:
        if (
            recommendation.recommendation_type == "archive_candidate"
            and recommendation.recommended_action in {"none", "archive_deprecated"}
        ):
            if recommendation.artifact_id is None:
                raise ValidationError("Executable skill curator recommendations require artifact_id.")
            self._validate_action_reason_code(
                recommended_action="archive_deprecated",
                reason_code=reason_code,
                allowed=CURATOR_ARCHIVE_REASON_CODES,
            )
            artifact = await self._lifecycle_service.archive_deprecated(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
            return {
                "executed": True,
                "recommended_action": "archive_deprecated",
                "artifact_id": artifact.id,
                "artifact_status": artifact.status,
                "skill_name": artifact.name,
                "skill_version": artifact.version,
                "scope": artifact.scope,
            }
        if recommendation.recommended_action == "none":
            if recommendation.recommendation_type == "patch_needed":
                return await self._create_skill_patch_request(
                    recommendation,
                    operator_id=operator_id,
                )
            if recommendation.recommendation_type == "merge_candidate":
                return await self._create_skill_merge_package(
                    recommendation,
                    operator_id=operator_id,
                )
            return {"executed": False, "recommended_action": "none"}
        if recommendation.artifact_id is None:
            raise ValidationError("Executable skill curator recommendations require artifact_id.")
        if recommendation.recommended_action == "activate_staged":
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_ACTIVATION_REASON_CODES,
            )
            artifact = await self._lifecycle_service.activate_staged(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "stabilize_active":
            artifact = await self._lifecycle_service.stabilize_active(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "suppress_selectable":
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_SUPPRESSION_REASON_CODES,
            )
            artifact = await self._lifecycle_service.suppress_selectable(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "deactivate_active":
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_DEACTIVATION_REASON_CODES,
            )
            artifact = await self._lifecycle_service.deactivate_active(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "restore_suppressed":
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_RESTORE_REASON_CODES,
            )
            artifact = await self._lifecycle_service.restore_suppressed(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "replace_selectable":
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_DEACTIVATION_REASON_CODES,
            )
            artifact = await self._lifecycle_service.replace_selectable(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        elif recommendation.recommended_action == "archive_deprecated":
            if recommendation.recommendation_type != "archive_candidate":
                raise ValidationError("archive_deprecated requires archive_candidate recommendation.")
            self._validate_action_reason_code(
                recommended_action=recommendation.recommended_action,
                reason_code=reason_code,
                allowed=CURATOR_ARCHIVE_REASON_CODES,
            )
            artifact = await self._lifecycle_service.archive_deprecated(
                artifact_id=recommendation.artifact_id,
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
        else:
            raise ValidationError("Unsupported skill curator recommended_action.")
        result = {
            "executed": True,
            "recommended_action": recommendation.recommended_action,
            "artifact_id": artifact.id,
            "artifact_status": artifact.status,
            "skill_name": artifact.name,
            "skill_version": artifact.version,
            "scope": artifact.scope,
        }
        if recommendation.recommended_action in {"activate_staged", "replace_selectable"}:
            result["replacement_readiness"] = self._replacement_readiness_from_evidence(recommendation.evidence_snapshot)
        return result

    async def _create_skill_patch_request(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        if self._proposal_service is None:
            raise ValidationError("Reflection proposal service is not configured.")
        learner_goal_id, reflection_record_id = await self._skill_patch_anchor(recommendation)
        create = getattr(self._proposal_service, "create_skill_patch_request_from_recommendation", None)
        if create is None:
            raise ValidationError("Reflection proposal service does not support skill patch requests.")
        proposal = await create(
            recommendation_id=recommendation.id,
            artifact_id=recommendation.artifact_id,
            skill_name=recommendation.skill_name,
            skill_version=recommendation.skill_version,
            scope=recommendation.scope,
            surface=recommendation.surface,
            recommendation_reason_code=recommendation.reason_code,
            evidence_snapshot=dict(recommendation.evidence_snapshot),
            metrics_snapshot=dict(recommendation.metrics_snapshot),
            related_artifact_ids=list(recommendation.related_artifact_ids),
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            operator_id=operator_id,
        )
        return {
            "executed": True,
            "recommended_action": "create_skill_patch_proposal",
            "proposal_id": proposal.id,
            "proposal_type": proposal.proposal_type,
            "proposal_status": proposal.status,
            "artifact_id": recommendation.artifact_id,
            "skill_name": recommendation.skill_name,
            "skill_version": recommendation.skill_version,
            "scope": recommendation.scope,
        }

    async def _create_skill_merge_package(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        operator_id: str,
    ) -> dict[str, Any]:
        if self._proposal_service is None:
            raise ValidationError("Reflection proposal service is not configured.")
        learner_goal_id, reflection_record_id = await self._skill_patch_anchor(recommendation)
        create = getattr(self._proposal_service, "create_skill_merge_package_from_recommendation", None)
        if create is None:
            raise ValidationError("Reflection proposal service does not support skill merge proposals.")
        proposal = await create(
            recommendation_id=recommendation.id,
            artifact_id=recommendation.artifact_id,
            skill_name=recommendation.skill_name,
            skill_version=recommendation.skill_version,
            scope=recommendation.scope,
            surface=recommendation.surface,
            recommendation_reason_code=recommendation.reason_code,
            evidence_snapshot=dict(recommendation.evidence_snapshot),
            metrics_snapshot=dict(recommendation.metrics_snapshot),
            related_artifact_ids=list(recommendation.related_artifact_ids),
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            operator_id=operator_id,
        )
        return {
            "executed": True,
            "recommended_action": "create_skill_merge_proposal",
            "proposal_id": proposal.id,
            "proposal_type": proposal.proposal_type,
            "proposal_status": proposal.status,
            "artifact_id": recommendation.artifact_id,
            "skill_name": recommendation.skill_name,
            "skill_version": recommendation.skill_version,
            "scope": recommendation.scope,
            "merge_source_artifact_ids": list(recommendation.related_artifact_ids),
        }

    async def _skill_patch_anchor(self, recommendation: SkillCuratorRecommendation) -> tuple[str, str]:
        evidence = dict(recommendation.evidence_snapshot)
        learner_goal_id = self._optional_str(evidence.get("learner_goal_id"))
        reflection_record_id = self._optional_str(evidence.get("reflection_record_id"))
        source_proposal_id = self._optional_str(evidence.get("source_proposal_id"))
        artifact: SkillArtifact | None = None
        if recommendation.artifact_id is not None:
            artifact = await self._artifact_repository.get_by_id(recommendation.artifact_id)
            if artifact is None:
                raise NotFoundError(f"Skill artifact '{recommendation.artifact_id}' was not found.")
            source_proposal_id = source_proposal_id or artifact.source_proposal_id
        if (learner_goal_id is None or reflection_record_id is None) and source_proposal_id is not None:
            get_proposal = getattr(self._proposal_service, "get", None) if self._proposal_service is not None else None
            if get_proposal is not None:
                try:
                    proposal = await get_proposal(source_proposal_id)
                except NotFoundError:
                    proposal = None
                if proposal is not None:
                    learner_goal_id = learner_goal_id or proposal.learner_goal_id
                    reflection_record_id = reflection_record_id or proposal.reflection_record_id
        if reflection_record_id is None and artifact is not None and artifact.source_reflection_ids:
            reflection_record_id = artifact.source_reflection_ids[0]
        if learner_goal_id is None or reflection_record_id is None:
            raise ValidationError("Skill patch recommendation requires learner_goal_id and reflection_record_id.")
        return learner_goal_id, reflection_record_id

    @staticmethod
    def _optional_str(value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    async def _audit_recommendation(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        event_type: str,
        actor: str,
        reason_code: str,
        reason_note: str | None,
        durable: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        record = self._audit_service.record_durable if durable else self._audit_service.record
        await record(
            event_type=event_type,
            resource_type="skill_curator_recommendation",
            resource_id=recommendation.id,
            actor=actor,
            event_data={
                "recommendation_id": recommendation.id,
                "artifact_id": recommendation.artifact_id,
                "skill_name": recommendation.skill_name,
                "skill_version": recommendation.skill_version,
                "artifact_status": recommendation.artifact_status,
                "lineage_id": recommendation.lineage_id,
                "scope": recommendation.scope,
                "surface": recommendation.surface,
                "recommendation_type": recommendation.recommendation_type,
                "recommended_action": recommendation.recommended_action,
                "status": recommendation.status,
                "source_job_id": recommendation.source_job_id,
                "created_by": recommendation.created_by,
                "accepted_by": recommendation.accepted_by,
                "dismissed_by": recommendation.dismissed_by,
                "decision_reason_code": recommendation.decision_reason_code,
                "action_result": dict(recommendation.action_result),
                "operator_id": actor,
                "reason_code": reason_code,
                "reason_note": reason_note,
                "error_code": error_code,
                "error": error_message,
            },
        )

    @staticmethod
    def _validate_optional_filter(name: str, value: str | None, allowed: set[str]) -> None:
        if value is not None and value not in allowed:
            raise ValidationError(f"Unsupported skill curator recommendation {name}.")

    @staticmethod
    def _validate_action_reason_code(*, recommended_action: str, reason_code: str, allowed: set[str]) -> None:
        if reason_code not in allowed:
            raise ValidationError(f"Unsupported reason_code for {recommended_action}.")

    @staticmethod
    def _replacement_readiness_from_evidence(evidence_snapshot: dict[str, Any]) -> dict[str, Any] | None:
        replacement_readiness = evidence_snapshot.get("replacement_readiness")
        if isinstance(replacement_readiness, dict):
            return dict(replacement_readiness)
        source_anchor = evidence_snapshot.get("source_anchor")
        rollout_evidence = evidence_snapshot.get("rollout_evidence")
        usage_evidence = evidence_snapshot.get("usage_evidence")
        activate_readiness = evidence_snapshot.get("activate_readiness")
        replace_readiness = evidence_snapshot.get("replace_readiness")
        thresholds = evidence_snapshot.get("thresholds")
        checked_at = evidence_snapshot.get("checked_at")
        if not all(
            isinstance(value, dict)
            for value in (source_anchor, rollout_evidence, usage_evidence, activate_readiness, replace_readiness)
        ):
            return None
        payload: dict[str, Any] = {
            "proposal_source": evidence_snapshot.get("proposal_source"),
            "recommended_action": evidence_snapshot.get("ready_action"),
            "source_anchor": dict(source_anchor),
            "rollout_evidence": dict(rollout_evidence),
            "usage_evidence": dict(usage_evidence),
            "activate_readiness": dict(activate_readiness),
            "replace_readiness": dict(replace_readiness),
            "checked_at": checked_at,
        }
        if isinstance(thresholds, dict):
            payload["thresholds"] = dict(thresholds)
        return payload

