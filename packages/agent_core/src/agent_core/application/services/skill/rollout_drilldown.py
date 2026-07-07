from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from typing import Any

from agent_core.infrastructure.db.repositories.reflection import (
    ReflectionProposalRepository,
    ReflectionProposalRolloutDecisionRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
)
from agent_core.infrastructure.db.repositories.skill import SkillUsageEventRepository


@dataclass(frozen=True)
class RolloutDrillDownSummary:
    rollout_id: str
    proposal_summary: dict[str, Any]
    observation_timeline: list[dict[str, Any]]
    decision_timeline: list[dict[str, Any]]
    usage_attribution: dict[str, Any]
    signal_trend: dict[str, Any]
    current_status: str
    duration_days: float


class RolloutDrillDownService:
    def __init__(
        self,
        *,
        rollout_repository: ReflectionProposalRolloutRepository,
        observation_repository: ReflectionProposalRolloutObservationRepository,
        decision_repository: ReflectionProposalRolloutDecisionRepository,
        proposal_repository: ReflectionProposalRepository,
        usage_repository: SkillUsageEventRepository,
    ) -> None:
        self._rollout_repository = rollout_repository
        self._observation_repository = observation_repository
        self._decision_repository = decision_repository
        self._proposal_repository = proposal_repository
        self._usage_repository = usage_repository

    async def build_summary(self, rollout_id: str) -> RolloutDrillDownSummary:
        from agent_core.domain.errors import NotFoundError
        rollout = await self._rollout_repository.get_by_id(rollout_id)
        if rollout is None:
            raise NotFoundError(f"Rollout not found: {rollout_id}")

        proposal = await self._proposal_repository.get_by_id(rollout.proposal_id)
        proposal_summary: dict[str, Any] = {}
        if proposal is not None:
            proposal_summary = {
                "id": proposal.id,
                "proposal_type": proposal.proposal_type,
                "status": proposal.status,
                "hypothesis": proposal.hypothesis,
                "evaluation_status": proposal.evaluation_status,
                "risk_level": proposal.risk_level,
                "target_scope": proposal.target_scope,
            }

        observations = await self._observation_repository.list_by_rollout(rollout_id)
        observation_timeline = [
            {
                "id": o.id,
                "recommendation": o.recommendation,
                "positive_score": o.positive_score,
                "negative_score": o.negative_score,
                "observed_sample_count": o.observed_sample_count,
                "signal_summary": dict(o.signal_summary or {}),
                "reason_codes": list(o.reason_codes or []),
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in sorted(observations, key=lambda o: o.created_at)
        ]

        decisions = await self._decision_repository.list_by_rollout(rollout_id)
        decision_timeline = [
            {
                "id": d.id,
                "decision_type": d.decision_type,
                "previous_status": d.previous_status,
                "new_status": d.new_status,
                "reason_code": d.reason_code,
                "operator_id": d.operator_id,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in sorted(decisions, key=lambda d: d.created_at)
        ]

        all_usage = await self._usage_repository.list_events(limit=200)
        attributed = [
            e for e in all_usage
            if (e.metadata or {}).get("skill_package_rollout", {}).get("rollout_id") == rollout_id
        ]
        total_attr = len(attributed)
        positive_attr = sum(1 for e in attributed if e.outcome_status in ("completed", "partial_success"))
        negative_attr = sum(1 for e in attributed if e.outcome_status in ("failed", "aborted"))
        usage_attribution = {
            "total_events": total_attr,
            "positive_count": positive_attr,
            "negative_count": negative_attr,
        }

        signal_trend = {
            "positive_scores": [o["positive_score"] for o in observation_timeline],
            "negative_scores": [o["negative_score"] for o in observation_timeline],
            "observation_count": len(observation_timeline),
        }

        duration_days = 0.0
        if rollout.activated_at:
            end = rollout.rolled_back_at or rollout.promoted_at
            if end:
                duration_days = (end - rollout.activated_at).total_seconds() / 86400

        return RolloutDrillDownSummary(
            rollout_id=rollout_id,
            proposal_summary=proposal_summary,
            observation_timeline=observation_timeline,
            decision_timeline=decision_timeline,
            usage_attribution=usage_attribution,
            signal_trend=signal_trend,
            current_status=rollout.status,
            duration_days=round(duration_days, 2),
        )
