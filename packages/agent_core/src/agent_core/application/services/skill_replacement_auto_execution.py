from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.skills import (
    SkillCuratorRecommendationService,
    SkillReplacementReadiness,
    SkillReplacementReadinessService,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation
from agent_core.domain.errors import ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalRepository,
    ScheduledAutonomyJobRepository,
    SkillArtifactRepository,
    SkillCuratorRecommendationRepository,
)
from agent_core.infrastructure.observability.metrics import observe_skill_replacement_auto_execution

SKILL_REPLACEMENT_AUTO_EXECUTION_JOB_TYPE = "skill_replacement_auto_execution"
SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR = "system:auto_replacement_governor"
SKILL_REPLACEMENT_AUTO_EXECUTION_TRIGGER_SOURCE = "skill_curator_auto_execution"

AUTO_EXECUTABLE_RECOMMENDATION_TYPES = frozenset({"activate_candidate", "replace_candidate"})
AUTO_EXECUTABLE_RECOMMENDED_ACTIONS = frozenset({"activate_staged", "replace_selectable"})
AUTO_EXECUTION_REASON_CODES = {
    "activate_staged": "source_selectable_missing",
    "replace_selectable": "superseded",
}


@dataclass(frozen=True)
class SkillReplacementAutoExecutionConfig:
    enabled: bool = False
    scan_limit: int = 20
    surfaces: frozenset[str] = frozenset({"review_scheduling", "assessment_generation", "replan"})
    rate_limit_24h: int = 3


@dataclass(frozen=True)
class SkillReplacementAutoExecutionQueueResult:
    status: str
    job_id: str | None = None


@dataclass(frozen=True)
class SkillReplacementAutoExecutionResult:
    executed_count: int = 0
    skipped_count: int = 0

    @property
    def processed_count(self) -> int:
        return self.executed_count + self.skipped_count


class SkillReplacementAutoExecutionScheduler:
    def __init__(
        self,
        *,
        recommendation_repository: SkillCuratorRecommendationRepository,
        proposal_repository: ReflectionProposalRepository,
        autonomy_job_repository: ScheduledAutonomyJobRepository | None,
        autonomy_job_service: AutonomyJobService | None,
        audit_service: AuditService,
        config: SkillReplacementAutoExecutionConfig | None = None,
    ) -> None:
        self._recommendation_repository = recommendation_repository
        self._proposal_repository = proposal_repository
        self._autonomy_job_repository = autonomy_job_repository
        self._autonomy_job_service = autonomy_job_service
        self._audit_service = audit_service
        self._config = config or SkillReplacementAutoExecutionConfig()

    async def queue_recommendation(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        source_job_id: str,
        due_at: datetime | None = None,
    ) -> SkillReplacementAutoExecutionQueueResult:
        if not _is_auto_executable_recommendation(recommendation):
            return SkillReplacementAutoExecutionQueueResult(status="ignored")
        if recommendation.status != "pending" or recommendation.created_by != "skill_curator_job":
            return SkillReplacementAutoExecutionQueueResult(status="ignored")
        if not self._config.enabled:
            await self._audit_queue_skipped(
                recommendation=recommendation,
                reason_code="auto_execution_disabled",
                reason_note="Automatic staged replacement execution is disabled.",
                learner_goal_id=await self._learner_goal_id(recommendation),
            )
            return SkillReplacementAutoExecutionQueueResult(status="skipped")
        if recommendation.surface not in self._config.surfaces:
            await self._audit_queue_skipped(
                recommendation=recommendation,
                reason_code="surface_not_allowed",
                reason_note="Recommendation surface is not in the auto-execution allowlist.",
                learner_goal_id=await self._learner_goal_id(recommendation),
            )
            return SkillReplacementAutoExecutionQueueResult(status="skipped")
        if self._autonomy_job_service is None or self._autonomy_job_repository is None:
            await self._audit_queue_skipped(
                recommendation=recommendation,
                reason_code="autonomy_jobs_unavailable",
                reason_note="Autonomy job infrastructure is not configured.",
                learner_goal_id=await self._learner_goal_id(recommendation),
            )
            return SkillReplacementAutoExecutionQueueResult(status="skipped")

        learner_goal_id = await self._learner_goal_id(recommendation)
        if learner_goal_id is None:
            await self._audit_queue_skipped(
                recommendation=recommendation,
                reason_code="learner_goal_missing",
                reason_note="Automatic execution requires learner_goal_id evidence.",
                learner_goal_id=None,
            )
            return SkillReplacementAutoExecutionQueueResult(status="skipped")

        idempotency_key = f"{SKILL_REPLACEMENT_AUTO_EXECUTION_JOB_TYPE}:{recommendation.id}:{source_job_id}"
        existing = await self._autonomy_job_repository.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return SkillReplacementAutoExecutionQueueResult(status="existing", job_id=existing.id)

        scheduled = await self._autonomy_job_service.create_job(
            learner_goal_id=learner_goal_id,
            job_type=SKILL_REPLACEMENT_AUTO_EXECUTION_JOB_TYPE,
            trigger_source=SKILL_REPLACEMENT_AUTO_EXECUTION_TRIGGER_SOURCE,
            due_at=due_at or recommendation.updated_at,
            idempotency_key=idempotency_key,
            payload={
                "recommendation_id": recommendation.id,
                "source_job_id": source_job_id,
            },
        )
        if scheduled is None:
            await self._audit_queue_skipped(
                recommendation=recommendation,
                reason_code="autonomy_jobs_unavailable",
                reason_note="Autonomy job service did not create a job.",
                learner_goal_id=learner_goal_id,
            )
            return SkillReplacementAutoExecutionQueueResult(status="skipped")

        await self._audit_service.record(
            event_type="skill.curator.recommendation.auto_execution.queued",
            resource_type="skill_curator_recommendation",
            resource_id=recommendation.id,
            actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
            event_data={
                **self._event_data(
                    recommendation=recommendation,
                    learner_goal_id=learner_goal_id,
                    decision_reason_code="queued",
                    source_job_id=source_job_id,
                    autonomy_job_id=scheduled.id,
                ),
                "autonomy_job_due_at": scheduled.due_at.isoformat(),
            },
        )
        observe_skill_replacement_auto_execution(
            event="queued",
            action=recommendation.recommended_action,
            surface=recommendation.surface,
            reason_code="queued",
        )
        return SkillReplacementAutoExecutionQueueResult(status="queued", job_id=scheduled.id)

    async def _audit_queue_skipped(
        self,
        *,
        recommendation: SkillCuratorRecommendation,
        reason_code: str,
        reason_note: str,
        learner_goal_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type="skill.curator.recommendation.auto_execution.queue_skipped",
            resource_type="skill_curator_recommendation",
            resource_id=recommendation.id,
            actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
            event_data=self._event_data(
                recommendation=recommendation,
                learner_goal_id=learner_goal_id,
                decision_reason_code=reason_code,
                decision_reason_note=reason_note,
            ),
        )
        observe_skill_replacement_auto_execution(
            event="queue_skipped",
            action=recommendation.recommended_action,
            surface=recommendation.surface,
            reason_code=reason_code,
        )

    async def _learner_goal_id(self, recommendation: SkillCuratorRecommendation) -> str | None:
        value = _optional_str(recommendation.evidence_snapshot.get("learner_goal_id"))
        if value is not None:
            return value
        proposal_id = _optional_str(recommendation.evidence_snapshot.get("source_proposal_id"))
        if proposal_id is None:
            return None
        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            return None
        return proposal.learner_goal_id

    @staticmethod
    def _event_data(
        *,
        recommendation: SkillCuratorRecommendation,
        learner_goal_id: str | None,
        decision_reason_code: str,
        decision_reason_note: str | None = None,
        source_job_id: str | None = None,
        autonomy_job_id: str | None = None,
    ) -> dict[str, Any]:
        replacement_readiness = recommendation.evidence_snapshot.get("replacement_readiness")
        return {
            "recommendation_id": recommendation.id,
            "artifact_id": recommendation.artifact_id,
            "skill_name": recommendation.skill_name,
            "skill_version": recommendation.skill_version,
            "scope": recommendation.scope,
            "surface": recommendation.surface,
            "recommendation_type": recommendation.recommendation_type,
            "recommended_action": recommendation.recommended_action,
            "recommendation_status": recommendation.status,
            "learner_goal_id": learner_goal_id,
            "source_proposal_id": recommendation.evidence_snapshot.get("source_proposal_id"),
            "source_artifact_id": recommendation.evidence_snapshot.get("source_anchor", {}).get("source_artifact_id"),
            "source_lineage_id": recommendation.evidence_snapshot.get("source_anchor", {}).get("source_lineage_id"),
            "rollout_id": recommendation.evidence_snapshot.get("rollout_evidence", {}).get("rollout_id"),
            "binding_id": recommendation.evidence_snapshot.get("rollout_evidence", {}).get("binding_id"),
            "usage_event_ids": list(
                recommendation.evidence_snapshot.get("usage_evidence", {}).get("successful_usage_event_ids") or []
            ),
            "recommendation_reason_code": recommendation.reason_code,
            "recommendation_reason_note": recommendation.reason_note,
            "decision_reason_code": decision_reason_code,
            "decision_reason_note": decision_reason_note,
            "source_job_id": source_job_id,
            "recommendation_source_job_id": recommendation.source_job_id,
            "autonomy_job_id": autonomy_job_id,
            "replacement_readiness": dict(replacement_readiness) if isinstance(replacement_readiness, dict) else None,
        }


class SkillReplacementAutoExecutionService:
    def __init__(
        self,
        *,
        recommendation_repository: SkillCuratorRecommendationRepository,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        recommendation_service: SkillCuratorRecommendationService,
        readiness_service: SkillReplacementReadinessService,
        audit_service: AuditService,
        db_session: AsyncSession | None = None,
        config: SkillReplacementAutoExecutionConfig | None = None,
    ) -> None:
        self._recommendation_repository = recommendation_repository
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._recommendation_service = recommendation_service
        self._readiness_service = readiness_service
        self._audit_service = audit_service
        self._db_session = db_session
        self._config = config or SkillReplacementAutoExecutionConfig()

    @property
    def default_scan_limit(self) -> int:
        return self._config.scan_limit

    async def run_once(
        self,
        *,
        limit: int | None = None,
        now: datetime | None = None,
    ) -> SkillReplacementAutoExecutionResult:
        if not self._config.enabled:
            return SkillReplacementAutoExecutionResult()

        bounded = bounded_limit(limit or self._config.scan_limit)
        current_time = now or datetime.now(timezone.utc)
        executed_count = 0
        skipped_count = 0
        recommendations = await self._recommendation_repository.list_pending_auto_execution_candidates(
            limit=bounded,
            surfaces=set(self._config.surfaces),
        )
        for recommendation in recommendations:
            accepted = await self.execute_recommendation(
                recommendation_id=recommendation.id,
                now=current_time,
            )
            if accepted is None:
                skipped_count += 1
            else:
                executed_count += 1
        return SkillReplacementAutoExecutionResult(
            executed_count=executed_count,
            skipped_count=skipped_count,
        )

    async def execute_recommendation(
        self,
        *,
        recommendation_id: str,
        now: datetime | None = None,
        autonomy_job_id: str | None = None,
        source_job_id: str | None = None,
    ) -> SkillCuratorRecommendation | None:
        current_time = now or datetime.now(timezone.utc)
        recommendation = await self._recommendation_repository.get_by_id(recommendation_id)
        if recommendation is None:
            await self._audit_skipped_not_found(
                recommendation_id=recommendation_id,
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None

        preflight = await self._preflight(
            recommendation=recommendation,
            now=current_time,
            autonomy_job_id=autonomy_job_id,
            source_job_id=source_job_id,
        )
        if preflight is None:
            return None
        artifact, learner_goal_id, readiness = preflight
        decision_reason_code = AUTO_EXECUTION_REASON_CODES[recommendation.recommended_action]

        try:
            async with self._execution_unit_of_work():
                accepted = await self._recommendation_service.accept_recommendation(
                    recommendation_id=recommendation.id,
                    operator_id=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
                    reason_code=decision_reason_code,
                    reason_note=(
                        "Automatic governed staged replacement execution."
                    ),
                )
                await self._audit_service.record(
                    event_type="skill.curator.recommendation.auto_execution.executed",
                    resource_type="skill_curator_recommendation",
                    resource_id=accepted.id,
                    actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
                    event_data=self._event_data(
                        recommendation=accepted,
                        artifact=artifact,
                        learner_goal_id=learner_goal_id,
                        readiness=readiness,
                        decision_reason_code=decision_reason_code,
                        decision_reason_note="Automatic governed staged replacement execution.",
                        source_job_id=source_job_id,
                        autonomy_job_id=autonomy_job_id,
                    ),
                )
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="skill.curator.recommendation.auto_execution.failed",
                resource_type="skill_curator_recommendation",
                resource_id=recommendation.id,
                actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
                event_data={
                    **self._event_data(
                        recommendation=recommendation,
                        artifact=artifact,
                        learner_goal_id=learner_goal_id,
                        readiness=readiness,
                        decision_reason_code="execution_failed",
                        decision_reason_note=str(exc),
                        source_job_id=source_job_id,
                        autonomy_job_id=autonomy_job_id,
                    ),
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            observe_skill_replacement_auto_execution(
                event="failed",
                action=recommendation.recommended_action,
                surface=recommendation.surface,
                reason_code=type(exc).__name__,
            )
            raise

        observe_skill_replacement_auto_execution(
            event="executed",
            action=recommendation.recommended_action,
            surface=recommendation.surface,
            reason_code=decision_reason_code,
        )
        return accepted

    async def _preflight(
        self,
        *,
        recommendation: SkillCuratorRecommendation,
        now: datetime,
        autonomy_job_id: str | None,
        source_job_id: str | None,
    ) -> tuple[SkillArtifact, str, SkillReplacementReadiness] | None:
        if recommendation.status != "pending":
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="recommendation_not_pending",
                reason_note="Only pending recommendations are auto-executed.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if recommendation.created_by != "skill_curator_job":
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="recommendation_not_curator_generated",
                reason_note="Only curator-generated recommendations are auto-executed.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if not _is_auto_executable_recommendation(recommendation):
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="unsupported_recommendation_action",
                reason_note="Recommendation is not eligible for automatic execution.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if not self._config.enabled:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="auto_execution_disabled",
                reason_note="Automatic staged replacement execution is disabled.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if recommendation.surface not in self._config.surfaces:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="surface_not_allowed",
                reason_note="Recommendation surface is not in the auto-execution allowlist.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if self._db_session is None or getattr(self._db_session, "begin_nested", None) is None:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="savepoint_unavailable",
                reason_note="Automatic staged replacement execution requires db_session savepoint protection.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None

        artifact = await self._load_artifact(recommendation)
        if artifact is None:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=None,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=None),
                readiness=None,
                reason_code="artifact_missing",
                reason_note="Recommendation artifact is missing.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if artifact.status != "staged":
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=artifact),
                readiness=None,
                reason_code="artifact_not_staged",
                reason_note="Automatic execution requires a staged artifact.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if artifact.name != recommendation.skill_name or artifact.scope != recommendation.scope:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=await self._learner_goal_id(recommendation, artifact=artifact),
                readiness=None,
                reason_code="artifact_recommendation_mismatch",
                reason_note="Recommendation no longer matches the staged artifact identity.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None

        learner_goal_id = await self._learner_goal_id(recommendation, artifact=artifact)
        if learner_goal_id is None:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=None,
                readiness=None,
                reason_code="learner_goal_missing",
                reason_note="Automatic execution requires learner_goal_id evidence.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        if await self._rate_limit_reached(learner_goal_id=learner_goal_id, now=now):
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=learner_goal_id,
                readiness=None,
                reason_code="auto_execution_24h_limit_reached",
                reason_note="Learner goal has reached the 24-hour auto-execution limit.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None

        readiness = await self._readiness_service.evaluate_artifact(artifact)
        if readiness.recommended_action != recommendation.recommended_action:
            await self._audit_skipped(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=learner_goal_id,
                readiness=readiness,
                reason_code=(
                    self._action_reason_code(readiness=readiness, action=recommendation.recommended_action)
                    or "ready_action_mismatch"
                ),
                reason_note="Live replacement readiness no longer matches the stored recommendation action.",
                autonomy_job_id=autonomy_job_id,
                source_job_id=source_job_id,
            )
            return None
        return artifact, learner_goal_id, readiness

    async def _load_artifact(self, recommendation: SkillCuratorRecommendation) -> SkillArtifact | None:
        if recommendation.artifact_id is None:
            return None
        return await self._artifact_repository.get_by_id(recommendation.artifact_id)

    async def _learner_goal_id(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        artifact: SkillArtifact | None,
    ) -> str | None:
        value = _optional_str(recommendation.evidence_snapshot.get("learner_goal_id"))
        if value is not None:
            return value
        proposal_id = _optional_str(recommendation.evidence_snapshot.get("source_proposal_id"))
        if proposal_id is None and artifact is not None:
            proposal_id = artifact.source_proposal_id
        if proposal_id is None:
            return None
        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            return None
        return proposal.learner_goal_id

    async def _rate_limit_reached(self, *, learner_goal_id: str, now: datetime) -> bool:
        count = await self._recommendation_repository.count_recent_system_auto_executed_for_goal(
            learner_goal_id=learner_goal_id,
            accepted_at_from=now - timedelta(hours=24),
        )
        return count >= self._config.rate_limit_24h

    async def _audit_skipped(
        self,
        *,
        recommendation: SkillCuratorRecommendation,
        artifact: SkillArtifact | None,
        learner_goal_id: str | None,
        readiness: SkillReplacementReadiness | None,
        reason_code: str,
        reason_note: str,
        autonomy_job_id: str | None,
        source_job_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type="skill.curator.recommendation.auto_execution.skipped",
            resource_type="skill_curator_recommendation",
            resource_id=recommendation.id,
            actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
            event_data=self._event_data(
                recommendation=recommendation,
                artifact=artifact,
                learner_goal_id=learner_goal_id,
                readiness=readiness,
                decision_reason_code=reason_code,
                decision_reason_note=reason_note,
                source_job_id=source_job_id,
                autonomy_job_id=autonomy_job_id,
            ),
        )
        observe_skill_replacement_auto_execution(
            event="skipped",
            action=recommendation.recommended_action,
            surface=recommendation.surface,
            reason_code=reason_code,
        )

    async def _audit_skipped_not_found(
        self,
        *,
        recommendation_id: str,
        autonomy_job_id: str | None,
        source_job_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type="skill.curator.recommendation.auto_execution.skipped",
            resource_type="skill_curator_recommendation",
            resource_id=recommendation_id,
            actor=SKILL_REPLACEMENT_AUTO_EXECUTION_ACTOR,
            event_data={
                "recommendation_id": recommendation_id,
                "decision_reason_code": "recommendation_not_found",
                "decision_reason_note": "Recommendation was not found during automatic execution.",
                "autonomy_job_id": autonomy_job_id,
                "source_job_id": source_job_id,
            },
        )
        observe_skill_replacement_auto_execution(
            event="skipped",
            action="unknown",
            surface="unknown",
            reason_code="recommendation_not_found",
        )

    def _event_data(
        self,
        *,
        recommendation: SkillCuratorRecommendation,
        artifact: SkillArtifact | None,
        learner_goal_id: str | None,
        readiness: SkillReplacementReadiness | None,
        decision_reason_code: str,
        decision_reason_note: str | None,
        source_job_id: str | None,
        autonomy_job_id: str | None,
    ) -> dict[str, Any]:
        source_proposal_id = recommendation.evidence_snapshot.get("source_proposal_id")
        if source_proposal_id is None and artifact is not None:
            source_proposal_id = artifact.source_proposal_id
        readiness_payload = _replacement_readiness_payload(readiness)
        usage_evidence = readiness.usage_evidence if readiness is not None else {}
        rollout_evidence = readiness.rollout_evidence if readiness is not None else {}
        source_anchor = readiness.source_anchor if readiness is not None else {}
        return {
            "recommendation_id": recommendation.id,
            "artifact_id": recommendation.artifact_id,
            "artifact_status": artifact.status if artifact is not None else None,
            "skill_name": recommendation.skill_name,
            "skill_version": recommendation.skill_version,
            "scope": recommendation.scope,
            "surface": recommendation.surface,
            "recommendation_type": recommendation.recommendation_type,
            "recommended_action": recommendation.recommended_action,
            "recommendation_status": recommendation.status,
            "learner_goal_id": learner_goal_id,
            "source_proposal_id": source_proposal_id,
            "source_artifact_id": source_anchor.get("source_artifact_id"),
            "source_lineage_id": source_anchor.get("source_lineage_id"),
            "current_selectable_artifact_id": source_anchor.get("current_selectable_artifact_id"),
            "rollout_id": rollout_evidence.get("rollout_id"),
            "binding_id": rollout_evidence.get("binding_id"),
            "observation_id": rollout_evidence.get("latest_observation_id"),
            "usage_event_ids": list(usage_evidence.get("successful_usage_event_ids") or usage_evidence.get("matched_usage_event_ids") or []),
            "recommendation_reason_code": recommendation.reason_code,
            "recommendation_reason_note": recommendation.reason_note,
            "decision_reason_code": decision_reason_code,
            "decision_reason_note": decision_reason_note,
            "source_job_id": source_job_id,
            "recommendation_source_job_id": recommendation.source_job_id,
            "autonomy_job_id": autonomy_job_id,
            "replacement_readiness": readiness_payload,
            "action_result": dict(recommendation.action_result),
        }

    def _action_reason_code(
        self,
        *,
        readiness: SkillReplacementReadiness,
        action: str,
    ) -> str | None:
        if action == "activate_staged":
            reason_codes = readiness.activate_readiness.reason_codes
        else:
            reason_codes = readiness.replace_readiness.reason_codes
        for reason_code in reason_codes:
            if isinstance(reason_code, str) and reason_code:
                return reason_code
        return None

    @asynccontextmanager
    async def _execution_unit_of_work(self) -> AsyncIterator[None]:
        if self._db_session is None:
            raise ValidationError("Automatic staged replacement execution requires db_session savepoint protection.")
        begin_nested = getattr(self._db_session, "begin_nested", None)
        if begin_nested is None:
            raise ValidationError("Automatic staged replacement execution requires begin_nested savepoint support.")
        async with begin_nested():
            yield


def _is_auto_executable_recommendation(recommendation: SkillCuratorRecommendation) -> bool:
    return (
        recommendation.recommendation_type in AUTO_EXECUTABLE_RECOMMENDATION_TYPES
        and recommendation.recommended_action in AUTO_EXECUTABLE_RECOMMENDED_ACTIONS
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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
