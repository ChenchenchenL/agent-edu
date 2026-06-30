from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.skills import SkillReplacementStagingService
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalSandboxRun,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
    ReflectionProposalSandboxRunRepository,
    SkillArtifactRepository,
)
from agent_core.infrastructure.observability.metrics import observe_reflection_skill_evolution

SYSTEM_OPERATOR_ID = "system"
CURATOR_REASON_NOTE = "reflection_skill_evolution_curator"
TRUSTED_AUTO_STAGE_SOURCES = frozenset(
    {
        "skill_patch_request_realization",
        "skill_curator_merge_recommendation",
    }
)


@dataclass(frozen=True)
class ReflectionSkillEvolutionCuratorConfig:
    enabled: bool = True
    auto_staging_enabled: bool = False
    auto_stage_score_delta_min: float = 0.10
    auto_stage_24h_limit: int = 3


@dataclass(frozen=True)
class ReflectionSkillEvolutionCuratorResult:
    realized_count: int = 0
    sandbox_enqueued_count: int = 0
    staged_count: int = 0
    rejected_count: int = 0
    suspended_count: int = 0

    @property
    def processed_count(self) -> int:
        return (
            self.realized_count
            + self.sandbox_enqueued_count
            + self.staged_count
            + self.rejected_count
            + self.suspended_count
        )


class ReflectionSkillEvolutionCuratorService:
    def __init__(
        self,
        *,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        sandbox_run_repository: ReflectionProposalSandboxRunRepository,
        artifact_repository: SkillArtifactRepository,
        proposal_service: ReflectionProposalService,
        staging_service: SkillReplacementStagingService,
        audit_service: AuditService,
        db_session: AsyncSession | None = None,
        config: ReflectionSkillEvolutionCuratorConfig | None = None,
    ) -> None:
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._sandbox_run_repository = sandbox_run_repository
        self._artifact_repository = artifact_repository
        self._proposal_service = proposal_service
        self._staging_service = staging_service
        self._audit_service = audit_service
        self._db_session = db_session
        self._config = config or ReflectionSkillEvolutionCuratorConfig()

    async def run_once(
        self,
        *,
        limit: int = 20,
        now: datetime | None = None,
    ) -> ReflectionSkillEvolutionCuratorResult:
        """Run one bounded reflection skill evolution curation pass.

        Args:
            limit: Maximum proposals scanned in each phase.
            now: Optional clock override for deterministic tests.

        Returns:
            A count summary for the work completed in this pass.
        """
        if not self._config.enabled:
            return ReflectionSkillEvolutionCuratorResult()

        bounded = bounded_limit(limit)
        current_time = now or datetime.now(timezone.utc)
        realized_count = 0
        sandbox_enqueued_count = 0
        staged_count = 0
        rejected_count = 0
        suspended_count = 0

        patch_requests = await self._proposal_repository.list_pending_skill_patch_realizations(limit=bounded)
        for proposal in patch_requests:
            if await self._auto_realize_patch_request(proposal):
                realized_count += 1

        sandbox_candidates = await self._proposal_repository.list_pending_skill_package_sandbox(limit=bounded)
        for proposal in sandbox_candidates:
            outcome = await self._process_sandbox_candidate(proposal)
            if outcome == "enqueued":
                sandbox_enqueued_count += 1
            elif outcome == "rejected":
                rejected_count += 1
            elif outcome == "suspended":
                suspended_count += 1

        auto_stage_candidates = await self._proposal_repository.list_pending_skill_package_auto_stage(limit=bounded)
        for proposal in auto_stage_candidates:
            outcome = await self._process_auto_stage_candidate(proposal, now=current_time)
            if outcome == "staged":
                staged_count += 1
            elif outcome == "rejected":
                rejected_count += 1
            elif outcome == "suspended":
                suspended_count += 1

        return ReflectionSkillEvolutionCuratorResult(
            realized_count=realized_count,
            sandbox_enqueued_count=sandbox_enqueued_count,
            staged_count=staged_count,
            rejected_count=rejected_count,
            suspended_count=suspended_count,
        )

    async def _auto_realize_patch_request(self, proposal: ReflectionProposal) -> bool:
        try:
            derived = await self._proposal_service.realize_skill_patch_request(
                proposal_id=proposal.id,
                operator_id=SYSTEM_OPERATOR_ID,
                reason_code="auto_realized",
                reason_note=CURATOR_REASON_NOTE,
            )
        except (NotFoundError, ValidationError) as exc:
            await self._manual_review_required(
                proposal=proposal,
                phase="realization",
                reason_code="realization_validation_failed",
                reason_note=str(exc),
            )
            return False

        await self._audit_service.record(
            event_type="reflection.proposal.auto_realized",
            resource_type="reflection_proposal",
            resource_id=derived.id,
            actor=SYSTEM_OPERATOR_ID,
            event_data={
                **self._proposal_event_data(
                    proposal=derived,
                    evaluation=await self._evaluation_repository.get_by_proposal(derived.id),
                    sandbox_run=None,
                    reason_code="auto_realized",
                ),
                "source_skill_patch_request_id": proposal.id,
                "derived_proposal_id": derived.id,
            },
        )
        observe_reflection_skill_evolution(event="auto_realized", reason_code="auto_realized")
        return True

    async def _process_sandbox_candidate(self, proposal: ReflectionProposal) -> str | None:
        if proposal.risk_level == "high":
            await self._manual_review_required(
                proposal=proposal,
                phase="sandbox_enqueue",
                reason_code="risk_level_high",
                reason_note="high-risk proposals require manual sandbox review",
            )
            return "suspended"

        sandbox_run = await self._load_sandbox_run(proposal=proposal, evaluation=None)
        if sandbox_run is not None and sandbox_run.status in {"failed", "cancelled"}:
            await self._auto_reject(
                proposal=proposal,
                evaluation=None,
                sandbox_run=sandbox_run,
                reason_code="sandbox_failed",
                reason_note=sandbox_run.error_code,
            )
            return "rejected"

        updated = await self._proposal_service.auto_enqueue_sandbox(proposal_id=proposal.id)
        if updated.status == "sandbox_queued":
            return "enqueued"
        await self._manual_review_required(
            proposal=updated,
            phase="sandbox_enqueue",
            reason_code="sandbox_enqueue_not_queued",
            reason_note=f"auto_enqueue_sandbox returned status '{updated.status}'",
        )
        return "suspended"

    async def _process_auto_stage_candidate(self, proposal: ReflectionProposal, *, now: datetime) -> str | None:
        if proposal.risk_level == "high":
            await self._manual_review_required(
                proposal=proposal,
                phase="auto_stage",
                reason_code="risk_level_high",
                reason_note="high-risk proposals require manual approval and staging review",
            )
            return "suspended"

        evaluation, sandbox_run = await self._load_proposal_context(proposal=proposal)

        if proposal.status == "approved" and proposal.approved_by is None:
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="approved_by_missing",
                reason_note="approved proposals require an explicit approver before auto-staging",
            )
            return "suspended"

        if proposal.status == "approved" and proposal.approved_by != SYSTEM_OPERATOR_ID:
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="approved_by_non_system",
                reason_note="operator-approved proposals are not auto-staged",
            )
            return "suspended"

        if not self._trusted_auto_stage_source(proposal):
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="non_replacement_source",
                reason_note="only governed replacement sources may be auto-staged",
            )
            return "suspended"

        existing_artifact = await self._artifact_repository.get_by_source_proposal_id(proposal.id)
        if existing_artifact is not None and existing_artifact.status != "candidate":
            return None

        validation_outcome = await self._validate_auto_stage_candidate(
            proposal=proposal,
            evaluation=evaluation,
            sandbox_run=sandbox_run,
        )
        if validation_outcome is not None:
            return validation_outcome

        if not self._config.auto_staging_enabled:
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="auto_staging_disabled",
                reason_note="automatic replacement staging is disabled",
            )
            return "suspended"

        if self._db_session is None or getattr(self._db_session, "begin_nested", None) is None:
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="savepoint_unavailable",
                reason_note="automatic staging requires db_session savepoint protection",
            )
            return "suspended"

        if await self._rate_limit_reached(learner_goal_id=proposal.learner_goal_id, now=now):
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="auto_stage_24h_limit_reached",
                reason_note="learner goal has reached the 24-hour auto-staging limit",
            )
            return "suspended"

        async with self._stage_unit_of_work():
            approved = proposal
            if proposal.status == "sandbox_completed":
                approved = await self._proposal_service.approve(
                    proposal_id=proposal.id,
                    operator_id=SYSTEM_OPERATOR_ID,
                    reason_code="auto_stage_approved",
                    reason_note=CURATOR_REASON_NOTE,
                )
            staged = await self._staging_service.stage_replacement_from_proposal(
                proposal_id=approved.id,
                operator_id=SYSTEM_OPERATOR_ID,
                reason_code="auto_staged",
                reason_note=CURATOR_REASON_NOTE,
            )
            await self._audit_service.record(
                event_type="skill.artifact.auto_staged",
                resource_type="skill_artifact",
                resource_id=staged.id,
                actor=SYSTEM_OPERATOR_ID,
                event_data={
                    **self._proposal_event_data(
                        proposal=approved,
                        evaluation=evaluation,
                        sandbox_run=sandbox_run,
                        reason_code="auto_staged",
                    ),
                    "artifact_id": staged.id,
                    "artifact_status": staged.status,
                    "lineage_id": staged.lineage_id,
                    "parent_artifact_id": staged.parent_artifact_id,
                    "supersedes_artifact_id": staged.supersedes_artifact_id,
                },
            )
        observe_reflection_skill_evolution(event="auto_staged", reason_code="auto_staged")
        return "staged"

    async def _auto_reject(
        self,
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
        sandbox_run: ReflectionProposalSandboxRun | None,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        rejected = await self._proposal_service.reject(
            proposal_id=proposal.id,
            operator_id=SYSTEM_OPERATOR_ID,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        await self._audit_service.record(
            event_type="reflection.proposal.auto_rejected",
            resource_type="reflection_proposal",
            resource_id=rejected.id,
            actor=SYSTEM_OPERATOR_ID,
            event_data=self._proposal_event_data(
                proposal=rejected,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code=reason_code,
                reason_note=reason_note,
            ),
        )
        observe_reflection_skill_evolution(event="auto_rejected", reason_code=reason_code)
        return rejected

    async def _auto_stage_suspended(
        self,
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
        sandbox_run: ReflectionProposalSandboxRun | None,
        reason_code: str,
        reason_note: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type="reflection.proposal.auto_staging_suspended",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=SYSTEM_OPERATOR_ID,
            event_data=self._proposal_event_data(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code=reason_code,
                reason_note=reason_note,
            ),
        )
        observe_reflection_skill_evolution(event="auto_staging_suspended", reason_code=reason_code)

    async def _manual_review_required(
        self,
        *,
        proposal: ReflectionProposal,
        phase: str,
        reason_code: str,
        reason_note: str | None,
    ) -> None:
        evaluation, sandbox_run = await self._load_proposal_context(proposal=proposal)
        await self._audit_service.record(
            event_type="reflection.proposal.manual_review_required",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=SYSTEM_OPERATOR_ID,
            event_data={
                **self._proposal_event_data(
                    proposal=proposal,
                    evaluation=evaluation,
                    sandbox_run=sandbox_run,
                    reason_code=reason_code,
                    reason_note=reason_note,
                ),
                "phase": phase,
            },
        )
        observe_reflection_skill_evolution(event="manual_review_required", reason_code=reason_code)

    async def _rate_limit_reached(self, *, learner_goal_id: str, now: datetime) -> bool:
        staged_count = await self._artifact_repository.count_recent_system_staged_replacements_for_goal(
            learner_goal_id=learner_goal_id,
            created_at_from=now - timedelta(hours=24),
        )
        return staged_count >= self._config.auto_stage_24h_limit

    async def _load_sandbox_run(
        self,
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
    ) -> ReflectionProposalSandboxRun | None:
        sandbox_run_id = proposal.latest_sandbox_run_id or (evaluation.sandbox_run_id if evaluation is not None else None)
        if sandbox_run_id is None:
            return None
        return await self._sandbox_run_repository.get_by_id(sandbox_run_id)

    async def _load_proposal_context(
        self,
        *,
        proposal: ReflectionProposal,
    ) -> tuple[ReflectionProposalEvaluation | None, ReflectionProposalSandboxRun | None]:
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        sandbox_run = await self._load_sandbox_run(proposal=proposal, evaluation=evaluation)
        return evaluation, sandbox_run

    async def _validate_auto_stage_candidate(
        self,
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
        sandbox_run: ReflectionProposalSandboxRun | None,
    ) -> str | None:
        if sandbox_run is None:
            await self._auto_reject(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=None,
                reason_code="missing_sandbox_run",
                reason_note=f"{proposal.status} proposal is missing sandbox run evidence",
            )
            return "rejected"
        if sandbox_run.status in {"failed", "cancelled"}:
            await self._auto_reject(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="sandbox_failed",
                reason_note=sandbox_run.error_code,
            )
            return "rejected"
        if evaluation is None:
            await self._auto_reject(
                proposal=proposal,
                evaluation=None,
                sandbox_run=sandbox_run,
                reason_code="missing_evaluation",
                reason_note=f"{proposal.status} proposal is missing evaluation evidence",
            )
            return "rejected"
        if evaluation.evaluation_status == "ineffective":
            await self._auto_reject(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="evaluation_ineffective",
                reason_note="effective auto-staging requires an effective sandbox evaluation",
            )
            return "rejected"
        if evaluation.evaluation_status == "inconclusive":
            await self._auto_reject(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="evaluation_inconclusive",
                reason_note="inconclusive sandbox evaluations are not auto-promoted",
            )
            return "rejected"
        if evaluation.score_delta < 0:
            await self._auto_reject(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="negative_score_delta",
                reason_note="negative sandbox score deltas are auto-rejected",
            )
            return "rejected"
        if evaluation.score_delta < self._config.auto_stage_score_delta_min:
            await self._auto_stage_suspended(
                proposal=proposal,
                evaluation=evaluation,
                sandbox_run=sandbox_run,
                reason_code="score_delta_below_threshold",
                reason_note="sandbox score delta is below the auto-staging threshold",
            )
            return "suspended"
        return None

    @asynccontextmanager
    async def _stage_unit_of_work(self) -> AsyncIterator[None]:
        if self._db_session is None:
            raise ValidationError("Reflection skill auto-staging requires db_session savepoint protection.")
        begin_nested = getattr(self._db_session, "begin_nested", None)
        if begin_nested is None:
            raise ValidationError("Reflection skill auto-staging requires begin_nested savepoint support.")
        async with begin_nested():
            yield

    @staticmethod
    def _trusted_auto_stage_source(proposal: ReflectionProposal) -> bool:
        source = proposal.evidence_snapshot.get("source")
        return isinstance(source, str) and source in TRUSTED_AUTO_STAGE_SOURCES

    @staticmethod
    def _proposal_event_data(
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
        sandbox_run: ReflectionProposalSandboxRun | None,
        reason_code: str,
        reason_note: str | None = None,
    ) -> dict[str, object]:
        return {
            "proposal_id": proposal.id,
            "proposal_status": proposal.status,
            "proposal_type": proposal.proposal_type,
            "learner_goal_id": proposal.learner_goal_id,
            "source_proposal_id": proposal.evidence_snapshot.get("source_skill_patch_request_id"),
            "proposal_source": proposal.evidence_snapshot.get("source"),
            "evaluation_id": evaluation.id if evaluation is not None else None,
            "evaluation_status": evaluation.evaluation_status if evaluation is not None else None,
            "sandbox_run_id": (
                sandbox_run.id if sandbox_run is not None else (evaluation.sandbox_run_id if evaluation is not None else None)
            ),
            "sandbox_run_status": sandbox_run.status if sandbox_run is not None else None,
            "score_delta": evaluation.score_delta if evaluation is not None else None,
            "reason_code": reason_code,
            "reason_note": reason_note,
            "source_artifact_id": proposal.evidence_snapshot.get("source_artifact_id"),
            "lineage_id": proposal.evidence_snapshot.get("source_artifact_lineage_id"),
            "recommendation_id": proposal.evidence_snapshot.get("recommendation_id"),
        }
