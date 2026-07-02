"""Skill artifact governed lifecycle service.

This module is the single entry point for skill artifact state transitions:
stage, activate, replace, stabilize, deactivate, suppress, restore, archive.

All high-risk state changes require audit. Activate and replace operations
check replacement readiness before proceeding. The service does not absorb
curator job scanning logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.skill.candidates import SkillCandidateService
from agent_core.application.services.skill.constants import (
    ACTIVE_SKILL_REFERENCE_STATUSES,
    STABLE_MAX_NEGATIVE_USAGE_RATE,
    STABLE_MIN_SUCCESSFUL_USAGE_COUNT,
    STABLE_NEGATIVE_USAGE_STATUSES,
    STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT,
    STABLE_SUCCESSFUL_USAGE_STATUSES,
)
from agent_core.application.services.skill.observability import refresh_skill_observability_metrics
from agent_core.application.services.skill.readiness import (
    SkillReplacementReadiness,
    SkillReplacementReadinessService,
    matches_rollout_metadata,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.constants import SkillArtifactStatus
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects import require_non_empty
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    SkillArtifactRepository,
    SkillUsageEventRepository,
)


class SkillArtifactLifecycleService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        rollout_repository: ReflectionProposalRolloutRepository,
        rollout_observation_repository: ReflectionProposalRolloutObservationRepository,
        goal_skill_binding_repository: GoalSkillBindingRepository,
        usage_repository: SkillUsageEventRepository,
        skill_registry: SkillRegistry,
        audit_service: AuditService,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._rollout_repository = rollout_repository
        self._rollout_observation_repository = rollout_observation_repository
        self._goal_skill_binding_repository = goal_skill_binding_repository
        self._usage_repository = usage_repository
        self._skill_registry = skill_registry
        self._audit_service = audit_service

    async def stage_candidate(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == SkillArtifactStatus.STAGED.value:
            await self._audit_stage(
                artifact,
                event_type="skill.artifact.stage_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                evaluation_id=None,
                score_delta=None,
            )
            return artifact
        if artifact.status != SkillArtifactStatus.CANDIDATE.value:
            raise ValidationError("Only candidate skill artifacts can be staged.")
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact staging requires a source proposal.")

        proposal = await self._proposal_repository.get_by_id(artifact.source_proposal_id)
        if proposal is None:
            raise ValidationError("Skill artifact staging requires an existing source proposal.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = SkillCandidateService._validated_payload(proposal)
        self._validate_artifact_against_source(artifact, payload)

        staged = artifact.mark_staged()
        await self._artifact_repository.update(staged)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_stage(
            staged,
            event_type="skill.artifact.staged",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            evaluation_id=evaluation.id if evaluation else None,
            score_delta=evaluation.score_delta if evaluation else None,
        )
        return staged

    async def activate_staged(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_activation(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == SkillArtifactStatus.ACTIVE.value:
            await self._audit_activate(
                artifact,
                event_type="skill.artifact.activate_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                evaluation_id=None,
                score_delta=None,
                rollout_id=None,
                binding_id=None,
                observation_id=None,
                usage_event_ids=[],
                replacement_readiness=None,
            )
            return artifact
        if artifact.status != SkillArtifactStatus.STAGED.value:
            raise ValidationError("Only staged skill artifacts can be activated.")
        if not self._skill_registry.has_skill(artifact.name):
            raise ValidationError("Skill artifact activation requires an enabled skill name.")

        replacement_readiness = await self._replacement_readiness_service().evaluate_artifact(artifact)
        if replacement_readiness.activate_readiness.status != "not_applicable":
            self._require_replacement_readiness(
                readiness=replacement_readiness,
                action="activate_staged",
            )

        existing_selectable = await self._artifact_repository.get_selectable_by_name_scope(
            name=artifact.name,
            scope=artifact.scope,
        )
        if existing_selectable is not None and existing_selectable.id != artifact.id:
            raise ValidationError("A selectable skill artifact already exists for this name and scope.")
        proposal, evaluation, rollout, binding, observation, usage_events = await self._activation_evidence(artifact)
        usage_event_ids = (
            replacement_readiness.usage_evidence["successful_usage_event_ids"]
            if replacement_readiness.activate_readiness.status == "ready"
            else [item.id for item in usage_events]
        )
        observation_id = (
            replacement_readiness.rollout_evidence["latest_observation_id"]
            if replacement_readiness.activate_readiness.status == "ready"
            else observation.id
        )

        activated = artifact.mark_active(operator_id=operator_id)
        await self._artifact_repository.update(activated)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_activate(
            activated,
            event_type="skill.artifact.activated",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            evaluation_id=evaluation.id if evaluation else None,
            score_delta=evaluation.score_delta if evaluation else None,
            rollout_id=rollout.id,
            binding_id=binding.id,
            observation_id=observation_id,
            usage_event_ids=list(usage_event_ids),
            replacement_readiness=replacement_readiness,
        )
        return activated

    async def replace_selectable(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_replacement(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == "active" and artifact.supersedes_artifact_id is not None:
            superseded = await self._artifact_repository.get_by_id(artifact.supersedes_artifact_id)
            if superseded is not None and superseded.status == SkillArtifactStatus.DEPRECATED.value:
                await self._audit_replace(
                    artifact,
                    event_type="skill.artifact.replace_reused",
                    operator_id=operator_id,
                    reason_code=reason_code,
                    reason_note=reason_note,
                    replaced_artifact=superseded,
                    replaced_previous_status=superseded.status,
                    evaluation_id=None,
                    score_delta=None,
                    rollout_id=None,
                    binding_id=None,
                    observation_id=None,
                    usage_event_ids=[],
                    replacement_readiness=None,
                )
                return artifact
        if artifact.status != SkillArtifactStatus.STAGED.value:
            raise ValidationError("Only staged skill artifacts can replace a selectable artifact.")
        if not self._skill_registry.has_skill(artifact.name):
            raise ValidationError("Skill artifact replacement requires an enabled skill name.")

        replacement_readiness = await self._replacement_readiness_service().evaluate_artifact(artifact)
        if replacement_readiness.replace_readiness.status != "not_applicable":
            self._require_replacement_readiness(
                readiness=replacement_readiness,
                action="replace_selectable",
            )
        proposal, evaluation, rollout, binding, observation, usage_events = await self._activation_evidence(artifact)
        existing_selectable = await self._get_selectable_for_replacement(name=artifact.name, scope=artifact.scope)
        if existing_selectable is None:
            raise ValidationError("Skill artifact replacement requires an existing selectable artifact.")
        if existing_selectable.id == artifact.id:
            raise ValidationError("A skill artifact cannot replace itself.")
        if existing_selectable.status not in {
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value
        }:
            raise ValidationError("Only active or stable skill artifacts can be superseded.")
        if replacement_readiness.replace_readiness.status != "not_applicable":
            source_anchor_id = replacement_readiness.source_anchor.get("source_artifact_id")
            source_anchor_id = require_non_empty(source_anchor_id, "source_anchor_id") if isinstance(source_anchor_id, str) else ""
            if not source_anchor_id:
                raise ValidationError("Governed replacement requires a staged source anchor.")
            if existing_selectable.id != source_anchor_id:
                raise ValidationError(
                    "Governed replacement requires the staged source artifact to remain current selectable."
                )

        replaced_previous_status = existing_selectable.status
        deactivated = existing_selectable.mark_deprecated(operator_id=operator_id)
        replacement = artifact.mark_replacement_active(
            operator_id=operator_id,
            superseded_artifact=existing_selectable,
        )
        await self._artifact_repository.update(deactivated)
        await self._audit_deactivate(
            deactivated,
            event_type="skill.artifact.deactivated",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            previous_status=replaced_previous_status,
            superseded_by_artifact_id=replacement.id,
        )
        await self._artifact_repository.update(replacement)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_replace(
            replacement,
            event_type="skill.artifact.replaced",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            replaced_artifact=deactivated,
            replaced_previous_status=replaced_previous_status,
            evaluation_id=evaluation.id if evaluation else None,
            score_delta=evaluation.score_delta if evaluation else None,
            rollout_id=rollout.id,
            binding_id=binding.id,
            observation_id=(
                str(replacement_readiness.rollout_evidence["latest_observation_id"])
                if replacement_readiness.replace_readiness.status == "ready"
                else observation.id
            ),
            usage_event_ids=(
                list(replacement_readiness.usage_evidence["successful_usage_event_ids"])
                if replacement_readiness.replace_readiness.status == "ready"
                else [item.id for item in usage_events]
            ),
            replacement_readiness=(
                replacement_readiness if replacement_readiness.replace_readiness.status == "ready" else None
            ),
        )
        return replacement

    async def stabilize_active(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == SkillArtifactStatus.STABLE.value:
            await self._audit_stabilize(
                artifact,
                event_type="skill.artifact.stabilize_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                rollout_id=None,
                binding_id=None,
                observation_ids=[],
                usage_event_ids=[],
                successful_usage_count=None,
                negative_usage_count=None,
                negative_usage_rate=None,
                evidence_started_at=None,
            )
            return artifact
        if artifact.status != SkillArtifactStatus.ACTIVE.value:
            raise ValidationError("Only active skill artifacts can be stabilized.")
        if not self._skill_registry.has_skill(artifact.name):
            raise ValidationError("Skill artifact stabilization requires an enabled skill name.")

        existing_selectable = await self._artifact_repository.get_selectable_by_name_scope(
            name=artifact.name,
            scope=artifact.scope,
        )
        if existing_selectable is not None and existing_selectable.id != artifact.id:
            raise ValidationError("A selectable skill artifact already exists for this name and scope.")
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact stabilization requires a source proposal.")

        proposal = await self._proposal_repository.get_by_id(artifact.source_proposal_id)
        if proposal is None:
            raise ValidationError("Skill artifact stabilization requires an existing source proposal.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = SkillCandidateService._validated_payload(proposal)
        self._validate_artifact_against_source(artifact, payload)
        rollout, binding = await self._validate_stabilization_rollout_evidence(artifact)
        evidence_started_at = artifact.approved_at or artifact.updated_at
        observations = await self._stable_promote_observations(
            artifact=artifact,
            rollout=rollout,
            evidence_started_at=evidence_started_at,
        )
        successful_usage_events, negative_usage_events, negative_usage_rate = await self._stable_usage_events(
            artifact=artifact,
            proposal_id=proposal.id,
            rollout_id=rollout.id,
            binding_id=binding.id,
            learner_goal_id=rollout.learner_goal_id,
            evidence_started_at=evidence_started_at,
        )

        stable = artifact.mark_stable(operator_id=operator_id)
        await self._artifact_repository.update(stable)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_stabilize(
            stable,
            event_type="skill.artifact.stabilized",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            rollout_id=rollout.id,
            binding_id=binding.id,
            observation_ids=[item.id for item in observations],
            usage_event_ids=[item.id for item in successful_usage_events],
            successful_usage_count=len(successful_usage_events),
            negative_usage_count=len(negative_usage_events),
            negative_usage_rate=negative_usage_rate,
            evidence_started_at=evidence_started_at,
        )
        return stable

    async def deactivate_active(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_deactivation(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == SkillArtifactStatus.DEPRECATED.value:
            raise ValidationError("Skill artifact is already deprecated.")
        if artifact.status not in {
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value
        }:
            raise ValidationError("Only active or stable skill artifacts can be deactivated.")
        await self._validate_no_active_runtime_references(artifact)

        deactivated = artifact.mark_deprecated(operator_id=operator_id)
        await self._artifact_repository.update(deactivated)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_deactivate(
            deactivated,
            event_type="skill.artifact.deactivated",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return deactivated

    async def suppress_selectable(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_suppression(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == "suppressed":
            await self._audit_suppression(
                artifact,
                event_type="skill.artifact.suppress_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                previous_status=artifact.suppressed_previous_status,
            )
            return artifact
        if artifact.status not in {
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value
        }:
            raise ValidationError("Only active or stable skill artifacts can be suppressed.")

        existing_suppressed = await self._get_suppressed_for_suppression(name=artifact.name, scope=artifact.scope)
        if existing_suppressed is not None and existing_suppressed.id != artifact.id:
            raise ValidationError("A suppressed skill artifact already exists for this name and scope.")

        previous_status = artifact.status
        suppressed = artifact.mark_suppressed(
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        await self._artifact_repository.update(suppressed)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_suppression(
            suppressed,
            event_type="skill.artifact.suppressed",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            previous_status=previous_status,
        )
        return suppressed

    async def restore_suppressed(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_suppression(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status in {
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value
        } and artifact.suppressed_previous_status is None:
            await self._audit_restore(
                artifact,
                event_type="skill.artifact.restore_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                previous_status=artifact.status,
                suppressed_artifact=None,
            )
            return artifact
        if artifact.status != "suppressed":
            raise ValidationError("Only suppressed skill artifacts can be restored.")

        existing_selectable = await self._artifact_repository.get_selectable_by_name_scope(
            name=artifact.name,
            scope=artifact.scope,
        )
        if existing_selectable is not None and existing_selectable.id != artifact.id:
            raise ValidationError("A selectable skill artifact already exists for this name and scope.")

        previous_status = artifact.status
        restored = artifact.restore_suppressed(operator_id=operator_id)
        await self._artifact_repository.update(restored)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_restore(
            restored,
            event_type="skill.artifact.restored",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            previous_status=previous_status,
            suppressed_artifact=artifact,
        )
        return restored

    async def archive_deprecated(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        operator_id = require_non_empty(operator_id, "operator_id")
        reason_code = require_non_empty(reason_code, "reason_code")

        artifact = await self._get_artifact_for_archive(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == SkillArtifactStatus.ARCHIVED.value:
            await self._audit_archive(
                artifact,
                event_type="skill.artifact.archive_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                previous_status=artifact.status,
            )
            return artifact
        if artifact.status != SkillArtifactStatus.DEPRECATED.value:
            raise ValidationError("Only deprecated skill artifacts can be archived.")

        previous_status = artifact.status
        archived = artifact.mark_archived(operator_id=operator_id)
        await self._artifact_repository.update(archived)
        await refresh_skill_observability_metrics(artifact_repository=self._artifact_repository)
        await self._audit_archive(
            archived,
            event_type="skill.artifact.archived",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            previous_status=previous_status,
        )
        return archived

    async def _get_artifact_for_deactivation(self, artifact_id: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_by_id_for_update", None)
        if lock_getter is not None:
            return await lock_getter(artifact_id)
        return await self._artifact_repository.get_by_id(artifact_id)

    async def _get_artifact_for_activation(self, artifact_id: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_by_id_for_update", None)
        if lock_getter is not None:
            return await lock_getter(artifact_id)
        return await self._artifact_repository.get_by_id(artifact_id)

    async def _get_artifact_for_suppression(self, artifact_id: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_by_id_for_update", None)
        if lock_getter is not None:
            return await lock_getter(artifact_id)
        return await self._artifact_repository.get_by_id(artifact_id)

    async def _get_artifact_for_replacement(self, artifact_id: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_by_id_for_update", None)
        if lock_getter is not None:
            return await lock_getter(artifact_id)
        return await self._artifact_repository.get_by_id(artifact_id)

    async def _get_artifact_for_archive(self, artifact_id: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_by_id_for_update", None)
        if lock_getter is not None:
            return await lock_getter(artifact_id)
        return await self._artifact_repository.get_by_id(artifact_id)

    async def _get_selectable_for_replacement(self, *, name: str, scope: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_selectable_by_name_scope_for_update", None)
        if lock_getter is not None:
            return await lock_getter(name=name, scope=scope)
        return await self._artifact_repository.get_selectable_by_name_scope(name=name, scope=scope)

    async def _get_suppressed_for_suppression(self, *, name: str, scope: str) -> SkillArtifact | None:
        lock_getter = getattr(self._artifact_repository, "get_suppressed_by_name_scope_for_update", None)
        if lock_getter is not None:
            return await lock_getter(name=name, scope=scope)
        return await self._artifact_repository.get_suppressed_by_name_scope(name=name, scope=scope)

    def _replacement_readiness_service(self) -> SkillReplacementReadinessService:
        return SkillReplacementReadinessService(
            artifact_repository=self._artifact_repository,
            proposal_repository=self._proposal_repository,
            rollout_repository=self._rollout_repository,
            rollout_observation_repository=self._rollout_observation_repository,
            goal_skill_binding_repository=self._goal_skill_binding_repository,
            usage_repository=self._usage_repository,
        )

    @staticmethod
    def _require_replacement_readiness(
        *,
        readiness: SkillReplacementReadiness,
        action: str,
    ) -> None:
        action_readiness = (
            readiness.activate_readiness if action == "activate_staged" else readiness.replace_readiness
        )
        if action_readiness.status == "ready":
            return
        joined = ", ".join(action_readiness.reason_codes) if action_readiness.reason_codes else "unknown"
        raise ValidationError(f"Governed replacement {action} is blocked: {joined}.")

    async def _validate_no_active_runtime_references(self, artifact: SkillArtifact) -> None:
        if artifact.source_proposal_id is None:
            return
        active_bindings = await self._goal_skill_binding_repository.list_by_proposal_and_statuses(
            artifact.source_proposal_id,
            statuses=ACTIVE_SKILL_REFERENCE_STATUSES,
        )
        if active_bindings:
            raise ValidationError("Cannot deactivate skill artifact while active goal skill bindings exist.")
        active_rollouts = await self._rollout_repository.list_by_proposal_and_statuses(
            artifact.source_proposal_id,
            statuses=ACTIVE_SKILL_REFERENCE_STATUSES,
        )
        if active_rollouts:
            raise ValidationError("Cannot deactivate skill artifact while active rollouts exist.")

    def _validate_artifact_against_source(self, artifact: SkillArtifact, payload: dict[str, object]) -> None:
        if not artifact.source_reflection_ids:
            raise ValidationError("Skill artifact staging requires source reflections.")
        if artifact.name != payload["skill_name"] or artifact.scope != payload["surface"]:
            raise ValidationError("Skill artifact does not match its source proposal.")
        if artifact.runtime_directives != payload["runtime_directives"]:
            raise ValidationError("Skill artifact runtime_directives do not match its source proposal.")
        if artifact.tool_plan != payload["tool_plan"]:
            raise ValidationError("Skill artifact tool_plan does not match its source proposal.")
        if artifact.definition.get("match_rules") != payload["match_rules"]:
            raise ValidationError("Skill artifact match_rules do not match its source proposal.")
        if artifact.definition.get("scoring_contract") != payload["scoring_contract"]:
            raise ValidationError("Skill artifact scoring_contract does not match its source proposal.")

        contract = artifact.compatibility_contract
        surfaces = contract.get("surfaces")
        if contract.get("dynamic_execution") is not False:
            raise ValidationError("Skill artifact staging requires static compatibility contract execution.")
        if not isinstance(surfaces, list) or not all(isinstance(item, str) for item in surfaces):
            raise ValidationError("Skill artifact compatibility contract surfaces are invalid.")
        if surfaces != [artifact.scope]:
            raise ValidationError("In V2, artifact surfaces must exactly match artifact scope.")
        implementation_binding = contract.get("implementation_binding")
        if not isinstance(implementation_binding, str) or not implementation_binding.strip():
            raise ValidationError("Skill artifact implementation binding must be a non-empty string.")
        if not self._skill_registry.has_runtime_handler(implementation_binding):
            raise ValidationError("Skill artifact implementation binding must reference a registered runtime handler.")
        if not self._skill_registry.supports_runtime_handler(implementation_binding, surface=artifact.scope):
            raise ValidationError("Skill artifact implementation binding must support the artifact scope.")

    async def _activation_evidence(
        self,
        artifact: SkillArtifact,
    ) -> tuple[
        ReflectionProposal,
        ReflectionProposalEvaluation | None,
        ReflectionProposalRollout,
        GoalSkillBinding,
        ReflectionProposalRolloutObservation,
        list[SkillUsageEvent],
    ]:
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact activation requires a source proposal.")
        proposal = await self._proposal_repository.get_by_id(artifact.source_proposal_id)
        if proposal is None:
            raise ValidationError("Skill artifact activation requires an existing source proposal.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = SkillCandidateService._validated_payload(proposal)
        self._validate_artifact_against_source(artifact, payload)
        rollout, binding, observation = await self._validate_activation_rollout_evidence(artifact)
        usage_events = await self._activation_usage_events(
            artifact=artifact,
            proposal_id=proposal.id,
            rollout_id=rollout.id,
            binding_id=binding.id,
            learner_goal_id=rollout.learner_goal_id,
            activated_at=rollout.activated_at,
        )
        if not usage_events:
            raise ValidationError("Skill artifact activation requires successful attributed rollout usage.")
        return proposal, evaluation, rollout, binding, observation, usage_events

    async def _validate_activation_rollout_evidence(
        self,
        artifact: SkillArtifact,
    ) -> tuple[ReflectionProposalRollout, GoalSkillBinding, ReflectionProposalRolloutObservation]:
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact activation requires a source proposal.")
        rollout = await self._rollout_repository.get_by_proposal(artifact.source_proposal_id)
        if rollout is None:
            raise ValidationError("Skill artifact activation requires rollout evidence.")
        if rollout.status != "rolled_out":
            raise ValidationError("Skill artifact activation requires a promoted rollout.")
        if rollout.surface != artifact.scope:
            raise ValidationError("Skill artifact rollout surface does not match artifact scope.")
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is None:
            raise ValidationError("Skill artifact activation requires a rollout skill binding.")
        if binding.status != "rolled_out":
            raise ValidationError("Skill artifact activation requires a promoted skill binding.")
        if (
            binding.proposal_id != artifact.source_proposal_id
            or binding.rollout_id != rollout.id
            or binding.surface != artifact.scope
        ):
            raise ValidationError("Skill artifact activation rollout binding does not match artifact.")
        if rollout.latest_observation_id is None:
            raise ValidationError("Skill artifact activation requires rollout observation evidence.")
        observation = await self._rollout_observation_repository.get_by_id(rollout.latest_observation_id)
        if observation is None:
            raise ValidationError("Skill artifact activation requires existing rollout observation evidence.")
        if (
            observation.rollout_id != rollout.id
            or observation.proposal_id != artifact.source_proposal_id
            or observation.surface != artifact.scope
        ):
            raise ValidationError("Skill artifact activation observation does not match rollout.")
        if observation.recommendation != "promote":
            raise ValidationError("Skill artifact activation requires promote rollout observation.")
        return rollout, binding, observation

    async def _validate_stabilization_rollout_evidence(
        self,
        artifact: SkillArtifact,
    ) -> tuple[ReflectionProposalRollout, GoalSkillBinding]:
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact stabilization requires a source proposal.")
        rollout = await self._rollout_repository.get_by_proposal(artifact.source_proposal_id)
        if rollout is None:
            raise ValidationError("Skill artifact stabilization requires rollout evidence.")
        if rollout.status != "rolled_out":
            raise ValidationError("Skill artifact stabilization requires a promoted rollout.")
        if rollout.surface != artifact.scope:
            raise ValidationError("Skill artifact rollout surface does not match artifact scope.")
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is None:
            raise ValidationError("Skill artifact stabilization requires a rollout skill binding.")
        if binding.status != "rolled_out":
            raise ValidationError("Skill artifact stabilization requires a promoted skill binding.")
        if (
            binding.proposal_id != artifact.source_proposal_id
            or binding.rollout_id != rollout.id
            or binding.surface != artifact.scope
        ):
            raise ValidationError("Skill artifact stabilization rollout binding does not match artifact.")
        return rollout, binding

    async def _stable_promote_observations(
        self,
        *,
        artifact: SkillArtifact,
        rollout: ReflectionProposalRollout,
        evidence_started_at: datetime,
    ) -> list[ReflectionProposalRolloutObservation]:
        observations = await self._rollout_observation_repository.list_by_rollout(rollout.id)
        relevant = [
            item
            for item in observations
            if item.created_at >= evidence_started_at
            and item.rollout_id == rollout.id
            and item.proposal_id == artifact.source_proposal_id
            and item.surface == artifact.scope
        ]
        relevant = sorted(relevant, key=lambda item: (item.created_at, item.id), reverse=True)
        if len(relevant) < STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT:
            raise ValidationError("Skill artifact stabilization requires more rollout observations.")
        recent = relevant[:STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT]
        if any(item.recommendation != "promote" for item in recent):
            raise ValidationError("Skill artifact stabilization requires consecutive promote observations.")
        return recent

    async def _stable_usage_events(
        self,
        *,
        artifact: SkillArtifact,
        proposal_id: str,
        rollout_id: str,
        binding_id: str,
        learner_goal_id: str,
        evidence_started_at: datetime,
    ) -> tuple[list[SkillUsageEvent], list[SkillUsageEvent], float]:
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            learner_goal_id=learner_goal_id,
            surface=artifact.scope,
            created_at_from=evidence_started_at,
            limit=200,
        )
        matched: list[SkillUsageEvent] = []
        successful: list[SkillUsageEvent] = []
        negative: list[SkillUsageEvent] = []
        for event in events:
            if event.skill_name != artifact.name or event.surface != artifact.scope:
                continue
            rollout_metadata = event.metadata.get("skill_package_rollout")
            if not isinstance(rollout_metadata, dict):
                continue
            if not matches_rollout_metadata(
                rollout_metadata,
                proposal_id=proposal_id,
                rollout_id=rollout_id,
                binding_id=binding_id,
                skill_name=artifact.name,
                surface=artifact.scope,
            ):
                continue
            matched.append(event)
            if event.outcome_status in STABLE_SUCCESSFUL_USAGE_STATUSES:
                successful.append(event)
            elif event.outcome_status in STABLE_NEGATIVE_USAGE_STATUSES:
                negative.append(event)
        if len(successful) < STABLE_MIN_SUCCESSFUL_USAGE_COUNT:
            raise ValidationError("Skill artifact stabilization requires more successful rollout usage.")
        negative_usage_rate = len(negative) / len(matched) if matched else 0.0
        if negative_usage_rate > STABLE_MAX_NEGATIVE_USAGE_RATE:
            raise ValidationError("Skill artifact stabilization negative usage rate is too high.")
        return successful, negative, negative_usage_rate

    async def _activation_usage_events(
        self,
        *,
        artifact: SkillArtifact,
        proposal_id: str,
        rollout_id: str,
        binding_id: str,
        learner_goal_id: str,
        activated_at,
    ) -> list[SkillUsageEvent]:
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            learner_goal_id=learner_goal_id,
            surface=artifact.scope,
            created_at_from=activated_at,
            limit=200,
        )
        matching: list[SkillUsageEvent] = []
        for event in events:
            if event.skill_name != artifact.name or event.surface != artifact.scope:
                continue
            if event.outcome_status not in {"completed", "partial_success"}:
                continue
            rollout_metadata = event.metadata.get("skill_package_rollout")
            if not isinstance(rollout_metadata, dict):
                continue
            if matches_rollout_metadata(
                rollout_metadata,
                proposal_id=proposal_id,
                rollout_id=rollout_id,
                binding_id=binding_id,
                skill_name=artifact.name,
                surface=artifact.scope,
            ):
                matching.append(event)
        return matching


    @staticmethod
    def _replacement_readiness_payload(readiness: SkillReplacementReadiness | None) -> dict[str, Any] | None:
        if readiness is None:
            return None
        return {
            "proposal_source": readiness.proposal_source,
            "recommended_action": readiness.recommended_action,
            "source_anchor": dict(readiness.source_anchor),
            "rollout_evidence": dict(readiness.rollout_evidence),
            "usage_evidence": dict(readiness.usage_evidence),
            "activate_readiness": {
                "status": readiness.activate_readiness.status,
                "reason_codes": list(readiness.activate_readiness.reason_codes),
            },
            "replace_readiness": {
                "status": readiness.replace_readiness.status,
                "reason_codes": list(readiness.replace_readiness.reason_codes),
            },
            "thresholds": {
                "promote_observation_min": readiness.thresholds.promote_observation_min,
                "successful_usage_min": readiness.thresholds.successful_usage_min,
                "max_negative_usage_rate": readiness.thresholds.max_negative_usage_rate,
            },
            "checked_at": readiness.checked_at.isoformat(),
        }

    async def _audit_stage(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        evaluation_id: str | None,
        score_delta: float | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "evaluation_id": evaluation_id,
                "score_delta": score_delta,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_activate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        evaluation_id: str | None,
        score_delta: float | None,
        rollout_id: str | None,
        binding_id: str | None,
        observation_id: str | None,
        usage_event_ids: list[str],
        replacement_readiness: SkillReplacementReadiness | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "evaluation_id": evaluation_id,
                "score_delta": score_delta,
                "rollout_id": rollout_id,
                "binding_id": binding_id,
                "observation_id": observation_id,
                "usage_event_ids": list(usage_event_ids),
                "replacement_readiness": self._replacement_readiness_payload(replacement_readiness),
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_stabilize(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        rollout_id: str | None,
        binding_id: str | None,
        observation_ids: list[str],
        usage_event_ids: list[str],
        successful_usage_count: int | None,
        negative_usage_count: int | None,
        negative_usage_rate: float | None,
        evidence_started_at: datetime | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "rollout_id": rollout_id,
                "binding_id": binding_id,
                "observation_ids": list(observation_ids),
                "usage_event_ids": list(usage_event_ids),
                "successful_usage_count": successful_usage_count,
                "negative_usage_count": negative_usage_count,
                "negative_usage_rate": negative_usage_rate,
                "evidence_started_at": evidence_started_at.isoformat() if evidence_started_at is not None else None,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_deactivate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        previous_status: str | None = None,
        superseded_by_artifact_id: str | None = None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "previous_status": previous_status,
                "source_proposal_id": artifact.source_proposal_id,
                "superseded_by_artifact_id": superseded_by_artifact_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_suppression(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        previous_status: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "previous_status": previous_status,
                "source_proposal_id": artifact.source_proposal_id,
                "suppressed_reason_code": artifact.suppressed_reason_code,
                "suppressed_reason_note": artifact.suppressed_reason_note,
                "suppressed_by": artifact.suppressed_by,
                "suppressed_at": artifact.suppressed_at.isoformat() if artifact.suppressed_at is not None else None,
                "suppressed_previous_status": artifact.suppressed_previous_status,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_restore(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        previous_status: str | None,
        suppressed_artifact: SkillArtifact | None,
    ) -> None:
        suppression_source = suppressed_artifact or artifact
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "previous_status": previous_status,
                "source_proposal_id": artifact.source_proposal_id,
                "suppressed_reason_code": suppression_source.suppressed_reason_code,
                "suppressed_reason_note": suppression_source.suppressed_reason_note,
                "suppressed_by": suppression_source.suppressed_by,
                "suppressed_at": suppression_source.suppressed_at.isoformat() if suppression_source.suppressed_at is not None else None,
                "suppressed_previous_status": suppression_source.suppressed_previous_status,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_archive(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        previous_status: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "previous_status": previous_status,
                "lineage_id": artifact.lineage_id,
                "parent_artifact_id": artifact.parent_artifact_id,
                "supersedes_artifact_id": artifact.supersedes_artifact_id,
                "source_proposal_id": artifact.source_proposal_id,
                "source_reflection_ids": list(artifact.source_reflection_ids),
                "source_memory_ids": list(artifact.source_memory_ids),
                "deprecated_by": artifact.deprecated_by,
                "deprecated_at": artifact.deprecated_at.isoformat() if artifact.deprecated_at is not None else None,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_replace(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        replaced_artifact: SkillArtifact,
        replaced_previous_status: str,
        evaluation_id: str | None,
        score_delta: float | None,
        rollout_id: str | None,
        binding_id: str | None,
        observation_id: str | None,
        usage_event_ids: list[str],
        replacement_readiness: SkillReplacementReadiness | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "lineage_id": artifact.lineage_id,
                "parent_artifact_id": artifact.parent_artifact_id,
                "supersedes_artifact_id": artifact.supersedes_artifact_id,
                "replaced_artifact_id": replaced_artifact.id,
                "replaced_artifact_previous_status": replaced_previous_status,
                "replaced_artifact_status": replaced_artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "evaluation_id": evaluation_id,
                "score_delta": score_delta,
                "rollout_id": rollout_id,
                "binding_id": binding_id,
                "observation_id": observation_id,
                "usage_event_ids": list(usage_event_ids),
                "replacement_readiness": self._replacement_readiness_payload(replacement_readiness),
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )
