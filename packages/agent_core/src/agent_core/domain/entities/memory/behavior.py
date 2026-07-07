from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from agent_core.domain.errors import ValidationError

MEMORY_HORIZONS = {"early", "mid", "long"}
KNOWLEDGE_LEVELS = {"foundation", "core", "advanced", "application"}
BEHAVIOR_LEVELS = {"surface", "recurrent", "persistent", "critical"}
MEMORY_STATUSES = {"candidate", "active", "stable", "compressed", "archived", "suppressed"}
MEMORY_SCOPE_TYPES = {"profile_global", "goal_scoped"}
MEMORY_TYPES = {"knowledge", "behavior"}
MEMORY_BEHAVIOR_CATEGORIES = {"support_request", "guided_progress", "error_pattern", "response_preference", "affect"}
MEMORY_SEMANTIC_CATEGORIES = {"concept", "prerequisite", "misconception", "strategy", "preference", "affect", "meta"}
MEMORY_VALIDATION_STATUSES = {"unverified", "validated", "contested", "stale", "locally_valid"}
MEMORY_PROVENANCE_TYPES = {
    "session_event",
    "task_attempt",
    "assessment",
    "reflection",
    "operator",
    "compression",
    "system_inference",
}
MEMORY_EVIDENCE_SOURCE_TYPES = {
    "session_memory_event",
    "task_attempt",
    "topic_mastery",
    "operator_annotation",
    "reflection_record",
    "reflection_outcome",
}
MEMORY_EVIDENCE_ROLES = {"supporting", "contradicting", "refreshing"}
MEMORY_DECISION_TYPES = {"promote", "demote", "archive", "compress", "suppress", "restore", "refresh"}
MEMORY_DECISION_TRIGGER_SOURCES = {
    "evidence_refresh",
    "promotion_cycle",
    "decay_cycle",
    "compression_cycle",
    "operator_api",
}
MEMORY_ACTOR_TYPES = {"system", "operator"}
MEMORY_RETRIEVAL_STATUSES = {"active", "stable"}


class MemoryFieldUnset(Enum):
    UNSET = "unset"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_score(name: str, value: float) -> None:
    if value < 0.0 or value > 1.0:
        raise ValidationError(f"{name} must be between 0 and 1.")


def _validate_status(status: str) -> None:
    if status not in MEMORY_STATUSES:
        raise ValidationError("Unsupported memory status.")


def _validate_scope_type(scope_type: str) -> None:
    if scope_type not in MEMORY_SCOPE_TYPES:
        raise ValidationError("Unsupported memory scope type.")


def _validate_semantic_category(semantic_category: str) -> None:
    if semantic_category not in MEMORY_SEMANTIC_CATEGORIES:
        raise ValidationError("Unsupported memory semantic category.")


def _validate_behavior_category(behavior_category: str) -> None:
    if behavior_category not in MEMORY_BEHAVIOR_CATEGORIES:
        raise ValidationError("Unsupported behavior memory category.")


def _validate_validation_status(validation_status: str) -> None:
    if validation_status not in MEMORY_VALIDATION_STATUSES:
        raise ValidationError("Unsupported memory validation status.")


def _validate_provenance_type(provenance_type: str) -> None:
    if provenance_type not in MEMORY_PROVENANCE_TYPES:
        raise ValidationError("Unsupported memory provenance type.")


@dataclass(frozen=True)
class BehaviorMemoryStatusUpdate:
    stability_score: float | None = None
    support_score: float | None = None
    contradiction_score: float | None = None
    evidence_count: int | None = None
    contradiction_count: int | None = None
    last_supported_at: datetime | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    last_contradicted_at: datetime | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    promotion_state_changed_at: datetime | None = None
    suppressed_reason_code: str | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    suppressed_reason_note: str | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    suppressed_by: str | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    suppressed_at: datetime | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    freshness_score: float | None = None
    goal_relevance_score: float | None = None
    confidence_score: float | None = None
    importance_score: float | None = None
    intervention_success_count: int | None = None
    intervention_failure_count: int | None = None
    cross_session_recurrence_count: int | None = None
    last_reviewed_at: datetime | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    intervention_effect: str | None | MemoryFieldUnset = MemoryFieldUnset.UNSET
    validation_status: str | None = None
    promotion_rationale: str | None | MemoryFieldUnset = MemoryFieldUnset.UNSET

    @classmethod
    def from_legacy_kwargs(cls, values: dict[str, object]) -> "BehaviorMemoryStatusUpdate":
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValidationError(f"Unsupported behavior memory status update fields: {', '.join(unknown)}.")
        return cls(**{key: value for key, value in values.items() if value is not None})


@dataclass(frozen=True)
class BehaviorMemory:
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
    scope_type: str = "profile_global"
    stability_score: float = 0.0
    goal_relevance_score: float = 0.0
    support_score: float = 0.0
    contradiction_score: float = 0.0
    evidence_count: int = 0
    contradiction_count: int = 0
    last_supported_at: datetime | None = None
    last_contradicted_at: datetime | None = None
    promotion_state_changed_at: datetime = field(default_factory=_utcnow)
    suppressed_reason_code: str | None = None
    suppressed_reason_note: str | None = None
    suppressed_by: str | None = None
    suppressed_at: datetime | None = None
    source_event_ids: list[str] = field(default_factory=list)
    source_memory_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    intervention_effect: str | None = None
    status: str = "candidate"
    compressed_into_id: str | None = None
    last_reviewed_at: datetime | None = None
    intervention_success_count: int = 0
    intervention_failure_count: int = 0
    cross_session_recurrence_count: int = 0
    semantic_category: str = "strategy"
    validation_status: str = "unverified"
    provenance_type: str = "system_inference"
    provenance_source_id: str | None = None
    scope_ref: dict[str, str | None] = field(default_factory=dict)
    promotion_rationale: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    @property
    def is_positive_behavior(self) -> bool:
        return "success_pattern" in (self.tags or []) or "positive" in (self.tags or [])

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        title: str,
        summary: str,
        details: str | None,
        behavior_level: str,
        time_horizon: str,
        importance_score: float,
        confidence_score: float,
        freshness_score: float,
        source_event_ids: list[str],
        source_memory_ids: list[str],
        tags: list[str],
        intervention_effect: str | None,
    ) -> "BehaviorMemory":
        _validate_behavior_category(behavior_category)
        if behavior_level not in BEHAVIOR_LEVELS:
            raise ValidationError("Unsupported behavior memory level.")
        if time_horizon not in MEMORY_HORIZONS:
            raise ValidationError("Unsupported memory time horizon.")
        for score_name, score_value in (
            ("importance_score", importance_score),
            ("confidence_score", confidence_score),
            ("freshness_score", freshness_score),
        ):
            _validate_score(score_name, score_value)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            behavior_key=behavior_key,
            behavior_category=behavior_category,
            title=title,
            summary=summary,
            details=details,
            behavior_level=behavior_level,
            time_horizon=time_horizon,
            importance_score=importance_score,
            confidence_score=confidence_score,
            freshness_score=freshness_score,
            scope_type="goal_scoped" if learner_goal_id is not None else "profile_global",
            stability_score=0.0,
            goal_relevance_score=1.0 if learner_goal_id is not None else 0.5,
            support_score=0.0,
            contradiction_score=0.0,
            evidence_count=0,
            contradiction_count=0,
            last_supported_at=now,
            last_contradicted_at=None,
            promotion_state_changed_at=now,
            suppressed_reason_code=None,
            suppressed_reason_note=None,
            suppressed_by=None,
            suppressed_at=None,
            source_event_ids=source_event_ids,
            source_memory_ids=source_memory_ids,
            tags=tags,
            intervention_effect=intervention_effect,
            status="candidate",
            compressed_into_id=None,
            last_reviewed_at=None,
            intervention_success_count=0,
            intervention_failure_count=0,
            cross_session_recurrence_count=0,
            semantic_category="strategy" if behavior_category != "affect" else "affect",
            validation_status="unverified",
            provenance_type="session_event" if source_event_ids else "system_inference",
            provenance_source_id=source_event_ids[0] if source_event_ids else None,
            scope_ref={
                "learner_profile_id": learner_profile_id,
                "learner_goal_id": learner_goal_id,
                "topic_key": behavior_key,
                "phase": time_horizon,
            },
            promotion_rationale=None,
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: str,
        update: BehaviorMemoryStatusUpdate | None = None,
        **legacy_updates: object,
    ) -> "BehaviorMemory":
        _validate_status(status)
        if update is not None and legacy_updates:
            raise ValidationError("Use either update or keyword fields, not both.")
        status_update = update or BehaviorMemoryStatusUpdate.from_legacy_kwargs(legacy_updates)
        if status_update.validation_status is not None:
            _validate_validation_status(status_update.validation_status)
        updated_at = _utcnow()
        return BehaviorMemory(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            behavior_key=self.behavior_key,
            behavior_category=self.behavior_category,
            title=self.title,
            summary=self.summary,
            details=self.details,
            behavior_level=self.behavior_level,
            time_horizon=self.time_horizon,
            importance_score=self.importance_score
            if status_update.importance_score is None
            else status_update.importance_score,
            confidence_score=self.confidence_score
            if status_update.confidence_score is None
            else status_update.confidence_score,
            freshness_score=self.freshness_score
            if status_update.freshness_score is None
            else status_update.freshness_score,
            scope_type=self.scope_type,
            stability_score=self.stability_score
            if status_update.stability_score is None
            else status_update.stability_score,
            goal_relevance_score=self.goal_relevance_score
            if status_update.goal_relevance_score is None
            else status_update.goal_relevance_score,
            support_score=self.support_score if status_update.support_score is None else status_update.support_score,
            contradiction_score=self.contradiction_score
            if status_update.contradiction_score is None
            else status_update.contradiction_score,
            evidence_count=self.evidence_count if status_update.evidence_count is None else status_update.evidence_count,
            contradiction_count=self.contradiction_count
            if status_update.contradiction_count is None
            else status_update.contradiction_count,
            last_supported_at=self.last_supported_at
            if status_update.last_supported_at is MemoryFieldUnset.UNSET
            else status_update.last_supported_at,
            last_contradicted_at=self.last_contradicted_at
            if status_update.last_contradicted_at is MemoryFieldUnset.UNSET
            else status_update.last_contradicted_at,
            promotion_state_changed_at=status_update.promotion_state_changed_at or updated_at,
            suppressed_reason_code=self.suppressed_reason_code
            if status_update.suppressed_reason_code is MemoryFieldUnset.UNSET
            else status_update.suppressed_reason_code,
            suppressed_reason_note=self.suppressed_reason_note
            if status_update.suppressed_reason_note is MemoryFieldUnset.UNSET
            else status_update.suppressed_reason_note,
            suppressed_by=self.suppressed_by
            if status_update.suppressed_by is MemoryFieldUnset.UNSET
            else status_update.suppressed_by,
            suppressed_at=self.suppressed_at
            if status_update.suppressed_at is MemoryFieldUnset.UNSET
            else status_update.suppressed_at,
            source_event_ids=self.source_event_ids,
            source_memory_ids=self.source_memory_ids,
            tags=self.tags,
            intervention_effect=self.intervention_effect
            if status_update.intervention_effect is MemoryFieldUnset.UNSET
            else status_update.intervention_effect,
            status=status,
            compressed_into_id=self.compressed_into_id,
            last_reviewed_at=self.last_reviewed_at
            if status_update.last_reviewed_at is MemoryFieldUnset.UNSET
            else status_update.last_reviewed_at,
            intervention_success_count=self.intervention_success_count
            if status_update.intervention_success_count is None
            else status_update.intervention_success_count,
            intervention_failure_count=self.intervention_failure_count
            if status_update.intervention_failure_count is None
            else status_update.intervention_failure_count,
            cross_session_recurrence_count=self.cross_session_recurrence_count
            if status_update.cross_session_recurrence_count is None
            else status_update.cross_session_recurrence_count,
            semantic_category=self.semantic_category,
            validation_status=self.validation_status
            if status_update.validation_status is None
            else status_update.validation_status,
            provenance_type=self.provenance_type,
            provenance_source_id=self.provenance_source_id,
            scope_ref=dict(self.scope_ref),
            promotion_rationale=self.promotion_rationale
            if status_update.promotion_rationale is MemoryFieldUnset.UNSET
            else status_update.promotion_rationale,
            created_at=self.created_at,
            updated_at=updated_at,
        )

    def with_compression(self, *, compressed_into_id: str) -> "BehaviorMemory":
        return BehaviorMemory(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            behavior_key=self.behavior_key,
            behavior_category=self.behavior_category,
            title=self.title,
            summary=self.summary,
            details=self.details,
            behavior_level=self.behavior_level,
            time_horizon=self.time_horizon,
            importance_score=self.importance_score,
            confidence_score=self.confidence_score,
            freshness_score=self.freshness_score,
            scope_type=self.scope_type,
            stability_score=self.stability_score,
            goal_relevance_score=self.goal_relevance_score,
            support_score=self.support_score,
            contradiction_score=self.contradiction_score,
            evidence_count=self.evidence_count,
            contradiction_count=self.contradiction_count,
            last_supported_at=self.last_supported_at,
            last_contradicted_at=self.last_contradicted_at,
            promotion_state_changed_at=_utcnow(),
            suppressed_reason_code=self.suppressed_reason_code,
            suppressed_reason_note=self.suppressed_reason_note,
            suppressed_by=self.suppressed_by,
            suppressed_at=self.suppressed_at,
            source_event_ids=self.source_event_ids,
            source_memory_ids=self.source_memory_ids,
            tags=self.tags,
            intervention_effect=self.intervention_effect,
            status="compressed",
            compressed_into_id=compressed_into_id,
            last_reviewed_at=self.last_reviewed_at,
            intervention_success_count=self.intervention_success_count,
            intervention_failure_count=self.intervention_failure_count,
            cross_session_recurrence_count=self.cross_session_recurrence_count,
            semantic_category=self.semantic_category,
            validation_status=self.validation_status,
            provenance_type=self.provenance_type,
            provenance_source_id=self.provenance_source_id,
            scope_ref=dict(self.scope_ref),
            promotion_rationale=self.promotion_rationale,
            created_at=self.created_at,
            updated_at=_utcnow(),
        )


@dataclass(frozen=True)
class BehaviorMemoryEmbeddingRecord:
    id: str
    memory_id: str
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
    stability_score: float = 0.0
    goal_relevance_score: float = 0.0
    scope_type: str = "profile_global"
    provider: str = ""
    model: str = ""
    dimensions: int = 0
    vector: list[float] = field(default_factory=list)
    status: str = "candidate"
    created_at: datetime = field(default_factory=_utcnow)

    @classmethod
    def build(
        cls,
        *,
        memory_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        title: str,
        summary: str,
        behavior_level: str,
        time_horizon: str,
        importance_score: float,
        confidence_score: float,
        freshness_score: float,
        stability_score: float,
        goal_relevance_score: float,
        scope_type: str,
        provider: str,
        model: str,
        vector: list[float],
        status: str = "candidate",
    ) -> "BehaviorMemoryEmbeddingRecord":
        _validate_status(status)
        _validate_scope_type(scope_type)
        return cls(
            id=str(uuid4()),
            memory_id=memory_id,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            behavior_key=behavior_key,
            behavior_category=behavior_category,
            title=title,
            summary=summary,
            behavior_level=behavior_level,
            time_horizon=time_horizon,
            importance_score=importance_score,
            confidence_score=confidence_score,
            freshness_score=freshness_score,
            stability_score=stability_score,
            goal_relevance_score=goal_relevance_score,
            scope_type=scope_type,
            provider=provider,
            model=model,
            dimensions=len(vector),
            vector=vector,
            status=status,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class BehaviorMemoryRetrievalResult:
    memories: list[RetrievedBehaviorMemory]
    provider: str | None
    model: str | None
    latency_ms: int
    candidate_count: int


