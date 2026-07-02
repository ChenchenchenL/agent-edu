"""Result dataclasses for the Memory service layer.

These types are consumed by planners, reflection, workspace, API routes,
and maintenance workers.  They are re-exported from
``agent_core.application.services.memory`` for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
)


@dataclass(frozen=True)
class LongTermMemoryWriteResult:
    knowledge_memories: list[KnowledgeMemory]
    behavior_memories: list[BehaviorMemory]


@dataclass(frozen=True)
class LongTermMemoryUpsertResult:
    memory: KnowledgeMemory | BehaviorMemory
    action: str


@dataclass(frozen=True)
class MemoryMaintenanceResult:
    compressed_knowledge_groups: int
    compressed_behavior_groups: int
    promoted_knowledge: int = 0
    promoted_behavior: int = 0
    demoted_knowledge: int = 0
    demoted_behavior: int = 0


@dataclass(frozen=True)
class MemoryMaintenanceBatchResult:
    processed_count: int
    changed_count: int
    next_cursor: str | None
    completed: bool
    metadata: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryConflictMemberDetail:
    id: str
    conflict_set_id: str
    memory_type: str
    memory_id: str
    memory_key: str
    stance: str
    support_score: float
    contradiction_score: float
    member_title: str | None
    member_summary: str | None
    member_status: str | None
    member_validation_status: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReflectionCorpusMemoryItem:
    memory_type: str
    memory_id: str
    learner_profile_id: str
    learner_goal_id: str | None
    memory_key: str
    memory_level: str
    title: str
    summary: str
    status: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    support_score: float
    contradiction_score: float
    evidence_count: int
    contradiction_count: int
    reflection_priority_score: float
    recommended_action: str
    rationale: str
    recommended_action_reason: str
    topic_alignment_score: float
    governance_pressure: float
    review_recommended: bool
    quality_score: float
    quality_tier: str
    promotion_readiness: str
    quality_reasons: list[str]
    evidence_mix: dict[str, float]
    semantic_category: str
    validation_status: str
    provenance_type: str
    provenance_source_id: str | None
    scope_ref: dict[str, str | None]
    promotion_rationale: str | None
    contested: bool
    source_event_ids: list[str]
    source_memory_ids: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ReflectionCorpusSummary:
    total_items: int
    knowledge_items: int
    behavior_items: int
    candidate_items: int
    stable_items: int
    contradiction_focus_items: int
    stale_focus_items: int
    validate_items: int
    reinforce_items: int


@dataclass(frozen=True)
class ReflectionCorpusResult:
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    items: list[ReflectionCorpusMemoryItem]
    summary: ReflectionCorpusSummary


@dataclass(frozen=True)
class BrowseMemoriesResult:
    total: int
    limit: int
    offset: int
    items: list[KnowledgeMemory] | list[BehaviorMemory]


@dataclass(frozen=True)
class MemoryGovernanceSummary:
    learner_profile_id: str
    learner_goal_id: str | None
    knowledge_total: int
    behavior_total: int
    candidate_total: int
    active_total: int
    stable_total: int
    archived_total: int
    suppressed_total: int
    contradiction_focus_total: int
    stale_candidate_total: int
    high_priority_total: int
    recent_promotions: int
    recent_demotions: int
    recent_archives: int
    recent_compressions: int
    promotion_candidate_total: int
    demotion_risk_total: int
    operator_review_recommended_total: int
    reflection_bridge_total: int
    high_quality_total: int
    medium_quality_total: int
    ready_promotion_total: int
    weak_candidate_total: int
    quality_tier_totals: dict[str, int]
    topic_bucket_summary: list[dict[str, object]]


@dataclass(frozen=True)
class MemoryInterpretationFact:
    memory_type: str
    memory_id: str
    memory_key: str
    semantic_category: str
    validation_status: str
    title: str
    summary: str
    confidence_score: float
    importance_score: float
    recommended_use: str


@dataclass(frozen=True)
class MemoryInterpretationResult:
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    facts: list[MemoryInterpretationFact]
    behavior_patterns: list[MemoryInterpretationFact]
    contested_items: list[MemoryInterpretationFact]
    recommended_constraints: list[str]
    conflict_count: int
