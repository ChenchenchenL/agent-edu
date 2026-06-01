from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MemoryQualityResponseMixin(BaseModel):
    quality_score: float
    quality_tier: str
    promotion_readiness: str
    quality_reasons: list[str]
    evidence_mix: dict[str, float]


class KnowledgeMemoryResponse(MemoryQualityResponseMixin):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    knowledge_key: str
    title: str
    summary: str
    details: str | None
    knowledge_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    scope_type: str
    stability_score: float
    goal_relevance_score: float
    support_score: float
    contradiction_score: float
    evidence_count: int
    contradiction_count: int
    last_supported_at: datetime | None
    last_contradicted_at: datetime | None
    promotion_state_changed_at: datetime
    suppressed_reason_code: str | None
    suppressed_reason_note: str | None
    suppressed_by: str | None
    suppressed_at: datetime | None
    prerequisite_keys: list[str]
    source_event_ids: list[str]
    source_memory_ids: list[str]
    tags: list[str]
    status: str
    compressed_into_id: str | None
    last_reviewed_at: datetime | None
    prerequisite_weight: float
    assessment_evidence_count: int
    task_evidence_count: int
    semantic_category: str
    validation_status: str
    provenance_type: str
    provenance_source_id: str | None
    scope_ref: dict[str, str | None]
    promotion_rationale: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeMemoryBrowseItemResponse(MemoryQualityResponseMixin):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    knowledge_key: str
    title: str
    summary: str
    knowledge_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    evidence_count: int
    contradiction_count: int
    semantic_category: str
    validation_status: str
    provenance_type: str
    tags: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BehaviorMemoryResponse(MemoryQualityResponseMixin):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    behavior_key: str
    behavior_category: str
    title: str
    summary: str
    details: str | None
    behavior_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    scope_type: str
    stability_score: float
    goal_relevance_score: float
    support_score: float
    contradiction_score: float
    evidence_count: int
    contradiction_count: int
    last_supported_at: datetime | None
    last_contradicted_at: datetime | None
    promotion_state_changed_at: datetime
    suppressed_reason_code: str | None
    suppressed_reason_note: str | None
    suppressed_by: str | None
    suppressed_at: datetime | None
    source_event_ids: list[str]
    source_memory_ids: list[str]
    tags: list[str]
    intervention_effect: str | None
    status: str
    compressed_into_id: str | None
    last_reviewed_at: datetime | None
    intervention_success_count: int
    intervention_failure_count: int
    cross_session_recurrence_count: int
    semantic_category: str
    validation_status: str
    provenance_type: str
    provenance_source_id: str | None
    scope_ref: dict[str, str | None]
    promotion_rationale: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BehaviorMemoryBrowseItemResponse(MemoryQualityResponseMixin):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    behavior_key: str
    behavior_category: str
    title: str
    summary: str
    behavior_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    evidence_count: int
    contradiction_count: int
    semantic_category: str
    validation_status: str
    provenance_type: str
    tags: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeMemoryRetrievalItemResponse(BaseModel):
    memory_id: str
    knowledge_key: str
    title: str
    summary: str
    knowledge_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    status: str
    score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class BehaviorMemoryRetrievalItemResponse(BaseModel):
    memory_id: str
    behavior_key: str
    behavior_category: str
    title: str
    summary: str
    behavior_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    status: str
    score: float
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeMemoryRetrievalResponse(BaseModel):
    items: list[KnowledgeMemoryRetrievalItemResponse]
    provider: str | None
    model: str | None
    latency_ms: int
    candidate_count: int

    model_config = {"from_attributes": True}


class BehaviorMemoryRetrievalResponse(BaseModel):
    items: list[BehaviorMemoryRetrievalItemResponse]
    provider: str | None
    model: str | None
    latency_ms: int
    candidate_count: int

    model_config = {"from_attributes": True}


class KnowledgeMemoryBrowseResponse(BaseModel):
    items: list[KnowledgeMemoryBrowseItemResponse]
    total: int
    limit: int
    offset: int


class BehaviorMemoryBrowseResponse(BaseModel):
    items: list[BehaviorMemoryBrowseItemResponse]
    total: int
    limit: int
    offset: int


class MemoryEvidenceLinkResponse(BaseModel):
    id: str
    memory_type: str
    memory_id: str
    learner_profile_id: str
    learner_goal_id: str | None
    evidence_source_type: str
    evidence_source_id: str
    evidence_role: str
    signal_type: str
    weight: float
    payload: dict[str, str | float | int | bool | None]
    observed_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryGovernanceDecisionResponse(BaseModel):
    id: str
    memory_type: str
    memory_id: str
    previous_status: str | None
    new_status: str
    decision_type: str
    trigger_source: str
    actor_type: str
    actor_id: str
    reason_code: str
    reason_note: str | None
    metrics_snapshot: dict[str, float | int | str | None]
    created_at: datetime

    model_config = {"from_attributes": True}


class MemoryAnnotationResponse(BaseModel):
    id: str
    memory_type: str
    memory_id: str
    annotation_code: str
    note: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReflectionCorpusMemoryItemResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class ReflectionCorpusSummaryResponse(BaseModel):
    total_items: int
    knowledge_items: int
    behavior_items: int
    candidate_items: int
    stable_items: int
    contradiction_focus_items: int
    stale_focus_items: int
    validate_items: int
    reinforce_items: int

    model_config = {"from_attributes": True}


class ReflectionCorpusResponse(BaseModel):
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    items: list[ReflectionCorpusMemoryItemResponse]
    summary: ReflectionCorpusSummaryResponse

    model_config = {"from_attributes": True}


class MemoryGovernanceSummaryResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class ConflictStatusImpactResponse(BaseModel):
    validation_status: str
    recommended_use: str
    governance_effect: str
    direct_status_change: bool
    severity_score: float | None = None
    handling_result: str | None = None

    model_config = {"from_attributes": True}


class MemoryConflictSetResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    topic_key: str
    conflict_type: str
    severity_score: float
    status: str
    summary: str
    reason_code: str
    reason_note: str | None
    handling_result: str
    status_impact: ConflictStatusImpactResponse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryConflictMemberResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class MemoryConflictDetailResponse(BaseModel):
    conflict_set: MemoryConflictSetResponse
    members: list[MemoryConflictMemberResponse]


class MemoryInterpretationFactResponse(BaseModel):
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

    model_config = {"from_attributes": True}


class MemoryInterpretationResponse(BaseModel):
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    facts: list[MemoryInterpretationFactResponse]
    behavior_patterns: list[MemoryInterpretationFactResponse]
    contested_items: list[MemoryInterpretationFactResponse]
    recommended_constraints: list[str]
    conflict_count: int

    model_config = {"from_attributes": True}


class SuppressMemoryRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=4000)


class AnnotateMemoryRequest(BaseModel):
    annotation_code: str = Field(min_length=1, max_length=128)
    note: str = Field(min_length=1, max_length=4000)


class RestoreMemoryRequest(BaseModel):
    restore_to_status: str = Field(default="active", pattern="^(candidate|active)$")
    reason: str | None = Field(default=None, max_length=4000)
