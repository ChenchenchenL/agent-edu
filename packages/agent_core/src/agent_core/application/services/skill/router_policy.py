"""Deterministic routing policy for skill candidate ranking.

The ranker computes sub-scores for each candidate and aggregates them
into a total score.  No LLM involvement -- all signals are deterministic
and explainable.

Sub-scores:
- topic_coverage: how well the candidate covers the requested topic
- surface_compatibility: whether the candidate supports the surface
- mastery_fit: how well the candidate matches the learner's mastery band
- recent_usage: recent outcome quality from persisted usage events
- failure_penalty: inverse of failure rate
- trust: normalised trust level from governance state
- rollback_penalty: inverse of rollback pressure from rollout observations
"""

from __future__ import annotations

from agent_core.application.services.skill.router import (
    SkillRouterCandidate,
    SkillRouterRequest,
)

SUB_SCORE_WEIGHTS: dict[str, float] = {
    "topic_coverage": 1.0,
    "surface_compatibility": 1.5,
    "mastery_fit": 0.8,
    "recent_usage": 1.8,
    "failure_penalty": 2.0,
    "trust": 0.2,
    "rollback_penalty": 1.0,
}


class SkillCandidateRanker:
    """Deterministic policy ranker with explicit sub-scores."""

    def __init__(
        self,
        *,
        weights: dict[str, float] | None = None,
    ) -> None:
        self._weights = weights or dict(SUB_SCORE_WEIGHTS)

    def rank(
        self,
        candidates: list[SkillRouterCandidate],
        request: SkillRouterRequest,
    ) -> list[SkillRouterCandidate]:
        scored: list[SkillRouterCandidate] = []
        for c in candidates:
            sub_scores = self._compute_sub_scores(c, request)
            total = self._aggregate(sub_scores)
            scored.append(SkillRouterCandidate(
                **{**c.__dict__, "sub_scores": sub_scores, "total_score": total},
            ))
        scored.sort(key=lambda c: c.total_score, reverse=True)
        return scored

    def _compute_sub_scores(
        self,
        candidate: SkillRouterCandidate,
        request: SkillRouterRequest,
    ) -> dict[str, float]:
        mastery_fit = candidate.mastery_fit
        if request.mastery_band is not None:
            mastery_fit = _mastery_band_fit(request.mastery_band, candidate)

        return {
            "topic_coverage": candidate.topic_coverage,
            "surface_compatibility": candidate.surface_compatibility,
            "mastery_fit": mastery_fit,
            "recent_usage": candidate.recent_usage_score,
            "failure_penalty": 1.0 - candidate.failure_rate,
            "trust": candidate.trust_level / 25.0,
            "rollback_penalty": 1.0 - candidate.rollback_pressure,
        }

    def _aggregate(self, sub_scores: dict[str, float]) -> float:
        weighted_sum = 0.0
        total_weight = 0.0
        for key, value in sub_scores.items():
            weight = self._weights.get(key, 1.0)
            weighted_sum += value * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight > 0 else 0.0


def _mastery_band_fit(band: str, candidate: SkillRouterCandidate) -> float:
    """Compute mastery fit score for a candidate given the learner's mastery band.

    The "standard" band is used as a fallback when mastery data is missing.
    It bypasses band-specific filtering and returns the candidate's default
    mastery_fit score, allowing all candidates to compete on equal footing.
    """
    contract = candidate.compatibility_contract or {}
    match_rules = contract.get("match_rules") or contract

    supported = match_rules.get("supported_mastery_bands")
    excluded = match_rules.get("excluded_mastery_bands")
    remediation = match_rules.get("remediation")

    if excluded and isinstance(excluded, list) and band in excluded:
        return 0.0

    if supported and isinstance(supported, list) and band not in supported:
        return 0.0

    if remediation is True:
        if band == "confident":
            return 0.0
        elif band in ("novice", "developing"):
            return 1.0

    # "standard" band: no band-specific filtering, use candidate's default mastery_fit
    if band == "standard":
        return candidate.mastery_fit

    band_ranges = {
        "novice": (0.0, 0.35),
        "developing": (0.3, 0.65),
        "confident": (0.6, 1.0),
    }
    range_ = band_ranges.get(band)
    if range_ is None:
        return candidate.mastery_fit
    low, high = range_
    midpoint = (low + high) / 2.0
    candidate_mid = 0.5
    distance = abs(midpoint - candidate_mid)
    return max(0.0, 1.0 - distance * 2.0)
