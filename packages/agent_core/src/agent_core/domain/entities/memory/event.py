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
class MemoryEvent:
    id: str
    session_id: str
    learner_profile_id: str
    event_type: str
    memory_scope: str
    memory_level: str
    summary: str
    progress_note: str | None
    struggle_note: str | None
    concept_focus: str | None
    source_message_id: str | None
    tags: list[str]
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        learner_profile_id: str,
        event_type: str,
        memory_scope: str,
        memory_level: str,
        summary: str,
        progress_note: str | None,
        struggle_note: str | None,
        concept_focus: str | None,
        source_message_id: str | None,
        tags: list[str],
    ) -> "MemoryEvent":
        return cls(
            id=str(uuid4()),
            session_id=session_id,
            learner_profile_id=learner_profile_id,
            event_type=event_type,
            memory_scope=memory_scope,
            memory_level=memory_level,
            summary=summary,
            progress_note=progress_note,
            struggle_note=struggle_note,
            concept_focus=concept_focus,
            source_message_id=source_message_id,
            tags=tags,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class MemoryEmbeddingRecord:
    id: str
    memory_event_id: str
    session_id: str
    learner_profile_id: str
    memory_scope: str
    memory_level: str
    provider: str
    model: str
    dimensions: int
    vector: list[float]
    summary: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        memory_event_id: str,
        session_id: str,
        learner_profile_id: str,
        memory_scope: str,
        memory_level: str,
        provider: str,
        model: str,
        vector: list[float],
        summary: str,
    ) -> "MemoryEmbeddingRecord":
        return cls(
            id=str(uuid4()),
            memory_event_id=memory_event_id,
            session_id=session_id,
            learner_profile_id=learner_profile_id,
            memory_scope=memory_scope,
            memory_level=memory_level,
            provider=provider,
            model=model,
            dimensions=len(vector),
            vector=vector,
            summary=summary,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class RetrievedMemory:
    memory_event_id: str
    summary: str
    memory_scope: str
    memory_level: str
    progress_note: str | None
    struggle_note: str | None
    concept_focus: str | None
    score: float
    created_at: datetime


@dataclass(frozen=True)
class MemoryRetrievalResult:
    memories: list[RetrievedMemory]
    provider: str | None
    model: str | None
    latency_ms: int
    candidate_count: int


