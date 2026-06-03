from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.domain.entities.reflection_closure import ReflectionProposalRollout
from agent_core.infrastructure.db.repositories import ReflectionProposalRolloutRepository


@dataclass(frozen=True)
class ActiveProposalOverlay:
    rollout_id: str
    proposal_id: str
    learner_goal_id: str
    surface: str
    status: str
    payload: dict[str, Any]
    baseline_snapshot: dict[str, Any]


class ReflectionProposalRolloutResolver:
    def __init__(
        self,
        *,
        rollout_repository: ReflectionProposalRolloutRepository,
    ) -> None:
        self._rollout_repository = rollout_repository

    async def get_active_overlay(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        include_staged: bool = False,
    ) -> ActiveProposalOverlay | None:
        rollout = await self._rollout_repository.get_active_by_goal_and_surface(
            learner_goal_id,
            surface,
            include_staged=include_staged,
        )
        if rollout is None:
            return None
        return self._to_overlay(rollout)

    @staticmethod
    def _to_overlay(rollout: ReflectionProposalRollout) -> ActiveProposalOverlay:
        return ActiveProposalOverlay(
            rollout_id=rollout.id,
            proposal_id=rollout.proposal_id,
            learner_goal_id=rollout.learner_goal_id,
            surface=rollout.surface,
            status=rollout.status,
            payload=dict(rollout.runtime_overlay_payload),
            baseline_snapshot=dict(rollout.baseline_snapshot),
        )
