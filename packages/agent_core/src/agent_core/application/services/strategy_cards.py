from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import LearnerGoalStrategyCard
from agent_core.infrastructure.db.repositories import LearnerGoalStrategyCardRepository


class StrategyCardService:
    def __init__(
        self,
        *,
        repository: LearnerGoalStrategyCardRepository,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._audit_service = audit_service

    async def get_active(self, learner_goal_id: str) -> LearnerGoalStrategyCard | None:
        return await self._repository.get_active_by_goal(learner_goal_id)

    async def refresh_from_reflections(self, *, learner_goal_id: str, reflections: list[ReflectionRecord]) -> LearnerGoalStrategyCard | None:
        if not reflections:
            return await self._repository.get_active_by_goal(learner_goal_id)
        current = await self._repository.get_active_by_goal(learner_goal_id)
        version = 1 if current is None else current.version + 1
        strategy_implications = [dict((item.evidence_payload or {}).get("verdict", {}).get("strategy_implications") or {}) for item in reflections]
        instruction_mode = self._pick_bias(
            strategy_implications,
            key="primary_instruction_mode",
            fallback="guided" if any(item.primary_root_cause in {"knowledge_gap", "review_gap"} for item in reflections) else "mixed",
        )
        difficulty_bias = self._pick_bias(
            strategy_implications,
            key="difficulty_bias",
            fallback="supportive" if any(item.primary_root_cause == "difficulty_mismatch" for item in reflections) else "balanced",
        )
        review_bias = self._pick_bias(
            strategy_implications,
            key="review_bias",
            fallback="intensive" if any(item.primary_root_cause == "review_gap" for item in reflections) else "normal",
        )
        replan_bias = self._pick_bias(
            strategy_implications,
            key="replan_bias",
            fallback="aggressive" if any(item.primary_root_cause in {"sequencing_issue", "assessment_regression"} for item in reflections) else "normal",
        )
        assessment_bias = self._pick_bias(
            strategy_implications,
            key="assessment_bias",
            fallback="early" if any(item.primary_root_cause == "assessment_regression" for item in reflections) else "standard",
        )
        card = LearnerGoalStrategyCard.build(
            learner_goal_id=learner_goal_id,
            version=version,
            source_reflection_ids=[item.id for item in reflections[:5]],
            primary_instruction_mode=instruction_mode,
            difficulty_bias=difficulty_bias,
            review_bias=review_bias,
            replan_bias=replan_bias,
            assessment_bias=assessment_bias,
            intervention_policy={"source": "reflection_v2"},
            rationale="Derived from recent effective/resolved reflections.",
            confidence_score=min(0.9, 0.45 + 0.08 * len(reflections)),
        )
        if current is not None:
            await self._repository.update(current.with_status("superseded"))
        await self._repository.create(card)
        await self._audit_service.record(
            event_type="strategy.card.refreshed",
            resource_type="learner_goal_strategy_card",
            resource_id=card.id,
            actor="system",
            event_data={"learner_goal_id": learner_goal_id, "version": card.version},
        )
        return card

    async def refresh_from_evaluations(
        self,
        *,
        learner_goal_id: str,
        reflections: list[ReflectionRecord],
        effective: bool,
    ) -> LearnerGoalStrategyCard | None:
        if not effective:
            return await self._repository.get_active_by_goal(learner_goal_id)
        return await self.refresh_from_reflections(learner_goal_id=learner_goal_id, reflections=reflections)

    @staticmethod
    def _pick_bias(
        implications: list[dict[str, str]],
        *,
        key: str,
        fallback: str,
    ) -> str:
        for item in implications:
            value = item.get(key)
            if value:
                return value
        return fallback

    @staticmethod
    def build_strategy_summary(card: LearnerGoalStrategyCard | None) -> dict[str, object] | None:
        if card is None:
            return None
        return {
            "primary_instruction_mode": card.primary_instruction_mode,
            "difficulty_bias": card.difficulty_bias,
            "review_bias": card.review_bias,
            "replan_bias": card.replan_bias,
            "assessment_bias": card.assessment_bias,
            "rationale": card.rationale,
            "confidence_score": card.confidence_score,
        }
