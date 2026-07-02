"""Skill replacement readiness evaluation service.

This module evaluates whether a staged skill artifact has sufficient
evidence to be activated or to replace an existing selectable artifact.
It aggregates rollout observation, usage, binding, and proposal evidence
to produce structured readiness results with reason codes.

The service is fail-closed: missing evidence results in blocked status,
not a pass. It does not execute lifecycle state changes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.skill.constants import (
    REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE,
    REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN,
    REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN,
    STABLE_NEGATIVE_USAGE_STATUSES,
    STABLE_SUCCESSFUL_USAGE_STATUSES,
)
from agent_core.domain.constants import SkillArtifactStatus
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import NotFoundError
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    ReflectionProposalRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    SkillArtifactRepository,
    SkillUsageEventRepository,
)
from agent_core.infrastructure.observability.metrics import observe_skill_replacement_readiness


@dataclass(frozen=True)
class SkillReplacementReadinessThresholds:
    promote_observation_min: int
    successful_usage_min: int
    max_negative_usage_rate: float


@dataclass(frozen=True)
class SkillReplacementReadinessAction:
    status: str
    reason_codes: list[str]


@dataclass(frozen=True)
class SkillReplacementReadiness:
    artifact_id: str
    skill_name: str
    scope: str
    proposal_id: str | None
    proposal_source: str | None
    recommended_action: str | None
    source_anchor: dict[str, Any]
    rollout_evidence: dict[str, Any]
    usage_evidence: dict[str, Any]
    activate_readiness: SkillReplacementReadinessAction
    replace_readiness: SkillReplacementReadinessAction
    thresholds: SkillReplacementReadinessThresholds
    checked_at: datetime


class SkillReplacementReadinessService:
    _GOVERNED_PROPOSAL_SOURCES = {
        "skill_patch_request_realization",
        "skill_curator_merge_recommendation",
    }

    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        rollout_repository: ReflectionProposalRolloutRepository,
        rollout_observation_repository: ReflectionProposalRolloutObservationRepository,
        goal_skill_binding_repository: GoalSkillBindingRepository,
        usage_repository: SkillUsageEventRepository,
        successful_usage_min: int = REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN,
        promote_observation_min: int = REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN,
        max_negative_usage_rate: float = REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._rollout_repository = rollout_repository
        self._rollout_observation_repository = rollout_observation_repository
        self._goal_skill_binding_repository = goal_skill_binding_repository
        self._usage_repository = usage_repository
        self._thresholds = SkillReplacementReadinessThresholds(
            promote_observation_min=promote_observation_min,
            successful_usage_min=successful_usage_min,
            max_negative_usage_rate=max_negative_usage_rate,
        )

    async def get_replacement_readiness(self, *, artifact_id: str) -> SkillReplacementReadiness:
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        return await self.evaluate_artifact(artifact)

    async def evaluate_artifact(
        self,
        artifact: SkillArtifact,
        *,
        proposal: ReflectionProposal | None = None,
    ) -> SkillReplacementReadiness:
        checked_at = datetime.now(timezone.utc)
        proposal = proposal or await self._proposal_for_artifact(artifact)
        proposal_source = self._proposal_source(proposal)
        source_artifact_id = self._source_artifact_id(artifact=artifact, proposal=proposal)
        source_lineage_id = self._source_lineage_id(artifact=artifact, proposal=proposal)
        source_artifact = (
            await self._artifact_repository.get_by_id(source_artifact_id) if source_artifact_id is not None else None
        )
        current_selectable = await self._artifact_repository.get_selectable_by_name_scope(
            name=artifact.name,
            scope=artifact.scope,
        )
        source_anchor = {
            "source_artifact_id": source_artifact_id,
            "source_lineage_id": source_lineage_id,
            "current_source_status": source_artifact.status if source_artifact is not None else None,
            "current_selectable_artifact_id": current_selectable.id if current_selectable is not None else None,
            "anchor_status": "not_applicable",
        }
        empty_rollout = {
            "rollout_id": None,
            "binding_id": None,
            "latest_observation_id": None,
            "promote_observation_ids": [],
        }
        empty_usage = {
            "matched_count": 0,
            "successful_count": 0,
            "negative_count": 0,
            "negative_usage_rate": 0.0,
            "matched_usage_event_ids": [],
            "successful_usage_event_ids": [],
            "negative_usage_event_ids": [],
        }

        if artifact.status != SkillArtifactStatus.STAGED.value:
            readiness = SkillReplacementReadiness(
                artifact_id=artifact.id,
                skill_name=artifact.name,
                scope=artifact.scope,
                proposal_id=artifact.source_proposal_id,
                proposal_source=proposal_source,
                recommended_action=None,
                source_anchor=source_anchor,
                rollout_evidence=empty_rollout,
                usage_evidence=empty_usage,
                activate_readiness=SkillReplacementReadinessAction(
                    status="not_applicable",
                    reason_codes=["artifact_not_staged"],
                ),
                replace_readiness=SkillReplacementReadinessAction(
                    status="not_applicable",
                    reason_codes=["artifact_not_staged"],
                ),
                thresholds=self._thresholds,
                checked_at=checked_at,
            )
            self._observe(readiness)
            return readiness

        if proposal_source not in self._GOVERNED_PROPOSAL_SOURCES:
            readiness = SkillReplacementReadiness(
                artifact_id=artifact.id,
                skill_name=artifact.name,
                scope=artifact.scope,
                proposal_id=artifact.source_proposal_id,
                proposal_source=proposal_source,
                recommended_action=None,
                source_anchor=source_anchor,
                rollout_evidence=empty_rollout,
                usage_evidence=empty_usage,
                activate_readiness=SkillReplacementReadinessAction(
                    status="not_applicable",
                    reason_codes=["non_governed_replacement"],
                ),
                replace_readiness=SkillReplacementReadinessAction(
                    status="not_applicable",
                    reason_codes=["non_governed_replacement"],
                ),
                thresholds=self._thresholds,
                checked_at=checked_at,
            )
            self._observe(readiness)
            return readiness

        source_reason_codes = self._source_anchor_reason_codes(
            artifact=artifact,
            source_artifact=source_artifact,
            source_artifact_id=source_artifact_id,
            source_lineage_id=source_lineage_id,
        )
        source_anchor["anchor_status"] = "anchored" if not source_reason_codes else "changed"

        rollout_reason_codes: list[str] = []
        rollout = None
        binding = None
        latest_observation = None
        promote_observations: list[ReflectionProposalRolloutObservation] = []
        usage_metrics = dict(empty_usage)
        if proposal is None:
            rollout_reason_codes.append("missing_source_proposal")
        else:
            rollout = await self._rollout_repository.get_by_proposal(proposal.id)
            if rollout is None:
                rollout_reason_codes.append("missing_rollout")
            elif rollout.status != "rolled_out":
                rollout_reason_codes.append("rollout_not_promoted")
            elif rollout.surface != artifact.scope:
                rollout_reason_codes.append("rollout_scope_mismatch")
            else:
                binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
                if binding is None:
                    rollout_reason_codes.append("missing_binding")
                elif binding.status != "rolled_out":
                    rollout_reason_codes.append("binding_not_promoted")
                elif (
                    binding.proposal_id != proposal.id
                    or binding.rollout_id != rollout.id
                    or binding.surface != artifact.scope
                ):
                    rollout_reason_codes.append("binding_mismatch")
                if rollout.latest_observation_id is None:
                    rollout_reason_codes.append("missing_observation")
                else:
                    latest_observation = await self._rollout_observation_repository.get_by_id(rollout.latest_observation_id)
                    if latest_observation is None:
                        rollout_reason_codes.append("missing_observation")
                    elif (
                        latest_observation.rollout_id != rollout.id
                        or latest_observation.proposal_id != proposal.id
                        or latest_observation.surface != artifact.scope
                    ):
                        rollout_reason_codes.append("observation_mismatch")
                    elif latest_observation.recommendation != "promote":
                        rollout_reason_codes.append("latest_observation_not_promote")
                promote_observations = await self._promote_observations(
                    artifact=artifact,
                    rollout=rollout,
                    evidence_started_at=rollout.activated_at,
                )
                if len(promote_observations) < self._thresholds.promote_observation_min:
                    rollout_reason_codes.append("insufficient_promote_observations")
                if binding is not None:
                    usage_metrics = await self._rollout_usage_metrics(
                        artifact=artifact,
                        rollout=rollout,
                        binding=binding,
                        evidence_started_at=rollout.activated_at,
                    )
                    if usage_metrics["successful_count"] < self._thresholds.successful_usage_min:
                        rollout_reason_codes.append("insufficient_successful_usage")
                    if usage_metrics["negative_usage_rate"] > self._thresholds.max_negative_usage_rate:
                        rollout_reason_codes.append("negative_usage_rate_high")

        activate_reason_codes = list(source_reason_codes)
        activate_reason_codes.extend(code for code in rollout_reason_codes if code not in activate_reason_codes)
        if current_selectable is not None and current_selectable.id != artifact.id:
            activate_reason_codes.append("current_selectable_conflict")

        replace_reason_codes = list(source_reason_codes)
        replace_reason_codes.extend(code for code in rollout_reason_codes if code not in replace_reason_codes)
        if current_selectable is None:
            replace_reason_codes.append("existing_selectable_missing")
        elif source_artifact_id is None:
            replace_reason_codes.append("source_anchor_changed")
        elif current_selectable.id != source_artifact_id:
            replace_reason_codes.append("existing_selectable_not_source_anchor")

        readiness = SkillReplacementReadiness(
            artifact_id=artifact.id,
            skill_name=artifact.name,
            scope=artifact.scope,
            proposal_id=artifact.source_proposal_id,
            proposal_source=proposal_source,
            recommended_action=(
                "replace_selectable"
                if not replace_reason_codes
                else ("activate_staged" if not activate_reason_codes else None)
            ),
            source_anchor=source_anchor,
            rollout_evidence={
                "rollout_id": rollout.id if rollout is not None else None,
                "binding_id": binding.id if binding is not None else None,
                "latest_observation_id": latest_observation.id if latest_observation is not None else None,
                "promote_observation_ids": [item.id for item in promote_observations],
            },
            usage_evidence=usage_metrics,
            activate_readiness=SkillReplacementReadinessAction(
                status="ready" if not activate_reason_codes else "blocked",
                reason_codes=activate_reason_codes,
            ),
            replace_readiness=SkillReplacementReadinessAction(
                status="ready" if not replace_reason_codes else "blocked",
                reason_codes=replace_reason_codes,
            ),
            thresholds=self._thresholds,
            checked_at=checked_at,
        )
        self._observe(readiness)
        return readiness

    async def _proposal_for_artifact(self, artifact: SkillArtifact) -> ReflectionProposal | None:
        if artifact.source_proposal_id is None:
            return None
        return await self._proposal_repository.get_by_id(artifact.source_proposal_id)

    @staticmethod
    def _proposal_source(proposal: ReflectionProposal | None) -> str | None:
        if proposal is None:
            return None
        value = proposal.evidence_snapshot.get("source")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _source_artifact_id(*, artifact: SkillArtifact, proposal: ReflectionProposal | None) -> str | None:
        if proposal is not None:
            value = proposal.evidence_snapshot.get("source_artifact_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        if artifact.parent_artifact_id is not None and artifact.parent_artifact_id.strip():
            return artifact.parent_artifact_id.strip()
        return None

    @staticmethod
    def _source_lineage_id(*, artifact: SkillArtifact, proposal: ReflectionProposal | None) -> str | None:
        if proposal is not None:
            value = proposal.evidence_snapshot.get("source_artifact_lineage_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return artifact.lineage_id

    @staticmethod
    def _source_anchor_reason_codes(
        *,
        artifact: SkillArtifact,
        source_artifact: SkillArtifact | None,
        source_artifact_id: str | None,
        source_lineage_id: str | None,
    ) -> list[str]:
        reasons: list[str] = []
        if source_artifact_id is None:
            reasons.append("source_anchor_changed")
            return reasons
        if source_artifact is None:
            reasons.append("source_anchor_changed")
            return reasons
        if source_lineage_id is None or source_artifact.lineage_id != source_lineage_id:
            reasons.append("source_anchor_changed")
        if artifact.parent_artifact_id != source_artifact.id or artifact.supersedes_artifact_id != source_artifact.id:
            reasons.append("source_anchor_changed")
        if source_artifact.name != artifact.name or source_artifact.scope != artifact.scope:
            reasons.append("source_anchor_changed")
        deduped: list[str] = []
        for reason in reasons:
            if reason not in deduped:
                deduped.append(reason)
        return deduped

    async def _promote_observations(
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
            and item.proposal_id == rollout.proposal_id
            and item.surface == artifact.scope
        ]
        relevant = sorted(relevant, key=lambda item: (item.created_at, item.id), reverse=True)
        recent = relevant[: self._thresholds.promote_observation_min]
        if len(recent) < self._thresholds.promote_observation_min:
            return []
        if any(item.recommendation != "promote" for item in recent):
            return []
        return recent

    async def _rollout_usage_metrics(
        self,
        *,
        artifact: SkillArtifact,
        rollout: ReflectionProposalRollout,
        binding: ActiveGoalSkillBinding,
        evidence_started_at: datetime,
    ) -> dict[str, Any]:
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            learner_goal_id=rollout.learner_goal_id,
            surface=artifact.scope,
            created_at_from=evidence_started_at,
            limit=200,
        )
        matched: list[SkillUsageEvent] = []
        successful: list[SkillUsageEvent] = []
        negative: list[SkillUsageEvent] = []
        for event in events:
            rollout_metadata = event.metadata.get("skill_package_rollout")
            if not isinstance(rollout_metadata, dict):
                continue
            if not matches_rollout_metadata(
                rollout_metadata,
                proposal_id=rollout.proposal_id,
                rollout_id=rollout.id,
                binding_id=binding.id,
                skill_name=artifact.name,
                surface=artifact.scope,
            ):
                continue
            matched.append(event)
            if event.outcome_status in STABLE_SUCCESSFUL_USAGE_STATUSES:
                successful.append(event)
            elif event.outcome_status in STABLE_NEGATIVE_USAGE_STATUSES:
                negative.append(event)
        negative_usage_rate = len(negative) / len(matched) if matched else 0.0
        return {
            "matched_count": len(matched),
            "successful_count": len(successful),
            "negative_count": len(negative),
            "negative_usage_rate": negative_usage_rate,
            "matched_usage_event_ids": [item.id for item in matched],
            "successful_usage_event_ids": [item.id for item in successful],
            "negative_usage_event_ids": [item.id for item in negative],
        }

    @staticmethod
    def _observe(readiness: SkillReplacementReadiness) -> None:
        observe_skill_replacement_readiness(
            action="activate_staged",
            status=readiness.activate_readiness.status,
        )
        observe_skill_replacement_readiness(
            action="replace_selectable",
            status=readiness.replace_readiness.status,
        )


def matches_rollout_metadata(
    rollout_metadata: dict[str, Any],
    *,
    proposal_id: str,
    rollout_id: str,
    binding_id: str,
    skill_name: str,
    surface: str,
) -> bool:
    return (
        rollout_metadata.get("proposal_id") == proposal_id
        and rollout_metadata.get("rollout_id") == rollout_id
        and rollout_metadata.get("binding_id") == binding_id
        and rollout_metadata.get("skill_name") == skill_name
        and rollout_metadata.get("surface") == surface
    )
