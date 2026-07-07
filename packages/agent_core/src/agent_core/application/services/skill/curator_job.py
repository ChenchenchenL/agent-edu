"""Skill curator job service.

This module handles background curator job scanning, evidence aggregation,
recommendation generation, and auto execution enqueueing. The job scans
active/stable/staged/deprecated artifacts, aggregates usage/rollout/memory/
reflection/resolver/coverage/merge evidence, generates recommendations,
and optionally enqueues replacement auto execution.

The job maintains bounded scan limits and idempotent recommendation creation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.skill.constants import (
    MERGE_OVERLAP_RULE_KEYS,
    MERGE_RELATED_ARTIFACT_STATUSES,
    MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER,
    MERGE_SOURCE_ARTIFACT_STATUSES,
    REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE,
    REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN,
    REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN,
    STABLE_MAX_NEGATIVE_USAGE_RATE,
    STABLE_MIN_SUCCESSFUL_USAGE_COUNT,
    STABLE_NEGATIVE_USAGE_STATUSES,
    STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT,
    STABLE_SUCCESSFUL_USAGE_STATUSES,
)
from agent_core.application.services.skill.readiness import (
    SkillReplacementReadiness,
    SkillReplacementReadinessService,
    matches_rollout_metadata,
)
from agent_core.application.services.skill.recommendations import SkillCuratorRecommendationService
from agent_core.application.services.tool_plan_sequence_governance import (
    ToolPlanSequenceUsageSummary,
    build_tool_plan_sequence_contract,
    has_tool_plan_sequence_regression,
    summarize_tool_plan_usage,
)
from agent_core.domain.constants import SkillArtifactStatus
from agent_core.domain.entities.memory import MemoryConflictSet
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation, SkillUsageEvent
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    MemoryConflictRepository,
    ReflectionOutcomeEvaluationRepository,
    ReflectionProposalRolloutDecisionRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    SkillArtifactRepository,
    SkillCuratorRecommendationRepository,
    SkillUsageEventRepository,
)
from agent_core.infrastructure.observability.metrics import (
    observe_skill_curator_job,
    observe_routing_regression,
    observe_low_confidence_burst,
)

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

            outcome_gain = await self._maybe_recommend_learning_gain_review(
                artifact=artifact,
                now=now,
                window_key=window_key,
            )
            if outcome_gain is not None:
                outcomes.append(outcome_gain)

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
        # Learning gain check is optional for backward compatibility.
        # Artifacts without mastery data (has_learning_gain_evidence=False) can still be promoted
        # based on runtime success metrics alone. This allows older artifacts deployed before
        # mastery tracking was enabled to be promoted without requiring retrofitting mastery data.
        if usage_metrics.get("has_learning_gain_evidence"):
            if usage_metrics.get("learning_gain_rate", 0.0) < 0.01:
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
        if has_governance_signal:
            routing_regression = governance_evidence.get("routing_regression") or {}
            fallback_pressure = governance_evidence.get("fallback_pressure") or {}
            low_conf = governance_evidence.get("low_confidence_selection_burst") or {}
            retrieval_conflict = governance_evidence.get("retrieval_conflict_exposure") or {}

            # 1. Routing regression:
            if routing_regression.get("detected") or fallback_pressure.get("detected"):
                observe_routing_regression(
                    skill_name=artifact.name,
                    surface=artifact.scope or "unknown",
                )
            if low_conf.get("detected"):
                observe_low_confidence_burst(
                    skill_name=artifact.name,
                    surface=artifact.scope or "unknown",
                )
            if routing_regression.get("detected") or fallback_pressure.get("detected") or low_conf.get("detected"):
                return await self._create_recommendation_once(
                    artifact=artifact,
                    window_key=window_key,
                    recommendation_type="patch_routing_policy",
                    recommended_action="none",
                    reason_code="routing_regression",
                    reason_note="Capability routing failure, fallback pressure, or selection burst detected.",
                    evidence_snapshot=evidence_snapshot,
                    metrics_snapshot=metrics_snapshot,
                    source_discriminator=f"routing:{artifact.id}",
                )

            # 2. Template policy sequence mismatch:
            tool_plan_sequence = governance_evidence.get("tool_plan_sequence")
            if isinstance(tool_plan_sequence, dict):
                summary = self._tool_plan_sequence_summary_from_payload(tool_plan_sequence)
                if summary is not None and has_tool_plan_sequence_regression(
                    summary=summary,
                    mismatch_min=self._config.tool_plan_sequence_mismatch_min,
                    missing_metadata_min=self._config.tool_plan_missing_metadata_min,
                    required_output_missing_min=self._config.tool_plan_required_output_missing_min,
                ):
                    return await self._create_recommendation_once(
                        artifact=artifact,
                        window_key=window_key,
                        recommendation_type="patch_template_policy",
                        recommended_action="none",
                        reason_code="template_sequence_mismatch",
                        reason_note="Tool plan sequence contract mismatch or template mismatch detected.",
                        evidence_snapshot=evidence_snapshot,
                        metrics_snapshot=metrics_snapshot,
                        source_discriminator=f"template:{artifact.id}",
                    )

            # 3. Retrieval conflict / memory conflicts:
            if retrieval_conflict.get("detected"):
                return await self._create_recommendation_once(
                    artifact=artifact,
                    window_key=window_key,
                    recommendation_type="patch_skill_package",
                    recommended_action="none",
                    reason_code="memory_retrieval_conflict",
                    reason_note="Memory or knowledge retrieval conflict detected.",
                    evidence_snapshot=evidence_snapshot,
                    metrics_snapshot=metrics_snapshot,
                    source_discriminator=f"memory_conflict:{artifact.id}",
                )

            # 4. General governance outcomes (ineffective/inconclusive):
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="select_replacement_skill_package",
                recommended_action="none",
                reason_code="governance_evidence_regression",
                reason_note="Governance evidence shows reflection outcome regressions requiring replacement selection.",
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

    async def _maybe_recommend_learning_gain_review(
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
        if not matched:
            return None

        completed = sum(1 for e in matched if e.outcome_status == "completed")
        total = len(matched)
        completion_rate = completed / total if total > 0 else 0.0

        valid_gain_events = []
        for item in matched:
            signals = item.outcome_signals or {}
            delta = signals.get("mastery_delta")
            before = signals.get("mastery_before")
            after = signals.get("mastery_after")
            if before is not None and after is not None:
                try:
                    before_val = float(before)
                    after_val = float(after)
                    # Validate mastery values are in [0, 1] range
                    if 0.0 <= before_val <= 1.0 and 0.0 <= after_val <= 1.0:
                        delta = after_val - before_val
                except (ValueError, TypeError):
                    pass
            if delta is not None:
                try:
                    delta_val = float(delta)
                    # Validate delta is reasonable (abs <= 1.0)
                    if abs(delta_val) <= 1.0:
                        valid_gain_events.append(delta_val)
                except (ValueError, TypeError):
                    pass

        if not valid_gain_events:
            return None

        learning_gain_rate = sum(valid_gain_events) / len(valid_gain_events)

        if completion_rate >= 0.7 and learning_gain_rate < 0.0:
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="demote_candidate",
                recommended_action="demote_active",
                reason_code="poor_learning_outcome",
                reason_note="High runtime success but poor/negative learning outcome detected.",
                evidence_snapshot={
                    "artifact_id": artifact.id,
                    "artifact_status": artifact.status,
                    "completion_rate": completion_rate,
                    "learning_gain_rate": learning_gain_rate,
                },
                metrics_snapshot={
                    "completion_rate": completion_rate,
                    "learning_gain_rate": learning_gain_rate,
                },
                source_discriminator=f"demote:{artifact.id}",
            )

        if learning_gain_rate < 0.02:
            return await self._create_recommendation_once(
                artifact=artifact,
                window_key=window_key,
                recommendation_type="patch_needed",
                recommended_action="none",
                reason_code="low_learning_gain",
                reason_note="Artifact has low learning gain rate, requiring a patch.",
                evidence_snapshot={
                    "artifact_id": artifact.id,
                    "artifact_status": artifact.status,
                    "learning_gain_rate": learning_gain_rate,
                },
                metrics_snapshot={
                    "learning_gain_rate": learning_gain_rate,
                },
                source_discriminator=f"patch_needed:{artifact.id}",
            )

        return None

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
        memory_conflicts = None
        if learner_goal_id is not None and topic_keys:
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

        # Compute the new unified governance signals from usage_events and resolver_failures:
        has_routing_mismatch = any(
            (item.metadata or {}).get("routing_mismatch") is True 
            or (item.metadata or {}).get("router_mismatch") is True
            for item in usage_events
        )
        evidence["routing_regression"] = {
            "detected": len(resolver_failures) >= 2 or has_routing_mismatch,
            "mismatch_count": sum(1 for item in usage_events if (item.metadata or {}).get("routing_mismatch") is True or (item.metadata or {}).get("router_mismatch") is True),
        }
        
        fallback_counts = sum(
            1 for item in usage_events 
            if item.resolver_status == "fallback" 
            or (item.metadata or {}).get("fallback_used") is True
        )
        evidence["fallback_pressure"] = {
            "detected": fallback_counts >= 2,
            "fallback_count": fallback_counts,
        }
        
        low_conf_counts = sum(
            1 for item in usage_events 
            if item.selection_reason == "low_confidence"
            or "low_confidence" in ((item.metadata or {}).get("fallback_chain") or [])
            or (item.metadata or {}).get("confidence", 1.0) < 0.6
            or ((item.metadata or {}).get("capability") or {}).get("confidence", 1.0) < 0.6
        )
        evidence["low_confidence_selection_burst"] = {
            "detected": low_conf_counts >= 2,
            "low_confidence_count": low_conf_counts,
        }
        
        # Check retrieval conflict exposure: memory conflicts or retrieval mismatches
        memory_conflict_count = int(memory_conflicts.get("high_severity_count") or 0) if memory_conflicts else 0
        has_retrieval_conflict = any(
            (item.metadata or {}).get("retrieval_conflict") is True 
            for item in usage_events
        )
        evidence["retrieval_conflict_exposure"] = {
            "detected": memory_conflict_count > 0 or has_retrieval_conflict,
            "conflict_count": memory_conflict_count + sum(1 for item in usage_events if (item.metadata or {}).get("retrieval_conflict") is True),
        }

        # Keep checking if we actually generated any evidence beyond the metadata
        if set(evidence) == {
            "learner_goal_id",
            "topic_keys",
            "evidence_started_at",
            "usage_evidence_started_at",
            "evidence_ended_at",
            "routing_regression",
            "fallback_pressure",
            "low_confidence_selection_burst",
            "retrieval_conflict_exposure",
        } and not evidence.get("routing_regression", {}).get("detected") \
          and not evidence.get("fallback_pressure", {}).get("detected") \
          and not evidence.get("low_confidence_selection_burst", {}).get("detected") \
          and not evidence.get("retrieval_conflict_exposure", {}).get("detected"):
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
        if (evidence.get("routing_regression") or {}).get("detected") is True:
            return True
        if (evidence.get("fallback_pressure") or {}).get("detected") is True:
            return True
        if (evidence.get("low_confidence_selection_burst") or {}).get("detected") is True:
            return True
        if (evidence.get("retrieval_conflict_exposure") or {}).get("detected") is True:
            return True

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
        valid_gain_events = []
        for event in matched:
            signals = event.outcome_signals or {}
            delta = signals.get("mastery_delta")
            before = signals.get("mastery_before")
            after = signals.get("mastery_after")
            if before is not None and after is not None:
                try:
                    before_val = float(before)
                    after_val = float(after)
                    # Validate mastery values are in [0, 1] range
                    if 0.0 <= before_val <= 1.0 and 0.0 <= after_val <= 1.0:
                        delta = after_val - before_val
                except (ValueError, TypeError):
                    pass
            if delta is not None:
                try:
                    delta_val = float(delta)
                    # Validate delta is reasonable (abs <= 1.0)
                    if abs(delta_val) <= 1.0:
                        valid_gain_events.append(delta_val)
                except (ValueError, TypeError):
                    pass
        learning_gain_rate = sum(valid_gain_events) / len(valid_gain_events) if valid_gain_events else 0.0

        return {
            "matched_count": len(matched),
            "successful_count": len(successful),
            "negative_count": len(negative),
            "negative_usage_rate": negative_usage_rate,
            "matched_usage_event_ids": [item.id for item in matched],
            "successful_usage_event_ids": [item.id for item in successful],
            "negative_usage_event_ids": [item.id for item in negative],
            "learning_gain_rate": learning_gain_rate,
            "has_learning_gain_evidence": len(valid_gain_events) > 0,
        }


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

