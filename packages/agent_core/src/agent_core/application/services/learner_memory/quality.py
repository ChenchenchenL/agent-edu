"""Pure quality / readiness logic for Memory governance.

All functions are deterministic and side-effect free.  They do not
access repositories, mutate state, or write audit events.
"""

from __future__ import annotations

from agent_core.application.services.memory_conflict_policy import CONFLICT_CONTRADICTION_THRESHOLD
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def knowledge_quality_score(memory: KnowledgeMemory) -> float:
    source_strength = 0.1
    if memory.source_event_ids:
        source_strength = 0.25
    if memory.task_evidence_count > 0:
        source_strength = max(source_strength, 0.55)
    if memory.assessment_evidence_count > 0:
        source_strength = max(source_strength, 0.8)
    recurrence = clamp_score(memory.evidence_count / 5)
    assessment_backing = clamp_score(memory.assessment_evidence_count / 2)
    return clamp_score(
        0.18 * source_strength
        + 0.18 * recurrence
        + 0.18 * assessment_backing
        + 0.14 * memory.support_score
        + 0.12 * memory.goal_relevance_score
        + 0.10 * memory.stability_score
        + 0.10 * memory.confidence_score
        - 0.18 * memory.contradiction_score
    )


def behavior_quality_score(memory: BehaviorMemory) -> float:
    source_strength = 0.1
    if memory.source_event_ids:
        source_strength = 0.25
    if memory.evidence_count > 0:
        source_strength = max(source_strength, 0.55)
    recurrence = clamp_score(max(memory.cross_session_recurrence_count, memory.evidence_count) / 4)
    task_backing = clamp_score(memory.evidence_count / 4)
    return clamp_score(
        0.22 * source_strength
        + 0.22 * recurrence
        + 0.18 * task_backing
        + 0.12 * memory.support_score
        + 0.12 * memory.goal_relevance_score
        + 0.08 * memory.stability_score
        + 0.08 * memory.confidence_score
        - 0.14 * memory.contradiction_score
    )


def quality_tier(quality_score: float) -> str:
    if quality_score >= 0.7:
        return "high"
    if quality_score >= 0.45:
        return "medium"
    return "low"


def knowledge_promotion_readiness(
    memory: KnowledgeMemory,
    quality_score: float,
    governance_config: dict[str, float | int],
) -> str:
    if (
        quality_score >= 0.62
        and memory.evidence_count >= int(governance_config["candidate_to_active_evidence_min"])
        and memory.support_score >= float(governance_config["candidate_to_active_support_min"])
        and memory.confidence_score >= float(governance_config["candidate_to_active_confidence_min"])
        and memory.contradiction_score < float(governance_config["candidate_to_active_contradiction_max"])
    ):
        return "ready"
    if quality_score >= 0.45:
        return "monitor"
    return "not_ready"


def behavior_promotion_readiness(
    memory: BehaviorMemory,
    quality_score: float,
    governance_config: dict[str, float | int],
) -> str:
    if (
        quality_score >= 0.58
        and memory.evidence_count >= int(governance_config["candidate_to_active_evidence_min"])
        and memory.cross_session_recurrence_count >= 2
        and memory.confidence_score >= 0.5
    ):
        return "ready"
    if quality_score >= 0.45:
        return "monitor"
    return "not_ready"


def quality_reasons(
    *,
    memory: KnowledgeMemory | BehaviorMemory,
    quality_score: float,
    readiness: str,
) -> list[str]:
    reasons: list[str] = []
    if isinstance(memory, KnowledgeMemory):
        if memory.assessment_evidence_count > 0:
            reasons.append("assessment_backed")
        elif memory.task_evidence_count > 0:
            reasons.append("task_backed")
        elif memory.source_event_ids:
            reasons.append("weak_session_only")
    else:
        if memory.cross_session_recurrence_count >= 2:
            reasons.append("cross_session_recurrence")
        elif memory.source_event_ids:
            reasons.append("weak_session_only")
    if memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        reasons.append("high_contradiction")
    if memory.freshness_score < 0.35:
        reasons.append("low_freshness")
    if memory.goal_relevance_score >= 0.7:
        reasons.append("goal_aligned")
    if readiness == "ready":
        reasons.append("promotion_ready")
    elif readiness == "monitor":
        reasons.append("monitor_candidate")
    if not reasons:
        reasons.append("balanced")
    if quality_score >= 0.7 and "high_quality" not in reasons:
        reasons.append("high_quality")
    return reasons


def memory_quality_snapshot_sync(
    memory: KnowledgeMemory | BehaviorMemory,
    *,
    governance_config: dict[str, float | int],
    evidence_mix: dict[str, float] | None = None,
) -> dict[str, object]:
    if isinstance(memory, KnowledgeMemory):
        q_score = knowledge_quality_score(memory)
        readiness = knowledge_promotion_readiness(memory, q_score, governance_config)
    else:
        q_score = behavior_quality_score(memory)
        readiness = behavior_promotion_readiness(memory, q_score, governance_config)
    q_tier = quality_tier(q_score)
    return {
        "quality_score": q_score,
        "quality_tier": q_tier,
        "promotion_readiness": readiness,
        "quality_reasons": quality_reasons(memory=memory, quality_score=q_score, readiness=readiness),
        "evidence_mix": evidence_mix or {},
    }


def governance_pressure(memory: KnowledgeMemory | BehaviorMemory) -> float:
    contradiction_pressure = memory.contradiction_score
    staleness_pressure = 1.0 - memory.freshness_score
    low_relevance_pressure = 1.0 - memory.goal_relevance_score
    low_stability_pressure = 1.0 - memory.stability_score
    return min(
        1.0,
        0.35 * contradiction_pressure
        + 0.35 * staleness_pressure
        + 0.2 * low_relevance_pressure
        + 0.15 * low_stability_pressure,
    )


def review_recommended(memory: KnowledgeMemory | BehaviorMemory) -> bool:
    return memory.status == "candidate" and (
        memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
        or memory.freshness_score < 0.35
        or memory.goal_relevance_score >= 0.7
    )
