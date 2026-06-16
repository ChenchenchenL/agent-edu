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
class MemoryConflictSet:
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    topic_key: str
    conflict_type: str
    severity_score: float
    status: str
    summary: str
    created_at: datetime
    updated_at: datetime
    reason_code: str
    handling_result: str
    status_impact: ConflictStatusImpact
    reason_note: str | None = None

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        topic_key: str,
        conflict_type: str,
        severity_score: float,
        summary: str,
        reason_code: str,
        handling_result: str,
        status_impact: ConflictStatusImpact,
        reason_note: str | None = None,
    ) -> "MemoryConflictSet":
        _validate_score("severity_score", severity_score)
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        if not handling_result.strip():
            raise ValidationError("handling_result is required.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            topic_key=topic_key,
            conflict_type=conflict_type,
            severity_score=severity_score,
            status="open",
            summary=summary,
            created_at=now,
            updated_at=now,
            reason_code=reason_code.strip(),
            reason_note=reason_note,
            handling_result=handling_result.strip(),
            status_impact=status_impact,
        )


@dataclass(frozen=True)
class MemoryConflictMember:
    id: str
    conflict_set_id: str
    memory_type: str
    memory_id: str
    memory_key: str
    stance: str
    support_score: float
    contradiction_score: float
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        conflict_set_id: str,
        memory_type: str,
        memory_id: str,
        memory_key: str,
        stance: str,
        support_score: float,
        contradiction_score: float,
    ) -> "MemoryConflictMember":
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        _validate_score("support_score", support_score)
        _validate_score("contradiction_score", contradiction_score)
        return cls(
            id=str(uuid4()),
            conflict_set_id=conflict_set_id,
            memory_type=memory_type,
            memory_id=memory_id,
            memory_key=memory_key,
            stance=stance,
            support_score=support_score,
            contradiction_score=contradiction_score,
            created_at=_utcnow(),
        )
