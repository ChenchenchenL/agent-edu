from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import perf_counter
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.tool_plan_contracts import validate_tool_plan_contract
from agent_core.application.services.tool_plan_sequence_governance import (
    build_tool_plan_sequence_contract,
    has_tool_plan_sequence_regression,
    summarize_tool_plan_usage,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.memory import MemoryConflictSet
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.skill import (
    SKILL_ARTIFACT_STATUSES,
    SKILL_CURATOR_RECOMMENDATION_STATUSES,
    SKILL_CURATOR_RECOMMENDATION_TYPES,
    SKILL_CURATOR_RECOMMENDED_ACTIONS,
    SKILL_SCOPES,
    SKILL_USAGE_SURFACES,
    SkillArtifact,
    SkillCuratorRecommendation,
    SkillExecutionPlan,
    SkillResolution,
    SkillUsageEvent,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.observability.metrics import (
    observe_skill_curator_job,
    observe_skill_curator_recommendation,
    observe_skill_replacement_readiness,
    observe_skill_resolution,
    observe_skill_usage_event,
    set_skill_artifacts_total,
    set_skill_curator_pending_recommendations,
)
from agent_core.domain.constants import (
    SkillArtifactStatus,
    SkillLifecycleThresholds,
    ALLOWED_SKILL_PACKAGE_TOOLS as ALLOWED_TOOLS_FROM_CONSTANTS,
)
from agent_core.domain.value_objects import require_non_empty
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    MemoryConflictRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRolloutDecisionRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    ReflectionProposalRepository,
    ReflectionOutcomeEvaluationRepository,
    SkillArtifactRepository,
    SkillCuratorRecommendationRepository,
    SkillUsageEventRepository,
)


# 使用集中管理的常量
_thresholds = SkillLifecycleThresholds()
CANDIDATE_MIN_SCORE_DELTA = _thresholds.CANDIDATE_MIN_SCORE_DELTA
STABLE_MIN_SUCCESSFUL_USAGE_COUNT = _thresholds.STABLE_MIN_SUCCESSFUL_USAGE
STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT = _thresholds.STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT
STABLE_MAX_NEGATIVE_USAGE_RATE = _thresholds.STABLE_MAX_NEGATIVE_RATE
REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN = _thresholds.STAGING_MIN_USAGE_COUNT
REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN = _thresholds.REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN
REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE = _thresholds.STAGING_MAX_FAILURE_RATE

# 特定于skills.py的工具集（与centralized常量不同）
ALLOWED_SKILL_PACKAGE_TOOLS = {"review_scheduling", "assessment_generation", "partial_replan"}
STABLE_SUCCESSFUL_USAGE_STATUSES = {"completed", "partial_success"}
STABLE_NEGATIVE_USAGE_STATUSES = {"failed", "skipped", "aborted"}
ACTIVE_SKILL_REFERENCE_STATUSES = [
    SkillArtifactStatus.STAGED.value,
    "rolled_out"  # 不在SkillArtifactStatus枚举中
]
CURATOR_DEACTIVATION_REASON_CODES = {
    "rollout_rollback",
    "quality_regression",
    "safety_risk",
    "superseded",
    "operator_request",
}
CURATOR_SUPPRESSION_REASON_CODES = {
    "safety_risk",
    "quality_regression",
    "policy_violation",
    "operator_request",
}
CURATOR_RESTORE_REASON_CODES = {
    "operator_restore",
    "risk_mitigated",
    "false_positive",
}
CURATOR_ARCHIVE_REASON_CODES = {
    "stale_deprecated",
    "operator_request",
    "cleanup",
}
CURATOR_ACTIVATION_REASON_CODES = {
    "operator_reviewed",
    "replacement_evidence_ready",
    "source_selectable_missing",
    "operator_request",
    "rollout_promoted",
}
MERGE_SOURCE_ARTIFACT_STATUSES = {
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value
}
MERGE_RELATED_ARTIFACT_STATUSES = {
    SkillArtifactStatus.CANDIDATE.value,
    SkillArtifactStatus.STAGED.value,
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value,
    SkillArtifactStatus.DEPRECATED.value
}
MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER = (
    SkillArtifactStatus.CANDIDATE.value,
    SkillArtifactStatus.STAGED.value,
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value,
    SkillArtifactStatus.DEPRECATED.value
)
MERGE_OVERLAP_RULE_KEYS = ("task_types", "topic_keys")


class SkillPatchProposalService(Protocol):
    async def get(self, proposal_id: str) -> ReflectionProposal:
        ...

    async def create_skill_patch_request_from_recommendation(
        self,
        *,
        recommendation_id: str,
        artifact_id: str | None,
        skill_name: str,
        skill_version: str | None,
        scope: str,
        surface: str,
        recommendation_reason_code: str,
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        related_artifact_ids: list[str],
        reflection_record_id: str,
        learner_goal_id: str,
        operator_id: str,
    ) -> ReflectionProposal:
        ...

    async def create_skill_merge_package_from_recommendation(
        self,
        *,
        recommendation_id: str,
        artifact_id: str | None,
        skill_name: str,
        skill_version: str | None,
        scope: str,
        surface: str,
        recommendation_reason_code: str,
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        related_artifact_ids: list[str],
        reflection_record_id: str,
        learner_goal_id: str,
        operator_id: str,
    ) -> ReflectionProposal:
        ...


@dataclass(frozen=True)
class SkillCuratorJobConfig:
    enabled: bool = True
    artifact_scan_limit: int = 20
    merge_related_scan_limit: int = 200
    merge_overlap_min_shared_values: int = 1
    usage_lookback_days: int = 30
    coverage_regression_enabled: bool = True
    coverage_drift_topic_min: int = 3
    coverage_hole_topic_min: int = 2
    promote_successful_usage_min: int = STABLE_MIN_SUCCESSFUL_USAGE_COUNT
    promote_observation_min: int = STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT
    max_negative_usage_rate: float = STABLE_MAX_NEGATIVE_USAGE_RATE
    negative_usage_min: int = 3
    negative_usage_rate_threshold: float = 0.4
    resolver_failure_min: int = 3
    archive_stale_days: int = 30
    governance_evidence_enabled: bool = True
    governance_evidence_lookback_days: int = 30
    governance_evidence_limit: int = 20
    memory_conflict_severity_threshold: float = 0.6
    reflection_ineffective_min: int = 1
    reflection_inconclusive_min: int = 2
    tool_plan_sequence_evidence_enabled: bool = True
    tool_plan_sequence_mismatch_min: int = 1
    tool_plan_missing_metadata_min: int = 1
    tool_plan_required_output_missing_min: int = 1
    replacement_readiness_successful_usage_min: int = REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN
    replacement_readiness_promote_observation_min: int = REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN
    replacement_readiness_max_negative_usage_rate: float = REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE


@dataclass(frozen=True)
class SkillCuratorJobResult:
    scanned_count: int
    created_count: int
    existing_count: int


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


async def refresh_skill_observability_metrics(
    *,
    artifact_repository: Any | None = None,
    recommendation_repository: Any | None = None,
) -> None:
    if artifact_repository is not None:
        count_by_status = getattr(artifact_repository, "count_by_status", None)
        if count_by_status is not None:
            artifact_counts = await count_by_status()
            for status in SKILL_ARTIFACT_STATUSES:
                set_skill_artifacts_total(status=status, count=int(artifact_counts.get(status, 0)))
    if recommendation_repository is not None:
        count_pending_by_type = getattr(recommendation_repository, "count_pending_by_type", None)
        if count_pending_by_type is not None:
            pending_counts = await count_pending_by_type()
            for recommendation_type in SKILL_CURATOR_RECOMMENDATION_TYPES:
                set_skill_curator_pending_recommendations(
                    recommendation_type=recommendation_type,
                    count=int(pending_counts.get(recommendation_type, 0)),
                )


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
        binding: GoalSkillBinding,
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
            if not SkillArtifactLifecycleService._matches_rollout_metadata(
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


class SkillCatalogService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
        skill_registry: SkillRegistry,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service
        self._skill_registry = skill_registry

    async def list_artifacts(
        self,
        *,
        status: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        lineage_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillArtifact]:
        return await self._artifact_repository.list_artifacts(
            status=status,
            name=name,
            scope=scope,
            lineage_id=lineage_id,
            limit=bounded_limit(limit),
        )

    async def get_artifact(self, artifact_id: str) -> SkillArtifact:
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        return artifact

    async def list_lineage(self, artifact_id: str, *, limit: int = 50) -> list[SkillArtifact]:
        artifact = await self.get_artifact(artifact_id)
        return await self._artifact_repository.list_by_lineage(
            artifact.lineage_id,
            limit=bounded_limit(limit),
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
            if not self._matches_rollout_metadata(
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
            if self._matches_rollout_metadata(
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
    def _matches_rollout_metadata(
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


class SkillCuratorJobService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        usage_repository: SkillUsageEventRepository,
        proposal_repository: ReflectionProposalRepository,
        rollout_repository: ReflectionProposalRolloutRepository,
        rollout_observation_repository: ReflectionProposalRolloutObservationRepository,
        rollout_decision_repository: ReflectionProposalRolloutDecisionRepository,
        goal_skill_binding_repository: GoalSkillBindingRepository,
        recommendation_repository: SkillCuratorRecommendationRepository,
        recommendation_service: SkillCuratorRecommendationService,
        replacement_auto_execution_scheduler: SkillReplacementAutoExecutionScheduler | None = None,
        audit_service: AuditService,
        memory_conflict_repository: MemoryConflictRepository | None = None,
        reflection_outcome_evaluation_repository: ReflectionOutcomeEvaluationRepository | None = None,
        config: SkillCuratorJobConfig | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._usage_repository = usage_repository
        self._proposal_repository = proposal_repository
        self._rollout_repository = rollout_repository
        self._rollout_observation_repository = rollout_observation_repository
        self._rollout_decision_repository = rollout_decision_repository
        self._goal_skill_binding_repository = goal_skill_binding_repository
        self._recommendation_repository = recommendation_repository
        self._recommendation_service = recommendation_service
        self._replacement_auto_execution_scheduler = replacement_auto_execution_scheduler
        self._audit_service = audit_service
        self._memory_conflict_repository = memory_conflict_repository
        self._reflection_outcome_evaluation_repository = reflection_outcome_evaluation_repository
        self._config = config or SkillCuratorJobConfig()
        self._replacement_readiness_service = SkillReplacementReadinessService(
            artifact_repository=artifact_repository,
            proposal_repository=proposal_repository,
            rollout_repository=rollout_repository,
            rollout_observation_repository=rollout_observation_repository,
            goal_skill_binding_repository=goal_skill_binding_repository,
            usage_repository=usage_repository,
            successful_usage_min=self._config.replacement_readiness_successful_usage_min,
            promote_observation_min=self._config.replacement_readiness_promote_observation_min,
            max_negative_usage_rate=self._config.replacement_readiness_max_negative_usage_rate,
        )

    async def run_once(self, *, now: datetime | None = None) -> SkillCuratorJobResult:
        started_at = perf_counter()
        if not self._config.enabled:
            observe_skill_curator_job(status="disabled", duration_seconds=perf_counter() - started_at)
            return SkillCuratorJobResult(scanned_count=0, created_count=0, existing_count=0)
        checked_at = now or datetime.now(timezone.utc)
        window_key = checked_at.strftime("%Y%m%d")
        try:
            artifacts = await self._list_scan_artifacts()
            created_count = 0
            existing_count = 0
            for artifact in artifacts:
                result = await self._curate_artifact(
                    artifact=artifact,
                    now=checked_at,
                    window_key=window_key,
                )
                created_count += result.created_count
                existing_count += result.existing_count
            job_result = SkillCuratorJobResult(
                scanned_count=len(artifacts),
                created_count=created_count,
                existing_count=existing_count,
            )
            await self._audit_service.record(
                event_type="skill.curator.job.completed",
                resource_type="skill_curator_job",
                resource_id=None,
                actor="system",
                event_data={
                    "scanned_count": job_result.scanned_count,
                    "created_count": job_result.created_count,
                    "existing_count": job_result.existing_count,
                    "window_key": window_key,
                },
            )
            observe_skill_curator_job(status="completed", duration_seconds=perf_counter() - started_at)
            return job_result
        except Exception:
            observe_skill_curator_job(status="failed", duration_seconds=perf_counter() - started_at)
            raise

    async def _list_scan_artifacts(self) -> list[SkillArtifact]:
        limit = max(self._config.artifact_scan_limit, 1)
        artifacts: list[SkillArtifact] = []
        seen_ids: set[str] = set()
        for status in (
            SkillArtifactStatus.STAGED.value,
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value,
            SkillArtifactStatus.DEPRECATED.value
        ):
            remaining = limit - len(artifacts)
            if remaining <= 0:
                break
            for artifact in await self._artifact_repository.list_artifacts(status=status, limit=remaining):
                if artifact.id in seen_ids:
                    continue
                artifacts.append(artifact)
                seen_ids.add(artifact.id)
        return artifacts

    async def _curate_artifact(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        window_key: str,
    ) -> SkillCuratorJobResult:
        created_count = 0
        existing_count = 0
        for recommendation in await self._recommendations_for_artifact(
            artifact=artifact,
            now=now,
            window_key=window_key,
        ):
            if recommendation == "created":
                created_count += 1
            elif recommendation == "existing":
                existing_count += 1
        return SkillCuratorJobResult(scanned_count=1, created_count=created_count, existing_count=existing_count)

    async def _recommendations_for_artifact(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        window_key: str,
    ) -> list[str]:
        outcomes: list[str] = []
        if artifact.status == SkillArtifactStatus.STAGED.value:
            staged_recommendation = await self._maybe_recommend_staged_replacement_action(
                artifact=artifact,
                window_key=window_key,
            )
            if staged_recommendation is not None:
                outcomes.append(staged_recommendation)
        if artifact.status == SkillArtifactStatus.ACTIVE.value:
            promote = await self._maybe_recommend_promote(
                artifact=artifact,
                window_key=window_key,
            )
            if promote is not None:
                outcomes.append(promote)
        if artifact.status in {
            SkillArtifactStatus.ACTIVE.value,
            SkillArtifactStatus.STABLE.value
        }:
            negative = await self._maybe_recommend_negative_review(
                artifact=artifact,
                now=now,
                window_key=window_key,
            )
            if negative is not None:
                outcomes.append(negative)
            rollback = await self._maybe_recommend_rollback_review(
                artifact=artifact,
                window_key=window_key,
            )
            if rollback is not None:
                outcomes.append(rollback)
            coverage = await self._maybe_recommend_coverage_regression(
                artifact=artifact,
                now=now,
                window_key=window_key,
            )
            if coverage is not None:
                outcomes.append(coverage)
            merge = await self._maybe_recommend_merge_candidate(
                artifact=artifact,
                window_key=window_key,
            )
            if merge is not None:
                outcomes.append(merge)
        if artifact.status == SkillArtifactStatus.DEPRECATED.value:
            archive = await self._maybe_recommend_archive(
                artifact=artifact,
                now=now,
                window_key=window_key,
            )
            if archive is not None:
                outcomes.append(archive)
        return outcomes

    async def _maybe_recommend_staged_replacement_action(
        self,
        *,
        artifact: SkillArtifact,
        window_key: str,
    ) -> str | None:
        readiness = await self._replacement_readiness_service.evaluate_artifact(artifact)
        learner_goal_id = await self._learner_goal_id_for_readiness(readiness)
        if readiness.replace_readiness.status == "ready":
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="replace_candidate",
                recommended_action="replace_selectable",
                reason_code="replacement_evidence_ready",
                reason_note="Governed staged replacement has enough rollout evidence to replace the anchored selectable.",
                evidence_snapshot=self._replacement_readiness_evidence_snapshot(
                    readiness,
                    ready_action="replace_selectable",
                    learner_goal_id=learner_goal_id,
                ),
                metrics_snapshot=self._replacement_readiness_metrics_snapshot(readiness),
                source_discriminator=f"replacement:{artifact.id}:replace",
            )
        if readiness.activate_readiness.status == "ready":
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="activate_candidate",
                recommended_action="activate_staged",
                reason_code="activation_evidence_ready",
                reason_note="Governed staged replacement has enough rollout evidence to activate without a current selectable.",
                evidence_snapshot=self._replacement_readiness_evidence_snapshot(
                    readiness,
                    ready_action="activate_staged",
                    learner_goal_id=learner_goal_id,
                ),
                metrics_snapshot=self._replacement_readiness_metrics_snapshot(readiness),
                source_discriminator=f"replacement:{artifact.id}:activate",
            )
        return None

    async def _maybe_recommend_promote(
        self,
        *,
        artifact: SkillArtifact,
        window_key: str,
    ) -> str | None:
        rollout = await self._rollout_for_artifact(artifact)
        if rollout is None or rollout.status != "rolled_out" or rollout.surface != artifact.scope:
            return None
        binding = await self._binding_for_rollout(artifact=artifact, rollout=rollout)
        if binding is None:
            return None
        evidence_started_at = artifact.approved_at or artifact.updated_at
        observations = await self._promote_observations(
            artifact=artifact,
            rollout=rollout,
            evidence_started_at=evidence_started_at,
        )
        if len(observations) < self._config.promote_observation_min:
            return None
        usage_metrics = await self._rollout_usage_metrics(
            artifact=artifact,
            rollout=rollout,
            binding=binding,
            evidence_started_at=evidence_started_at,
        )
        if usage_metrics["successful_count"] < self._config.promote_successful_usage_min:
            return None
        if usage_metrics["negative_usage_rate"] > self._config.max_negative_usage_rate:
            return None
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="promote_candidate",
            recommended_action="stabilize_active",
            reason_code="stable_evidence",
            reason_note="Active artifact has enough stable rollout and usage evidence.",
            evidence_snapshot={
                "artifact_id": artifact.id,
                "artifact_status": artifact.status,
                "artifact_version": artifact.version,
                "lineage_id": artifact.lineage_id,
                "source_proposal_id": artifact.source_proposal_id,
                "rollout_id": rollout.id,
                "binding_id": binding.id,
                "observation_ids": [item.id for item in observations],
                "usage_event_ids": usage_metrics["matched_usage_event_ids"],
                "successful_usage_event_ids": usage_metrics["successful_usage_event_ids"],
                "negative_usage_event_ids": usage_metrics["negative_usage_event_ids"],
                "evidence_started_at": evidence_started_at.isoformat(),
            },
            metrics_snapshot={
                **usage_metrics,
                "promote_observation_count": len(observations),
                "promote_successful_usage_min": self._config.promote_successful_usage_min,
                "promote_observation_min": self._config.promote_observation_min,
                "max_negative_usage_rate": self._config.max_negative_usage_rate,
            },
        )

    async def _maybe_recommend_negative_review(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        window_key: str,
    ) -> str | None:
        started_at = now - timedelta(days=max(self._config.usage_lookback_days, 1))
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            surface=artifact.scope,
            created_at_from=started_at,
            limit=200,
        )
        matched = [item for item in events if item.skill_artifact_id == artifact.id]
        negative = [item for item in matched if item.outcome_status in STABLE_NEGATIVE_USAGE_STATUSES]
        resolver_failures = [
            item
            for item in events
            if item.resolver_status in {"blocked", "incompatible"}
            and item.selection_reason in {"suppressed_artifact", "contract_incompatible", "runtime_resolution_failed"}
        ]
        negative_rate = len(negative) / len(matched) if matched else 0.0
        has_negative_signal = (
            len(negative) >= self._config.negative_usage_min
            and negative_rate >= self._config.negative_usage_rate_threshold
        )
        has_resolver_signal = len(resolver_failures) >= self._config.resolver_failure_min
        governance_evidence = await self._governance_evidence_for_artifact(
            artifact=artifact,
            now=now,
            started_at=started_at,
            usage_events=events,
            resolver_failures=resolver_failures,
        )
        has_governance_signal = self._has_governance_regression(governance_evidence)
        if not has_negative_signal and not has_resolver_signal and not has_governance_signal:
            return None
        evidence_snapshot: dict[str, Any] = {
            "artifact_id": artifact.id,
            "artifact_status": artifact.status,
            "artifact_version": artifact.version,
            "lineage_id": artifact.lineage_id,
            "source_proposal_id": artifact.source_proposal_id,
            "evidence_started_at": started_at.isoformat(),
            "evidence_ended_at": now.isoformat(),
            "negative_usage_event_ids": [item.id for item in negative],
            "resolver_failure_event_ids": [item.id for item in resolver_failures],
            "resolver_selection_reasons": sorted({item.selection_reason for item in resolver_failures}),
        }
        metrics_snapshot: dict[str, Any] = {
            "matched_count": len(matched),
            "negative_count": len(negative),
            "negative_usage_rate": negative_rate,
            "resolver_failure_count": len(resolver_failures),
            "usage_lookback_days": self._config.usage_lookback_days,
            "negative_usage_min": self._config.negative_usage_min,
            "negative_usage_rate_threshold": self._config.negative_usage_rate_threshold,
            "resolver_failure_min": self._config.resolver_failure_min,
        }
        if governance_evidence:
            evidence_snapshot["governance_evidence"] = governance_evidence
            metrics_snapshot.update(self._governance_evidence_metrics(governance_evidence))
        if not has_negative_signal and not has_resolver_signal and has_governance_signal:
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="flag_for_review",
                recommended_action="none",
                reason_code="governance_evidence_regression",
                reason_note="Memory conflict or reflection outcome evidence requires operator review.",
                evidence_snapshot=evidence_snapshot,
                metrics_snapshot=metrics_snapshot,
                source_discriminator=self._governance_source_discriminator(governance_evidence),
            )
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="flag_for_review",
            recommended_action="none",
            reason_code="quality_regression",
            reason_note="Recent usage or resolver signals require operator review.",
            evidence_snapshot=evidence_snapshot,
            metrics_snapshot=metrics_snapshot,
        )

    async def _maybe_recommend_rollback_review(
        self,
        *,
        artifact: SkillArtifact,
        window_key: str,
    ) -> str | None:
        rollout = await self._rollout_for_artifact(artifact)
        if rollout is None:
            return None
        latest_observation = await self._latest_rollout_observation(rollout)
        if latest_observation is None or latest_observation.recommendation != "rollback":
            return None
        decisions = await self._rollout_decision_repository.list_by_rollout(rollout.id)
        if any(
            item.decision_type == "rollback" and item.created_at >= latest_observation.created_at
            for item in decisions
        ):
            return None
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="rollback_review",
            recommended_action="none",
            reason_code="rollback_recommended",
            reason_note="Latest rollout observation recommends rollback review.",
            evidence_snapshot={
                "artifact_id": artifact.id,
                "artifact_status": artifact.status,
                "artifact_version": artifact.version,
                "lineage_id": artifact.lineage_id,
                "source_proposal_id": artifact.source_proposal_id,
                "rollout_id": rollout.id,
                "latest_observation_id": latest_observation.id,
                "latest_observation_recommendation": latest_observation.recommendation,
                "decision_ids": [item.id for item in decisions],
            },
            metrics_snapshot={
                "positive_score": latest_observation.positive_score,
                "negative_score": latest_observation.negative_score,
                "observed_sample_count": latest_observation.observed_sample_count,
            },
        )

    async def _governance_evidence_for_artifact(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        started_at: datetime,
        usage_events: list[SkillUsageEvent],
        resolver_failures: list[SkillUsageEvent],
    ) -> dict[str, Any]:
        if not self._config.governance_evidence_enabled:
            return {}
        evidence_started_at = now - timedelta(days=max(self._config.governance_evidence_lookback_days, 1))
        topic_keys = self._artifact_topic_keys(artifact)
        rollout = await self._rollout_for_artifact(artifact)
        learner_goal_id = rollout.learner_goal_id if rollout is not None else self._single_usage_goal_id(usage_events)
        evidence: dict[str, Any] = {
            "learner_goal_id": learner_goal_id,
            "topic_keys": topic_keys,
            "evidence_started_at": evidence_started_at.isoformat(),
            "usage_evidence_started_at": started_at.isoformat(),
            "evidence_ended_at": now.isoformat(),
        }
        if resolver_failures:
            evidence["resolver_health"] = self._resolver_health_evidence(resolver_failures)
        tool_plan_sequence = self._tool_plan_sequence_evidence(
            artifact=artifact,
            usage_events=usage_events,
        )
        if tool_plan_sequence:
            evidence["tool_plan_sequence"] = tool_plan_sequence
        if learner_goal_id is None or not topic_keys:
            return {
                key: value
                for key, value in evidence.items()
                if key in {"resolver_health", "tool_plan_sequence"}
            }

        memory_conflicts = await self._memory_conflict_evidence(
            learner_goal_id=learner_goal_id,
            topic_keys=set(topic_keys),
            updated_at_from=evidence_started_at,
        )
        if memory_conflicts:
            evidence["memory_conflicts"] = memory_conflicts

        reflection_outcomes = await self._reflection_outcome_evidence(
            learner_goal_id=learner_goal_id,
            topic_keys=set(topic_keys),
            updated_at_from=evidence_started_at,
        )
        if reflection_outcomes:
            evidence["reflection_outcomes"] = reflection_outcomes

        if set(evidence) == {
            "learner_goal_id",
            "topic_keys",
            "evidence_started_at",
            "usage_evidence_started_at",
            "evidence_ended_at",
        }:
            return {}
        return evidence

    async def _memory_conflict_evidence(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str],
        updated_at_from: datetime,
    ) -> dict[str, Any]:
        if self._memory_conflict_repository is None:
            return {}
        conflicts: list[MemoryConflictSet] = await self._memory_conflict_repository.list_open_sets_by_goal_topics(
            learner_goal_id=learner_goal_id,
            topic_keys=topic_keys,
            updated_at_from=updated_at_from,
            limit=max(self._config.governance_evidence_limit, 1),
        )
        if not conflicts:
            return {}
        high_severity = [
            item
            for item in conflicts
            if item.severity_score >= self._config.memory_conflict_severity_threshold
        ]
        return {
            "open_count": len(conflicts),
            "high_severity_count": len(high_severity),
            "max_severity": max(item.severity_score for item in conflicts),
            "severity_threshold": self._config.memory_conflict_severity_threshold,
            "conflict_set_ids": [item.id for item in high_severity],
            "matched_conflict_set_ids": [item.id for item in conflicts],
            "topic_keys": sorted({item.topic_key for item in conflicts}),
            "conflict_types": sorted({item.conflict_type for item in conflicts}),
            "status_impacts": {
                item.id: item.status_impact.to_payload()
                for item in high_severity
            },
            "summaries": {item.id: item.summary for item in high_severity},
        }

    async def _reflection_outcome_evidence(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str],
        updated_at_from: datetime,
    ) -> dict[str, Any]:
        if self._reflection_outcome_evaluation_repository is None:
            return {}
        outcomes: list[ReflectionOutcomeEvaluation] = await self._reflection_outcome_evaluation_repository.list_by_goal_topics(
            learner_goal_id=learner_goal_id,
            topic_keys=topic_keys,
            statuses={"effective", "ineffective", "inconclusive"},
            updated_at_from=updated_at_from,
            limit=max(self._config.governance_evidence_limit, 1),
        )
        if not outcomes:
            return {}
        by_status = {
            "effective": [item for item in outcomes if item.evaluation_status == "effective"],
            "ineffective": [item for item in outcomes if item.evaluation_status == "ineffective"],
            "inconclusive": [item for item in outcomes if item.evaluation_status == "inconclusive"],
        }
        return {
            "evaluation_ids": [item.id for item in outcomes],
            "ineffective_evaluation_ids": [item.id for item in by_status["ineffective"]],
            "inconclusive_evaluation_ids": [item.id for item in by_status["inconclusive"]],
            "effective_evaluation_ids": [item.id for item in by_status["effective"]],
            "status_counts": {status: len(items) for status, items in by_status.items()},
            "topic_keys": sorted({item.topic_key for item in outcomes if item.topic_key is not None}),
            "improvement_scores": {item.id: item.improvement_score for item in outcomes},
            "observed_attempt_counts": {item.id: item.observed_attempt_count for item in outcomes},
            "reflection_record_ids": {item.id: item.reflection_record_id for item in outcomes},
        }

    @staticmethod
    def _resolver_health_evidence(resolver_failures: list[SkillUsageEvent]) -> dict[str, Any]:
        return {
            "failure_count": len(resolver_failures),
            "resolver_failure_event_ids": [item.id for item in resolver_failures],
            "resolver_statuses": sorted({item.resolver_status for item in resolver_failures}),
            "selection_reasons": sorted({item.selection_reason for item in resolver_failures}),
        }

    def _governance_evidence_metrics(self, evidence: dict[str, Any]) -> dict[str, Any]:
        memory_conflicts = evidence.get("memory_conflicts")
        reflection_outcomes = evidence.get("reflection_outcomes")
        resolver_health = evidence.get("resolver_health")
        metrics: dict[str, Any] = {
            "governance_evidence_enabled": self._config.governance_evidence_enabled,
            "governance_evidence_lookback_days": self._config.governance_evidence_lookback_days,
            "governance_evidence_limit": self._config.governance_evidence_limit,
        }
        if isinstance(memory_conflicts, dict):
            metrics.update(
                {
                    "governance_memory_conflict_open_count": int(memory_conflicts.get("open_count") or 0),
                    "governance_memory_conflict_high_severity_count": int(
                        memory_conflicts.get("high_severity_count") or 0
                    ),
                    "governance_memory_conflict_max_severity": float(memory_conflicts.get("max_severity") or 0.0),
                    "governance_memory_conflict_severity_threshold": self._config.memory_conflict_severity_threshold,
                }
            )
        if isinstance(reflection_outcomes, dict):
            status_counts = reflection_outcomes.get("status_counts")
            if not isinstance(status_counts, dict):
                status_counts = {}
            metrics.update(
                {
                    "governance_reflection_effective_count": int(status_counts.get("effective") or 0),
                    "governance_reflection_ineffective_count": int(status_counts.get("ineffective") or 0),
                    "governance_reflection_inconclusive_count": int(status_counts.get("inconclusive") or 0),
                    "governance_reflection_ineffective_min": self._config.reflection_ineffective_min,
                    "governance_reflection_inconclusive_min": self._config.reflection_inconclusive_min,
                }
            )
        if isinstance(resolver_health, dict):
            metrics["governance_resolver_failure_count"] = int(resolver_health.get("failure_count") or 0)
        tool_plan_sequence = evidence.get("tool_plan_sequence")
        if isinstance(tool_plan_sequence, dict):
            metrics.update(
                {
                    "governance_tool_plan_sequence_enabled": self._config.tool_plan_sequence_evidence_enabled,
                    "governance_tool_plan_expected_step_count": int(tool_plan_sequence.get("expected_step_count") or 0),
                    "governance_tool_plan_matched_usage_count": int(tool_plan_sequence.get("matched_usage_count") or 0),
                    "governance_tool_plan_sequence_mismatch_count": int(
                        tool_plan_sequence.get("sequence_mismatch_count") or 0
                    ),
                    "governance_tool_plan_step_count_mismatch_count": int(
                        tool_plan_sequence.get("step_count_mismatch_count") or 0
                    ),
                    "governance_tool_plan_missing_sequence_metadata_count": int(
                        tool_plan_sequence.get("missing_sequence_metadata_count") or 0
                    ),
                    "governance_tool_plan_missing_repair_task_id_count": int(
                        tool_plan_sequence.get("missing_repair_task_id_count") or 0
                    ),
                    "governance_tool_plan_missing_created_review_task_ids_count": int(
                        tool_plan_sequence.get("missing_created_review_task_ids_count") or 0
                    ),
                }
            )
        return metrics

    def _has_governance_regression(self, evidence: dict[str, Any]) -> bool:
        memory_conflicts = evidence.get("memory_conflicts")
        if isinstance(memory_conflicts, dict) and int(memory_conflicts.get("high_severity_count") or 0) > 0:
            return True
        reflection_outcomes = evidence.get("reflection_outcomes")
        if isinstance(reflection_outcomes, dict):
            status_counts = reflection_outcomes.get("status_counts")
            if isinstance(status_counts, dict):
                if int(status_counts.get("ineffective") or 0) >= self._config.reflection_ineffective_min:
                    return True
                if int(status_counts.get("inconclusive") or 0) >= self._config.reflection_inconclusive_min:
                    return True
        tool_plan_sequence = evidence.get("tool_plan_sequence")
        if isinstance(tool_plan_sequence, dict):
            summary = self._tool_plan_sequence_summary_from_payload(tool_plan_sequence)
            if summary is not None and has_tool_plan_sequence_regression(
                summary=summary,
                mismatch_min=self._config.tool_plan_sequence_mismatch_min,
                missing_metadata_min=self._config.tool_plan_missing_metadata_min,
                required_output_missing_min=self._config.tool_plan_required_output_missing_min,
            ):
                return True
        return False

    def _governance_source_discriminator(self, evidence: dict[str, Any]) -> str:
        sources: list[str] = []
        memory_conflicts = evidence.get("memory_conflicts")
        if isinstance(memory_conflicts, dict) and int(memory_conflicts.get("high_severity_count") or 0) > 0:
            sources.append("memory_conflict")
        reflection_outcomes = evidence.get("reflection_outcomes")
        if isinstance(reflection_outcomes, dict):
            status_counts = reflection_outcomes.get("status_counts")
            if isinstance(status_counts, dict) and (
                int(status_counts.get("ineffective") or 0) > 0
                or int(status_counts.get("inconclusive") or 0) > 0
            ):
                sources.append("reflection_outcome")
        tool_plan_sequence = evidence.get("tool_plan_sequence")
        if isinstance(tool_plan_sequence, dict):
            summary = self._tool_plan_sequence_summary_from_payload(tool_plan_sequence)
            if summary is not None and has_tool_plan_sequence_regression(
                summary=summary,
                mismatch_min=self._config.tool_plan_sequence_mismatch_min,
                missing_metadata_min=self._config.tool_plan_missing_metadata_min,
                required_output_missing_min=self._config.tool_plan_required_output_missing_min,
            ):
                sources.append("tool_plan_sequence")
        if not sources:
            sources.append("none")
        return "governance:" + ",".join(sources)

    def _tool_plan_sequence_evidence(
        self,
        *,
        artifact: SkillArtifact,
        usage_events: list[SkillUsageEvent],
    ) -> dict[str, Any]:
        if not self._config.tool_plan_sequence_evidence_enabled:
            return {}
        contract = build_tool_plan_sequence_contract(surface=artifact.scope, tool_plan=artifact.tool_plan)
        if contract is None:
            return {}
        matched_usage_events = [item for item in usage_events if item.skill_artifact_id == artifact.id]
        if not matched_usage_events:
            return {}
        return summarize_tool_plan_usage(
            contract=contract,
            usage_events=matched_usage_events,
        ).to_payload(contract)

    @staticmethod
    def _tool_plan_sequence_summary_from_payload(payload: dict[str, Any]):
        from agent_core.application.services.tool_plan_sequence_governance import ToolPlanSequenceUsageSummary

        required_lists = (
            "matched_usage_event_ids",
            "mismatch_usage_event_ids",
            "latest_observed_sequences",
        )
        if any(key not in payload for key in required_lists):
            return None
        return ToolPlanSequenceUsageSummary(
            matched_usage_count=int(payload.get("matched_usage_count") or 0),
            sequence_match_count=int(payload.get("sequence_match_count") or 0),
            sequence_mismatch_count=int(payload.get("sequence_mismatch_count") or 0),
            step_count_mismatch_count=int(payload.get("step_count_mismatch_count") or 0),
            missing_sequence_metadata_count=int(payload.get("missing_sequence_metadata_count") or 0),
            missing_repair_task_id_count=int(payload.get("missing_repair_task_id_count") or 0),
            missing_created_review_task_ids_count=int(payload.get("missing_created_review_task_ids_count") or 0),
            matched_usage_event_ids=[str(item) for item in payload.get("matched_usage_event_ids") or []],
            mismatch_usage_event_ids=[str(item) for item in payload.get("mismatch_usage_event_ids") or []],
            latest_observed_sequences=[
                [str(value) for value in item if isinstance(value, str)]
                for item in payload.get("latest_observed_sequences") or []
                if isinstance(item, list)
            ],
        )

    async def _learner_goal_id_for_readiness(self, readiness: SkillReplacementReadiness) -> str | None:
        rollout_id = readiness.rollout_evidence.get("rollout_id")
        if not isinstance(rollout_id, str) or not rollout_id.strip():
            return None
        get_rollout = getattr(self._rollout_repository, "get_by_id", None)
        if get_rollout is None:
            return None
        rollout = await get_rollout(rollout_id)
        if rollout is None:
            return None
        return rollout.learner_goal_id

    @staticmethod
    def _replacement_readiness_evidence_snapshot(
        readiness: SkillReplacementReadiness,
        *,
        ready_action: str,
        learner_goal_id: str | None = None,
    ) -> dict[str, Any]:
        replacement_readiness = {
            "proposal_source": readiness.proposal_source,
            "recommended_action": ready_action,
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
        return {
            "artifact_id": readiness.artifact_id,
            "artifact_status": SkillArtifactStatus.STAGED.value,
            "source_proposal_id": readiness.proposal_id,
            "proposal_source": readiness.proposal_source,
            "learner_goal_id": learner_goal_id,
            "ready_action": ready_action,
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
            "thresholds": dict(replacement_readiness["thresholds"]),
            "checked_at": readiness.checked_at.isoformat(),
            "replacement_readiness": replacement_readiness,
        }

    @staticmethod
    def _replacement_readiness_metrics_snapshot(readiness: SkillReplacementReadiness) -> dict[str, Any]:
        return {
            "replacement_promote_observation_min": readiness.thresholds.promote_observation_min,
            "replacement_successful_usage_min": readiness.thresholds.successful_usage_min,
            "replacement_max_negative_usage_rate": readiness.thresholds.max_negative_usage_rate,
            "replacement_matched_usage_count": int(readiness.usage_evidence["matched_count"]),
            "replacement_successful_usage_count": int(readiness.usage_evidence["successful_count"]),
            "replacement_negative_usage_count": int(readiness.usage_evidence["negative_count"]),
            "replacement_negative_usage_rate": float(readiness.usage_evidence["negative_usage_rate"]),
            "replacement_promote_observation_count": len(readiness.rollout_evidence["promote_observation_ids"]),
        }

    @staticmethod
    def _artifact_topic_keys(artifact: SkillArtifact) -> list[str]:
        match_rules = artifact.definition.get("match_rules")
        if not isinstance(match_rules, dict):
            return []
        values = match_rules.get("topic_keys")
        if not isinstance(values, list):
            return []
        topic_keys: list[str] = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            topic_key = value.strip()
            if topic_key not in topic_keys:
                topic_keys.append(topic_key)
        return topic_keys

    @staticmethod
    def _single_usage_goal_id(events: list[SkillUsageEvent]) -> str | None:
        goal_ids = {item.learner_goal_id for item in events if item.learner_goal_id is not None}
        if len(goal_ids) == 1:
            return next(iter(goal_ids))
        return None

    async def _maybe_recommend_coverage_regression(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        window_key: str,
    ) -> str | None:
        if not self._config.coverage_regression_enabled:
            return None
        declared_topic_keys = self._artifact_topic_keys(artifact)
        if not declared_topic_keys:
            return None

        started_at = now - timedelta(days=max(self._config.usage_lookback_days, 1))
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            surface=artifact.scope,
            created_at_from=started_at,
            limit=200,
        )
        attributed = [item for item in events if item.skill_artifact_id == artifact.id]
        attributed_outside_declared: list[SkillUsageEvent] = []
        binding_gap_events: list[SkillUsageEvent] = []
        declared_set = set(declared_topic_keys)
        uncovered_topic_keys: list[str] = []
        counts_by_topic: dict[str, dict[str, int]] = {}
        attributed_event_ids_by_topic: dict[str, list[str]] = {}
        binding_gap_event_ids_by_topic: dict[str, list[str]] = {}

        for event in attributed:
            topic_key = self._usage_topic_key(event)
            if topic_key is None or topic_key in declared_set:
                continue
            attributed_outside_declared.append(event)
            if topic_key not in uncovered_topic_keys:
                uncovered_topic_keys.append(topic_key)
            counts = counts_by_topic.setdefault(
                topic_key,
                {"attributed_count": 0, "binding_gap_count": 0, "unresolved_count": 0},
            )
            counts["attributed_count"] += 1
            attributed_event_ids_by_topic.setdefault(topic_key, []).append(event.id)
            if self._has_governed_binding_metadata(event=event, artifact=artifact):
                continue
            binding_gap_events.append(event)
            counts["binding_gap_count"] += 1
            binding_gap_event_ids_by_topic.setdefault(topic_key, []).append(event.id)

        drift_topic_keys = sorted(
            topic_key
            for topic_key, counts in counts_by_topic.items()
            if counts["attributed_count"] >= self._config.coverage_drift_topic_min
        )
        hole_topic_keys = sorted(
            topic_key
            for topic_key, counts in counts_by_topic.items()
            if counts["binding_gap_count"] >= self._config.coverage_hole_topic_min
        )
        if not drift_topic_keys and not hole_topic_keys:
            return None

        triggered_topic_keys = sorted(set(drift_topic_keys).union(hole_topic_keys))
        unresolved_event_ids_by_topic: dict[str, list[str]] = {}
        resolver_statuses_by_topic: dict[str, list[str]] = {}
        selection_reasons_by_topic: dict[str, list[str]] = {}
        unresolved_supporting_events: list[SkillUsageEvent] = []
        for event in events:
            topic_key = self._usage_topic_key(event)
            if topic_key is None or topic_key not in triggered_topic_keys:
                continue
            if event.resolver_status not in {"missing_artifact", "blocked", "incompatible"}:
                continue
            unresolved_supporting_events.append(event)
            counts_by_topic.setdefault(
                topic_key,
                {"attributed_count": 0, "binding_gap_count": 0, "unresolved_count": 0},
            )["unresolved_count"] += 1
            unresolved_event_ids_by_topic.setdefault(topic_key, []).append(event.id)
            self._append_unique_value(
                resolver_statuses_by_topic.setdefault(topic_key, []),
                event.resolver_status,
            )
            self._append_unique_value(
                selection_reasons_by_topic.setdefault(topic_key, []),
                event.selection_reason,
            )

        rollout = await self._rollout_for_artifact(artifact)
        learner_goal_id = rollout.learner_goal_id if rollout is not None else self._single_usage_goal_id(attributed)
        evidence_snapshot: dict[str, Any] = {
            "artifact_id": artifact.id,
            "source_artifact_id": artifact.id,
            "artifact_status": artifact.status,
            "artifact_version": artifact.version,
            "lineage_id": artifact.lineage_id,
            "source_proposal_id": artifact.source_proposal_id,
            "learner_goal_id": learner_goal_id,
            "evidence_started_at": started_at.isoformat(),
            "evidence_ended_at": now.isoformat(),
            "coverage_regression": {
                "declared_topic_keys": declared_topic_keys,
                "drift_topic_keys": drift_topic_keys,
                "hole_topic_keys": hole_topic_keys,
                "uncovered_topic_keys": triggered_topic_keys,
                "topic_counts": counts_by_topic,
                "attributed_usage_event_ids_by_topic": attributed_event_ids_by_topic,
                "binding_gap_event_ids_by_topic": binding_gap_event_ids_by_topic,
                "unresolved_usage_event_ids_by_topic": unresolved_event_ids_by_topic,
                "resolver_statuses_by_topic": resolver_statuses_by_topic,
                "selection_reasons_by_topic": selection_reasons_by_topic,
                "binding_gap_reason": (
                    "usage outside declared topic coverage without governed binding metadata"
                ),
                "coverage_reason": "repeated topic demand exceeds declared artifact coverage",
            },
        }
        metrics_snapshot = {
            "coverage_uncovered_topic_count": len(triggered_topic_keys),
            "coverage_drift_topic_count": len(drift_topic_keys),
            "coverage_hole_topic_count": len(hole_topic_keys),
            "coverage_attributed_outside_declared_count": len(attributed_outside_declared),
            "coverage_binding_gap_count": len(binding_gap_events),
            "coverage_unresolved_supporting_count": len(unresolved_supporting_events),
            "coverage_drift_topic_min": self._config.coverage_drift_topic_min,
            "coverage_hole_topic_min": self._config.coverage_hole_topic_min,
            "usage_lookback_days": self._config.usage_lookback_days,
        }
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="patch_needed",
            recommended_action="none",
            reason_code="coverage_regression",
            reason_note="Observed repeated topic demand outside declared artifact coverage.",
            evidence_snapshot=evidence_snapshot,
            metrics_snapshot=metrics_snapshot,
            source_discriminator="coverage:" + ",".join(triggered_topic_keys),
        )

    async def _maybe_recommend_merge_candidate(
        self,
        *,
        artifact: SkillArtifact,
        window_key: str,
    ) -> str | None:
        if artifact.status not in MERGE_SOURCE_ARTIFACT_STATUSES:
            return None
        source_rules = self._merge_match_rule_values(artifact)
        if not source_rules:
            return None
        related_artifacts = await self._merge_related_artifacts(artifact)
        if not related_artifacts:
            return None

        related_overlap: dict[str, dict[str, list[str]]] = {}
        overlap_match_rules: dict[str, list[str]] = {}
        for related in related_artifacts:
            shared = self._shared_merge_rule_values(source_rules, self._merge_match_rule_values(related))
            if not shared:
                continue
            shared_value_count = sum(len(values) for values in shared.values())
            if shared_value_count < self._config.merge_overlap_min_shared_values:
                continue
            related_overlap[related.id] = shared
            for key, values in shared.items():
                aggregate = overlap_match_rules.setdefault(key, [])
                for value in values:
                    if value not in aggregate:
                        aggregate.append(value)

        matched_related = [artifact for artifact in related_artifacts if artifact.id in related_overlap]
        if not matched_related:
            return None

        related_artifact_ids = [item.id for item in matched_related]
        shared_value_count = sum(len(values) for values in overlap_match_rules.values())
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="merge_candidate",
            recommended_action="none",
            reason_code="merge_candidate",
            reason_note="Skill artifacts have overlapping match coverage; review for governed merge.",
            evidence_snapshot={
                "artifact_id": artifact.id,
                "source_artifact_id": artifact.id,
                "artifact_status": artifact.status,
                "artifact_version": artifact.version,
                "lineage_id": artifact.lineage_id,
                "source_proposal_id": artifact.source_proposal_id,
                "source_artifact": self._merge_artifact_evidence(artifact),
                "related_artifact_ids": related_artifact_ids,
                "related_artifacts": {
                    item.id: self._merge_artifact_evidence(item)
                    for item in matched_related
                },
                "related_artifact_versions": {item.id: item.version for item in matched_related},
                "related_artifact_statuses": {item.id: item.status for item in matched_related},
                "related_artifact_lineage_ids": {item.id: item.lineage_id for item in matched_related},
                "overlap_match_rules": overlap_match_rules,
                "related_overlap_match_rules": related_overlap,
                "overlap_reason": "same name/scope or implementation binding with shared match_rules coverage",
            },
            metrics_snapshot={
                "overlap_score": min(1.0, shared_value_count / max(len(MERGE_OVERLAP_RULE_KEYS), 1)),
                "overlap_shared_value_count": shared_value_count,
                "overlap_rule_keys": sorted(overlap_match_rules),
                "related_artifact_count": len(matched_related),
                "merge_overlap_min_shared_values": self._config.merge_overlap_min_shared_values,
            },
            related_artifact_ids=related_artifact_ids,
            source_discriminator="merge:" + ",".join(sorted(related_artifact_ids)),
        )

    async def _maybe_recommend_archive(
        self,
        *,
        artifact: SkillArtifact,
        now: datetime,
        window_key: str,
    ) -> str | None:
        stale_started_at = now - timedelta(days=max(self._config.archive_stale_days, 1))
        deprecated_at = artifact.deprecated_at or artifact.updated_at
        if deprecated_at > stale_started_at:
            return None
        recent_usage = await self._usage_repository.list_events(
            artifact_id=artifact.id,
            created_at_from=stale_started_at,
            limit=1,
        )
        if recent_usage:
            return None
        return await self._create_recommendation_once(
            artifact=artifact,
            window_key=window_key,
            recommendation_type="archive_candidate",
            recommended_action="archive_deprecated",
            reason_code="stale_deprecated",
            reason_note="Deprecated artifact has no recent attributed usage.",
            evidence_snapshot={
                "artifact_id": artifact.id,
                "artifact_status": artifact.status,
                "artifact_version": artifact.version,
                "lineage_id": artifact.lineage_id,
                "source_proposal_id": artifact.source_proposal_id,
                "deprecated_at": deprecated_at.isoformat(),
                "stale_started_at": stale_started_at.isoformat(),
            },
            metrics_snapshot={
                "archive_stale_days": self._config.archive_stale_days,
                "recent_usage_count": len(recent_usage),
            },
        )

    async def _create_recommendation_once(
        self,
        *,
        artifact: SkillArtifact,
        window_key: str,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
        reason_note: str,
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        related_artifact_ids: list[str] | None = None,
        source_discriminator: str | None = None,
    ) -> str:
        source_job_id = self._source_job_id(
            artifact=artifact,
            window_key=window_key,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            reason_code=reason_code,
            source_discriminator=source_discriminator,
        )
        existing = await self._recommendation_repository.get_by_source_job_id(source_job_id)
        if existing is not None:
            await self._audit_service.record(
                event_type="skill.curator.job.recommendation_reused",
                resource_type="skill_curator_recommendation",
                resource_id=existing.id,
                actor="system",
                event_data={
                    "recommendation_id": existing.id,
                    "artifact_id": existing.artifact_id,
                    "skill_name": existing.skill_name,
                    "scope": existing.scope,
                    "surface": existing.surface,
                    "recommendation_type": existing.recommendation_type,
                    "recommended_action": existing.recommended_action,
                    "status": existing.status,
                    "reason_code": existing.reason_code,
                    "source_job_id": source_job_id,
                    "window_key": window_key,
                },
            )
            return "existing"
        recommendation = await self._recommendation_service.create_recommendation(
            artifact_id=artifact.id,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            reason_code=reason_code,
            reason_note=reason_note,
            evidence_snapshot=evidence_snapshot,
            metrics_snapshot=metrics_snapshot,
            related_artifact_ids=related_artifact_ids,
            source_job_id=source_job_id,
            created_by="skill_curator_job",
        )
        await self._maybe_queue_replacement_auto_execution(recommendation=recommendation, source_job_id=source_job_id)
        return "created" if recommendation.source_job_id == source_job_id else "existing"

    async def _maybe_queue_replacement_auto_execution(
        self,
        *,
        recommendation: SkillCuratorRecommendation,
        source_job_id: str,
    ) -> None:
        if self._replacement_auto_execution_scheduler is None:
            return
        if recommendation.status != "pending":
            return
        if recommendation.recommendation_type not in {"activate_candidate", "replace_candidate"}:
            return
        if recommendation.recommended_action not in {"activate_staged", "replace_selectable"}:
            return
        await self._replacement_auto_execution_scheduler.queue_recommendation(
            recommendation,
            source_job_id=source_job_id,
        )

    async def _merge_related_artifacts(self, source_artifact: SkillArtifact) -> list[SkillArtifact]:
        limit = max(self._config.merge_related_scan_limit, 1)
        related: list[SkillArtifact] = []
        seen_ids: set[str] = {source_artifact.id}

        same_name = await self._artifact_repository.list_artifacts(
            name=source_artifact.name,
            scope=source_artifact.scope,
            limit=limit,
        )
        for artifact in same_name:
            self._append_merge_related_artifact(
                related=related,
                seen_ids=seen_ids,
                source_artifact=source_artifact,
                candidate=artifact,
            )

        source_binding = self._implementation_binding(source_artifact)
        if source_binding is None:
            return related
        for status in MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER:
            if len(related) >= limit:
                break
            candidates = await self._artifact_repository.list_artifacts(
                status=status,
                scope=source_artifact.scope,
                limit=limit,
            )
            for candidate in candidates:
                if len(related) >= limit:
                    break
                if self._implementation_binding(candidate) != source_binding:
                    continue
                self._append_merge_related_artifact(
                    related=related,
                    seen_ids=seen_ids,
                    source_artifact=source_artifact,
                    candidate=candidate,
                )
        return related

    @staticmethod
    def _append_merge_related_artifact(
        *,
        related: list[SkillArtifact],
        seen_ids: set[str],
        source_artifact: SkillArtifact,
        candidate: SkillArtifact,
    ) -> None:
        if candidate.id in seen_ids:
            return
        if candidate.status not in MERGE_RELATED_ARTIFACT_STATUSES:
            return
        if not SkillCuratorJobService._merge_candidate_matches_source(
            source_artifact=source_artifact,
            candidate=candidate,
        ):
            return
        related.append(candidate)
        seen_ids.add(candidate.id)

    @staticmethod
    def _merge_candidate_matches_source(
        *,
        source_artifact: SkillArtifact,
        candidate: SkillArtifact,
    ) -> bool:
        if candidate.scope != source_artifact.scope:
            return False
        if candidate.name == source_artifact.name:
            return True
        source_binding = SkillCuratorJobService._implementation_binding(source_artifact)
        candidate_binding = SkillCuratorJobService._implementation_binding(candidate)
        return source_binding is not None and candidate_binding == source_binding

    @staticmethod
    def _implementation_binding(artifact: SkillArtifact) -> str | None:
        value = artifact.compatibility_contract.get("implementation_binding")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _merge_match_rule_values(artifact: SkillArtifact) -> dict[str, list[str]]:
        match_rules = artifact.definition.get("match_rules")
        if not isinstance(match_rules, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key in MERGE_OVERLAP_RULE_KEYS:
            values = match_rules.get(key)
            if not isinstance(values, list):
                continue
            normalized: list[str] = []
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    continue
                item = value.strip()
                if item not in normalized:
                    normalized.append(item)
            if normalized:
                result[key] = normalized
        return result

    @staticmethod
    def _shared_merge_rule_values(
        source_rules: dict[str, list[str]],
        related_rules: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        shared: dict[str, list[str]] = {}
        for key in MERGE_OVERLAP_RULE_KEYS:
            source_values = set(source_rules.get(key, []))
            related_values = related_rules.get(key, [])
            values = [item for item in related_values if item in source_values]
            if values:
                shared[key] = values
        return shared

    @staticmethod
    def _merge_artifact_evidence(artifact: SkillArtifact) -> dict[str, Any]:
        return {
            "artifact_id": artifact.id,
            "name": artifact.name,
            "scope": artifact.scope,
            "version": artifact.version,
            "status": artifact.status,
            "lineage_id": artifact.lineage_id,
            "parent_artifact_id": artifact.parent_artifact_id,
            "supersedes_artifact_id": artifact.supersedes_artifact_id,
            "source_proposal_id": artifact.source_proposal_id,
            "implementation_binding": SkillCuratorJobService._implementation_binding(artifact),
        }

    async def _rollout_for_artifact(self, artifact: SkillArtifact) -> ReflectionProposalRollout | None:
        if artifact.source_proposal_id is None:
            return None
        rollout = await self._rollout_repository.get_by_proposal(artifact.source_proposal_id)
        if rollout is None or rollout.proposal_id != artifact.source_proposal_id:
            return None
        return rollout

    async def _binding_for_rollout(
        self,
        *,
        artifact: SkillArtifact,
        rollout: ReflectionProposalRollout,
    ) -> GoalSkillBinding | None:
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is None:
            return None
        if (
            binding.status != "rolled_out"
            or binding.proposal_id != artifact.source_proposal_id
            or binding.rollout_id != rollout.id
            or binding.surface != artifact.scope
        ):
            return None
        return binding

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
            and item.proposal_id == artifact.source_proposal_id
            and item.surface == artifact.scope
        ]
        relevant = sorted(relevant, key=lambda item: (item.created_at, item.id), reverse=True)
        recent = relevant[: self._config.promote_observation_min]
        if len(recent) < self._config.promote_observation_min:
            return []
        if any(item.recommendation != "promote" for item in recent):
            return []
        return recent

    async def _latest_rollout_observation(
        self,
        rollout: ReflectionProposalRollout,
    ) -> ReflectionProposalRolloutObservation | None:
        if rollout.latest_observation_id is not None:
            observation = await self._rollout_observation_repository.get_by_id(rollout.latest_observation_id)
            if observation is not None:
                return observation
        observations = await self._rollout_observation_repository.list_by_rollout(rollout.id)
        if not observations:
            return None
        return sorted(observations, key=lambda item: (item.created_at, item.id), reverse=True)[0]

    async def _rollout_usage_metrics(
        self,
        *,
        artifact: SkillArtifact,
        rollout: ReflectionProposalRollout,
        binding: GoalSkillBinding,
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
            if not self._matches_rollout_metadata(
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
    def _matches_rollout_metadata(
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

    @staticmethod
    def _usage_topic_key(event: SkillUsageEvent) -> str | None:
        if not isinstance(event.topic_key, str):
            return None
        topic_key = event.topic_key.strip()
        return topic_key or None

    @staticmethod
    def _append_unique_value(values: list[str], candidate: str | None) -> None:
        if not isinstance(candidate, str) or not candidate or candidate in values:
            return
        values.append(candidate)

    @staticmethod
    def _has_governed_binding_metadata(
        *,
        event: SkillUsageEvent,
        artifact: SkillArtifact,
    ) -> bool:
        rollout_metadata = event.metadata.get("skill_package_rollout")
        if not isinstance(rollout_metadata, dict):
            return False
        required_keys = ("proposal_id", "rollout_id", "binding_id")
        if any(not isinstance(rollout_metadata.get(key), str) or not str(rollout_metadata.get(key)).strip() for key in required_keys):
            return False
        return (
            rollout_metadata.get("skill_name") == artifact.name
            and rollout_metadata.get("surface") == artifact.scope
        )

    @staticmethod
    def _source_job_id(
        *,
        artifact: SkillArtifact,
        window_key: str,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
        source_discriminator: str | None = None,
    ) -> str:
        parts = [
            "agent-edu",
            "skill-curator",
            window_key,
            artifact.id,
            recommendation_type,
            recommended_action,
            reason_code,
        ]
        if source_discriminator is not None:
            parts.append(source_discriminator)
        return str(
            uuid5(
                NAMESPACE_URL,
                ":".join(parts),
            )
        )


class SkillResolver:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
        skill_registry: SkillRegistry,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service
        self._skill_registry = skill_registry

    async def resolve(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        audit: bool = True,
    ) -> SkillResolution:
        if not self._skill_registry.has_skill(skill_name):
            raise ValidationError(f"Skill '{skill_name}' is not enabled.")
        default_binding = self._skill_registry.default_handler_for_skill(skill_name)
        suppressed = await self._artifact_repository.get_suppressed_by_name_scope(name=skill_name, scope=surface)
        if suppressed is not None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=suppressed.id,
                skill_version=suppressed.version,
                artifact_status=suppressed.status,
                resolver_status="blocked",
                selection_reason="suppressed_artifact",
                implementation_binding=str(suppressed.compatibility_contract.get("implementation_binding") or default_binding),
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.blocked",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        artifact = await self._artifact_repository.get_selectable_by_name_scope(name=skill_name, scope=surface)
        if artifact is None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=None,
                skill_version=None,
                artifact_status=None,
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
                implementation_binding=default_binding,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.missing_artifact",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        implementation_binding = str(artifact.compatibility_contract.get("implementation_binding") or "")
        surfaces = artifact.compatibility_contract.get("surfaces")
        if (
            artifact.compatibility_contract.get("dynamic_execution") is not False
            or not implementation_binding
            or not self._skill_registry.has_runtime_handler(implementation_binding)
            or not self._skill_registry.supports_runtime_handler(implementation_binding, surface=surface)
            or not isinstance(surfaces, list)
            or surfaces != [surface]
        ):
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=artifact.id,
                skill_version=artifact.version,
                artifact_status=artifact.status,
                resolver_status="incompatible",
                selection_reason="contract_incompatible",
                implementation_binding=implementation_binding or default_binding,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.incompatible",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        resolution = SkillResolution.build(
            skill_name=skill_name,
            surface=surface,
            artifact_id=artifact.id,
            skill_version=artifact.version,
            artifact_status=artifact.status,
            resolver_status="resolved",
            selection_reason="production_default",
            implementation_binding=implementation_binding,
        )
        observe_skill_resolution(
            surface=surface,
            resolver_status=resolution.resolver_status,
            selection_reason=resolution.selection_reason,
        )
        return resolution

    async def build_execution_plan(
        self,
        *,
        resolution: SkillResolution,
        skill_binding: ActiveGoalSkillBinding | None = None,
    ) -> SkillExecutionPlan:
        if resolution.resolver_status in {"blocked", "incompatible"}:
            raise ValidationError(f"Skill resolution is {resolution.resolver_status}.")
        base_runtime_directives: dict[str, Any] = {}
        base_tool_plan: list[dict[str, Any]] = []
        if resolution.artifact_id is not None:
            artifact = await self._artifact_repository.get_by_id(resolution.artifact_id)
            if artifact is None:
                raise ValidationError("Resolved skill artifact is missing.")
            base_runtime_directives = dict(artifact.runtime_directives)
            base_tool_plan = [dict(item) for item in artifact.tool_plan]
        binding_runtime_directives = (
            dict(skill_binding.runtime_directives)
            if skill_binding is not None
            else {}
        )
        effective_tool_plan = (
            [dict(item) for item in skill_binding.tool_plan]
            if skill_binding is not None and skill_binding.tool_plan
            else base_tool_plan
        )
        binding_metadata = (
            skill_binding.usage_metadata(skill_name=resolution.skill_name)
            if skill_binding is not None
            else {}
        )
        return SkillExecutionPlan(
            resolution=resolution,
            execution_kind=self._skill_registry.runtime_handler_execution_kind(resolution.implementation_binding),
            runtime_directives={
                **base_runtime_directives,
                **binding_runtime_directives,
            },
            tool_plan=effective_tool_plan,
            binding_metadata=binding_metadata,
        )

    async def _audit_resolution(
        self,
        resolution: SkillResolution,
        *,
        event_type: str,
        resource_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill",
            resource_id=resource_id or resolution.artifact_id,
            actor="system",
            event_data={
                "skill_name": resolution.skill_name,
                "surface": resolution.surface,
                "artifact_id": resolution.artifact_id,
                "skill_version": resolution.skill_version,
                "artifact_status": resolution.artifact_status,
                "resolver_status": resolution.resolver_status,
                "selection_reason": resolution.selection_reason,
                "implementation_binding": resolution.implementation_binding,
            },
        )


class SkillUsageService:
    def __init__(
        self,
        *,
        usage_repository: SkillUsageEventRepository,
        skill_resolver: SkillResolver,
        audit_service: AuditService,
    ) -> None:
        self._usage_repository = usage_repository
        self._skill_resolver = skill_resolver
        self._audit_service = audit_service

    async def resolve_for_runtime(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
    ) -> SkillResolution:
        resolution = await self._skill_resolver.resolve(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )
        if resolution.resolver_status in {"blocked", "incompatible"}:
            raise ValidationError(f"Skill resolution is {resolution.resolver_status}.")
        return resolution

    async def resolve_execution_plan(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        skill_binding: ActiveGoalSkillBinding | None = None,
    ) -> SkillExecutionPlan:
        resolution = await self.resolve_for_runtime(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )
        return await self._skill_resolver.build_execution_plan(
            resolution=resolution,
            skill_binding=skill_binding,
        )

    async def record_usage(
        self,
        *,
        skill_name: str,
        surface: str,
        outcome_status: str,
        resolution: SkillResolution | None = None,
        learner_profile_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        daily_task_id: str | None = None,
        workflow_run_id: str | None = None,
        topic_key: str | None = None,
        trigger_source: str | None = None,
        latency_ms: int | None = None,
        cost_units: float | None = None,
        input_summary: str | None = None,
        input_fingerprint: str | None = None,
        output_summary: str | None = None,
        output_fingerprint: str | None = None,
        error_code: str | None = None,
        outcome_signals: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillUsageEvent | None:
        resolution_error_code: str | None = None
        if resolution is None:
            try:
                resolution = await self._skill_resolver.resolve(
                    skill_name=skill_name,
                    surface=surface,
                    resource_id=session_id or daily_task_id or workflow_run_id,
                )
            except ValidationError:
                resolution = SkillResolution.build(
                    skill_name=skill_name,
                    surface=surface,
                    artifact_id=None,
                    skill_version=None,
                    artifact_status=None,
                    resolver_status="blocked",
                    selection_reason="runtime_resolution_failed",
                    implementation_binding=skill_name,
                )
                resolution_error_code = "SkillResolutionValidationError"
        elif resolution.skill_name != skill_name or resolution.surface != surface:
            raise ValidationError("Skill resolution does not match usage context.")
        event = SkillUsageEvent.build(
            skill_artifact_id=resolution.artifact_id,
            skill_name=resolution.skill_name,
            skill_version=resolution.skill_version,
            skill_status_at_use=resolution.artifact_status,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            surface=surface,
            topic_key=topic_key,
            trigger_source=trigger_source,
            outcome_status=outcome_status,
            latency_ms=latency_ms,
            cost_units=cost_units,
            input_summary=self._truncate(input_summary),
            input_fingerprint=input_fingerprint or self._fingerprint(input_summary),
            output_summary=self._truncate(output_summary),
            output_fingerprint=output_fingerprint or self._fingerprint(output_summary),
            error_code=error_code or resolution_error_code,
            resolver_status=resolution.resolver_status,
            selection_reason=resolution.selection_reason,
            outcome_signals=outcome_signals,
            metadata=metadata,
        )
        try:
            await self._persist_usage_event(event)
            return event
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="skill.usage.record_failed",
                resource_type="skill",
                resource_id=event.skill_artifact_id,
                actor="system",
                event_data={
                    "skill_name": event.skill_name,
                    "skill_version": event.skill_version,
                    "skill_status_at_use": event.skill_status_at_use,
                    "surface": event.surface,
                    "outcome_status": event.outcome_status,
                    "resolver_status": event.resolver_status,
                    "selection_reason": event.selection_reason,
                    "learner_profile_id": event.learner_profile_id,
                    "learner_goal_id": event.learner_goal_id,
                    "session_id": event.session_id,
                    "daily_task_id": event.daily_task_id,
                    "workflow_run_id": event.workflow_run_id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

    async def _persist_usage_event(self, event: SkillUsageEvent) -> None:
        await self._usage_repository.create(event)
        observe_skill_usage_event(
            surface=event.surface,
            outcome_status=event.outcome_status,
            resolver_status=event.resolver_status,
            selection_reason=event.selection_reason,
        )
        await self._audit_service.record(
            event_type="skill.usage.recorded",
            resource_type="skill",
            resource_id=event.skill_artifact_id,
            actor="system",
            event_data={
                "usage_event_id": event.id,
                "skill_name": event.skill_name,
                "skill_version": event.skill_version,
                "skill_status_at_use": event.skill_status_at_use,
                "surface": event.surface,
                "outcome_status": event.outcome_status,
                "resolver_status": event.resolver_status,
                "selection_reason": event.selection_reason,
                "learner_profile_id": event.learner_profile_id,
                "learner_goal_id": event.learner_goal_id,
                "session_id": event.session_id,
                "daily_task_id": event.daily_task_id,
                "workflow_run_id": event.workflow_run_id,
            },
        )

    async def list_usage_by_artifact(self, artifact_id: str, *, limit: int = 50) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_by_artifact(artifact_id, limit=bounded_limit(limit))

    async def list_usage(
        self,
        *,
        artifact_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        surface: str | None = None,
        outcome_status: str | None = None,
        resolver_status: str | None = None,
        limit: int = 50,
    ) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_events(
            artifact_id=artifact_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            surface=surface,
            outcome_status=outcome_status,
            resolver_status=resolver_status,
            limit=bounded_limit(limit),
        )

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if len(stripped) <= 500:
            return stripped
        return stripped[:497] + "..."

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            return sha256(b"").hexdigest()
        return sha256(normalized.encode("utf-8")).hexdigest()
