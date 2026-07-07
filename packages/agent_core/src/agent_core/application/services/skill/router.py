"""Skill router service -- Phase 2 multi-candidate routing.

The router replaces the old first-match resolution with a structured
pipeline: collect candidates -> filter by eligibility -> rank by policy
-> pick winner or fall back to baseline.

Core objects:

* ``SkillRouterRequest`` -- input, built on top of ``CapabilityRequest``
* ``SkillRouterCandidate`` -- normalised candidate from any source
* ``SkillRouterDecision`` -- winner + full ranking + explain metadata
* ``SkillRouterService`` -- orchestrates collection, filtering, ranking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_core.application.services.skill.capability import CapabilityRequest


# ---------------------------------------------------------------------------
# Source types
# ---------------------------------------------------------------------------

CANDIDATE_SOURCE_TYPES = frozenset({
    "active_artifact",
    "staged_artifact",
    "tenant_external",
    "baseline_builtin",
})

# ---------------------------------------------------------------------------
# Trust levels (higher == more trusted)
# ---------------------------------------------------------------------------

TRUST_LEVELS: dict[str, int] = {
    "baseline_builtin": 25,
    "active_governed": 22,
    "stable_governed": 24,
    "staged_probe": 15,
    "staged_shadow": 12,
    "external_installed": 10,
}

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

ROUTING_CONFIDENCE_THRESHOLDS = {
    "minimum_confidence_to_promote_candidate": 0.45,
    "minimum_score_gap_over_baseline": 0.05,
    "maximum_failure_rate_before_forced_fallback": 0.50,
}


# ---------------------------------------------------------------------------
# Input / output contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillRouterRequest:
    """Input to the router, built on top of ``CapabilityRequest``."""

    capability_request: CapabilityRequest
    resource_id: str
    include_staged: bool = False
    topic_key: str | None = None
    learner_goal_id: str | None = None
    mastery_band: str | None = None
    confidence_thresholds: dict[str, float] = field(
        default_factory=lambda: dict(ROUTING_CONFIDENCE_THRESHOLDS),
    )


@dataclass(frozen=True)
class SkillRouterCandidate:
    """Normalised candidate from any source."""

    candidate_id: str
    source_type: str
    capability: str
    artifact_id: str | None
    skill_name: str
    surface: str
    implementation_binding: str
    artifact_status: str
    trust_level: int
    eligible: bool = True
    ineligible_reason_codes: list[str] = field(default_factory=list)
    topic_coverage: float = 0.0
    surface_compatibility: float = 1.0
    mastery_fit: float = 0.5
    recent_usage_score: float = 0.5
    failure_rate: float = 0.0
    rollback_pressure: float = 0.0
    binding_overlay: dict[str, Any] | None = None
    tool_plan: list[dict[str, Any]] = field(default_factory=list)
    sub_scores: dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0
    reason_codes: list[str] = field(default_factory=list)
    artifact_quality: float = 0.5
    compatibility_contract: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillRouterDecision:
    """Full routing decision with winner, ranking, and explain metadata."""

    winner: SkillRouterCandidate | None
    ranked_candidates: list[SkillRouterCandidate] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    confidence: float = 0.0
    selection_reason_codes: list[str] = field(default_factory=list)
    loser_reason_map: dict[str, list[str]] = field(default_factory=dict)
    blocked_candidate_ids: list[str] = field(default_factory=list)
    routing_mode: str = "deterministic_policy"
    baseline_used: bool = False


# ---------------------------------------------------------------------------
# Candidate source protocol
# ---------------------------------------------------------------------------


class SkillCandidateSource(Protocol):
    """Protocol for candidate collection sources."""

    @property
    def source_type(self) -> str: ...

    async def collect(
        self,
        request: SkillRouterRequest,
    ) -> list[SkillRouterCandidate]: ...


# ---------------------------------------------------------------------------
# Router service
# ---------------------------------------------------------------------------


class SkillRouterService:
    """Multi-candidate router with deterministic policy scoring.

    Pipeline:
    1. Collect candidates from all registered sources
    2. Filter by eligibility (deterministic governance rules)
    3. Rank by policy (deterministic sub-score aggregation)
    4. Pick winner or fall back to baseline
    """

    def __init__(
        self,
        *,
        sources: list[SkillCandidateSource],
        ranker: Any | None = None,
        confidence_thresholds: dict[str, float] | None = None,
    ) -> None:
        self._sources = sources
        self._ranker = ranker
        self._thresholds = {
            **ROUTING_CONFIDENCE_THRESHOLDS,
            **(confidence_thresholds or {}),
        }

    async def decide(self, request: SkillRouterRequest) -> SkillRouterDecision:
        candidates = await self._collect(request)
        eligible, blocked = self._filter_eligible(candidates, request)
        ranked = self._rank(eligible, request)
        winner, fallback_chain, baseline_used = self._pick_winner(ranked, request)
        loser_map = self._build_loser_map(ranked, winner)

        confidence = winner.total_score if winner is not None else 0.0
        selection_reasons: list[str] = []
        if winner is not None:
            selection_reasons = list(winner.reason_codes)
        if baseline_used:
            selection_reasons.append("baseline_fallback")
        if not eligible:
            selection_reasons.append("no_eligible_candidates")

        return SkillRouterDecision(
            winner=winner,
            ranked_candidates=ranked,
            fallback_chain=fallback_chain,
            confidence=confidence,
            selection_reason_codes=selection_reasons,
            loser_reason_map=loser_map,
            blocked_candidate_ids=[c.candidate_id for c in blocked],
            routing_mode="deterministic_policy",
            baseline_used=baseline_used,
        )

    async def _collect(self, request: SkillRouterRequest) -> list[SkillRouterCandidate]:
        all_candidates: list[SkillRouterCandidate] = []
        for source in self._sources:
            candidates = await source.collect(request)
            all_candidates.extend(candidates)
        return all_candidates

    @staticmethod
    def _filter_eligible(
        candidates: list[SkillRouterCandidate],
        request: SkillRouterRequest,
    ) -> tuple[list[SkillRouterCandidate], list[SkillRouterCandidate]]:
        eligible: list[SkillRouterCandidate] = []
        blocked: list[SkillRouterCandidate] = []
        for c in candidates:
            if not c.eligible:
                blocked.append(c)
                continue
            if c.source_type == "staged_artifact" and not request.include_staged:
                c_ineligible = SkillRouterCandidate(
                    **{**c.__dict__, "eligible": False, "ineligible_reason_codes": ["staged_not_included"]},
                )
                blocked.append(c_ineligible)
                continue
            eligible.append(c)
        return eligible, blocked

    def _rank(
        self,
        candidates: list[SkillRouterCandidate],
        request: SkillRouterRequest,
    ) -> list[SkillRouterCandidate]:
        if self._ranker is not None:
            ranked = self._ranker.rank(candidates, request)
            return [self._apply_quality_multiplier(c) for c in ranked]
        scored: list[SkillRouterCandidate] = []
        for c in candidates:
            sub_scores = _compute_sub_scores(c, request)
            total = sum(sub_scores.values()) / max(len(sub_scores), 1)
            total *= 0.7 + 0.3 * c.artifact_quality
            scored.append(SkillRouterCandidate(
                **{**c.__dict__, "sub_scores": sub_scores, "total_score": total},
            ))
        scored.sort(key=lambda c: c.total_score, reverse=True)
        return scored

    @staticmethod
    def _apply_quality_multiplier(c: SkillRouterCandidate) -> SkillRouterCandidate:
        adjusted = c.total_score * (0.7 + 0.3 * c.artifact_quality)
        return SkillRouterCandidate(
            **{**c.__dict__, "total_score": adjusted},
        )

    def _pick_winner(
        self,
        ranked: list[SkillRouterCandidate],
        request: SkillRouterRequest,
    ) -> tuple[SkillRouterCandidate | None, list[str], bool]:
        min_confidence = self._thresholds["minimum_confidence_to_promote_candidate"]
        max_failure = self._thresholds["maximum_failure_rate_before_forced_fallback"]
        min_gap = self._thresholds["minimum_score_gap_over_baseline"]

        baseline = next(
            (c for c in ranked if c.source_type == "baseline_builtin"),
            None,
        )

        non_baseline = [c for c in ranked if c.source_type != "baseline_builtin"]
        top = non_baseline[0] if non_baseline else None

        fallback_chain: list[str] = []
        baseline_used = False

        if top is None:
            fallback_chain.append("no_non_baseline_candidates")
            return baseline, fallback_chain, True

        if top.failure_rate > max_failure:
            fallback_chain.append("high_failure_rate")
            baseline_used = True
            return baseline, fallback_chain, baseline_used

        if top.total_score < min_confidence:
            fallback_chain.append("low_confidence")
            baseline_used = True
            return baseline, fallback_chain, baseline_used

        if baseline is not None and (top.total_score - baseline.total_score) < min_gap:
            fallback_chain.append("insufficient_gap_over_baseline")
            baseline_used = True
            return baseline, fallback_chain, baseline_used

        for c in ranked[1:]:
            fallback_chain.append(c.candidate_id)

        return top, fallback_chain, baseline_used

    @staticmethod
    def _build_loser_map(
        ranked: list[SkillRouterCandidate],
        winner: SkillRouterCandidate | None,
    ) -> dict[str, list[str]]:
        loser_map: dict[str, list[str]] = {}
        for c in ranked:
            if winner is not None and c.candidate_id == winner.candidate_id:
                continue
            reasons: list[str] = []
            if not c.eligible:
                reasons.extend(c.ineligible_reason_codes)
            if c.total_score < (winner.total_score if winner else 0):
                reasons.append("lower_total_score")
            if c.failure_rate > 0.3:
                reasons.append("high_failure_rate")
            if c.rollback_pressure > 0.5:
                reasons.append("high_rollback_pressure")
            loser_map[c.candidate_id] = reasons or ["ranked_lower"]
        return loser_map


def _compute_sub_scores(
    candidate: SkillRouterCandidate,
    request: SkillRouterRequest,
) -> dict[str, float]:
    return {
        "topic_coverage": candidate.topic_coverage,
        "surface_compatibility": candidate.surface_compatibility,
        "mastery_fit": candidate.mastery_fit,
        "recent_usage": candidate.recent_usage_score,
        "failure_penalty": 1.0 - candidate.failure_rate,
        "trust": candidate.trust_level / 25.0,
        "rollback_penalty": 1.0 - candidate.rollback_pressure,
    }
