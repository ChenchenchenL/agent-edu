"""Constants, evidence weights, and default thresholds for Memory service.

Re-exported from ``agent_core.application.services.memory`` for backward
compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeEvidenceWeights:
    completed_assessment: float = 0.35
    completed_practice_or_review: float = 0.25
    completed_other_task: float = 0.15
    failed_assessment: float = 0.35
    failed_other_task: float = 0.25
    progress_event: float = 0.10
    struggle_event: float = 0.08
    neutral_event_refresh: float = 0.05
    strong_mastery: float = 0.10
    weak_mastery: float = 0.10
    task_attempt_assessment_link: float = 0.35
    task_attempt_default_link: float = 0.25
    completed_practice_or_review_link: float = 0.20


@dataclass(frozen=True)
class BehaviorEvidenceWeights:
    recurrence_per_session: float = 0.20
    max_recurrence_support: float = 0.60
    failed_or_skipped_task: float = 0.15
    completed_task_contradiction: float = 0.10
    failed_or_skipped_task_link: float = 0.20
    completed_task_link: float = 0.10
    struggle_event_link: float = 0.12
    neutral_event_link: float = 0.06


KNOWLEDGE_EVIDENCE_WEIGHTS = KnowledgeEvidenceWeights()
BEHAVIOR_EVIDENCE_WEIGHTS = BehaviorEvidenceWeights()


def default_governance_config() -> dict[str, float | int]:
    """Return the default governance threshold configuration."""
    return {
        "candidate_to_active_evidence_min": 2,
        "candidate_to_active_support_min": 0.35,
        "candidate_to_active_confidence_min": 0.55,
        "candidate_to_active_contradiction_max": 0.25,
        "active_to_stable_evidence_min": 4,
        "active_to_stable_stability_min": 0.75,
        "active_to_stable_assessment_min": 1,
        "stable_demote_contradiction_min": 0.35,
        "stable_demote_freshness_max": 0.35,
        "archive_freshness_max": 0.1,
        "archive_goal_relevance_max": 0.35,
        "behavior_candidate_recurrence_min": 1,
        "behavior_active_recurrence_min": 2,
        "behavior_active_to_stable_stability_min": 0.7,
        "reflection_effective_weight": 0.18,
        "reflection_ineffective_weight": 0.14,
        "compression_min_group_size": 2,
    }
