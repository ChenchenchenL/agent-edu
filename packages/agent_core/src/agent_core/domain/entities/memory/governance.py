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
class RetrievedKnowledgeMemory:
    memory_id: str
    knowledge_key: str
    title: str
    summary: str
    knowledge_level: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float = 0.0
    goal_relevance_score: float = 0.0
    status: str = "active"
    governance_state: str = "active"
    eligibility_score: float | None = None
    score: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class RetrievedBehaviorMemory:
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
    stability_score: float = 0.0
    goal_relevance_score: float = 0.0
    status: str = "active"
    score: float = 0.0
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True)
class MemoryEvidenceLink:
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

    @classmethod
    def build(
        cls,
        *,
        memory_type: str,
        memory_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        evidence_source_type: str,
        evidence_source_id: str,
        evidence_role: str,
        signal_type: str,
        weight: float,
        payload: dict[str, str | float | int | bool | None],
        observed_at: datetime,
    ) -> "MemoryEvidenceLink":
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        if evidence_source_type not in MEMORY_EVIDENCE_SOURCE_TYPES:
            raise ValidationError("Unsupported memory evidence source type.")
        if evidence_role not in MEMORY_EVIDENCE_ROLES:
            raise ValidationError("Unsupported memory evidence role.")
        _validate_score("weight", weight)
        return cls(
            id=str(uuid4()),
            memory_type=memory_type,
            memory_id=memory_id,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            evidence_source_type=evidence_source_type,
            evidence_source_id=evidence_source_id,
            evidence_role=evidence_role,
            signal_type=signal_type,
            weight=weight,
            payload=payload,
            observed_at=observed_at,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class MemoryGovernanceDecision:
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

    @classmethod
    def build(
        cls,
        *,
        memory_type: str,
        memory_id: str,
        previous_status: str | None,
        new_status: str,
        decision_type: str,
        trigger_source: str,
        actor_type: str,
        actor_id: str,
        reason_code: str,
        reason_note: str | None,
        metrics_snapshot: dict[str, float | int | str | None],
    ) -> "MemoryGovernanceDecision":
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        if previous_status is not None:
            _validate_status(previous_status)
        _validate_status(new_status)
        if decision_type not in MEMORY_DECISION_TYPES:
            raise ValidationError("Unsupported memory decision type.")
        if trigger_source not in MEMORY_DECISION_TRIGGER_SOURCES:
            raise ValidationError("Unsupported memory decision trigger source.")
        if actor_type not in MEMORY_ACTOR_TYPES:
            raise ValidationError("Unsupported memory actor type.")
        return cls(
            id=str(uuid4()),
            memory_type=memory_type,
            memory_id=memory_id,
            previous_status=previous_status,
            new_status=new_status,
            decision_type=decision_type,
            trigger_source=trigger_source,
            actor_type=actor_type,
            actor_id=actor_id,
            reason_code=reason_code,
            reason_note=reason_note,
            metrics_snapshot=metrics_snapshot,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class MemoryAnnotation:
    id: str
    memory_type: str
    memory_id: str
    annotation_code: str
    note: str
    created_by: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        memory_type: str,
        memory_id: str,
        annotation_code: str,
        note: str,
        created_by: str,
    ) -> "MemoryAnnotation":
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        if not annotation_code.strip():
            raise ValidationError("annotation_code is required.")
        if not note.strip():
            raise ValidationError("note is required.")
        if not created_by.strip():
            raise ValidationError("created_by is required.")
        return cls(
            id=str(uuid4()),
            memory_type=memory_type,
            memory_id=memory_id,
            annotation_code=annotation_code.strip(),
            note=note.strip(),
            created_by=created_by.strip(),
            created_at=_utcnow(),
        )




MEMORY_PROMOTION_ELIGIBILITY_STATUSES = {
    "eligible",
    "insufficient_evidence",
    "below_score",
    "conflict_blocked",
    "suppressed_blocked",
    "stale_blocked",
}


@dataclass(frozen=True)
class MemoryPromotionEligibilityRecord:
    id: str
    memory_id: str
    learner_profile_id: str
    learner_goal_id: str | None
    status: str
    score: float
    independent_source_count: int
    high_signal_source_count: int
    evidence_span_hours: float
    conflict_blocked: bool
    blocked_conflict_set_id: str | None
    blocked_memory_id: str | None
    reason_codes: list[str]
    metrics_snapshot: dict[str, float | int | str | bool | None]
    evaluated_at: datetime
    superseded_at: datetime | None
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        memory_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        status: str,
        score: float,
        independent_source_count: int,
        high_signal_source_count: int,
        evidence_span_hours: float,
        conflict_blocked: bool,
        blocked_conflict_set_id: str | None,
        blocked_memory_id: str | None,
        reason_codes: list[str],
        metrics_snapshot: dict[str, float | int | str | bool | None],
        evaluated_at: datetime,
    ) -> "MemoryPromotionEligibilityRecord":
        if status not in MEMORY_PROMOTION_ELIGIBILITY_STATUSES:
            raise ValidationError("Unsupported promotion eligibility status.")
        _validate_score("score", score)
        if independent_source_count < 0 or high_signal_source_count < 0:
            raise ValidationError("Evidence counts must be non-negative.")
        if evidence_span_hours < 0:
            raise ValidationError("evidence_span_hours must be non-negative.")
        return cls(
            id=str(uuid4()),
            memory_id=memory_id,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            status=status,
            score=score,
            independent_source_count=independent_source_count,
            high_signal_source_count=high_signal_source_count,
            evidence_span_hours=evidence_span_hours,
            conflict_blocked=conflict_blocked,
            blocked_conflict_set_id=blocked_conflict_set_id,
            blocked_memory_id=blocked_memory_id,
            reason_codes=list(reason_codes),
            metrics_snapshot=dict(metrics_snapshot),
            evaluated_at=evaluated_at,
            superseded_at=None,
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class ConflictStatusImpact:
    validation_status: str
    recommended_use: str
    governance_effect: str
    direct_status_change: bool
    severity_score: float | None = None
    handling_result: str | None = None

    @classmethod
    def build(
        cls,
        *,
        validation_status: str,
        recommended_use: str,
        governance_effect: str,
        direct_status_change: bool,
        severity_score: float | None = None,
        handling_result: str | None = None,
    ) -> "ConflictStatusImpact":
        if not validation_status.strip():
            raise ValidationError("validation_status is required.")
        if not recommended_use.strip():
            raise ValidationError("recommended_use is required.")
        if not governance_effect.strip():
            raise ValidationError("governance_effect is required.")
        if severity_score is not None:
            _validate_score("severity_score", severity_score)
        return cls(
            validation_status=validation_status.strip(),
            recommended_use=recommended_use.strip(),
            governance_effect=governance_effect.strip(),
            direct_status_change=direct_status_change,
            severity_score=severity_score,
            handling_result=handling_result.strip() if handling_result is not None and handling_result.strip() else None,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> "ConflictStatusImpact":
        severity_value = payload.get("severity_score")
        severity_score = (
            float(severity_value)
            if isinstance(severity_value, (int, float)) and not isinstance(severity_value, bool)
            else None
        )
        handling_result = payload.get("handling_result")
        return cls.build(
            validation_status=str(payload.get("validation_status") or "unchanged"),
            recommended_use=str(payload.get("recommended_use") or "normal_governance"),
            governance_effect=str(payload.get("governance_effect") or "none"),
            direct_status_change=bool(payload.get("direct_status_change", False)),
            severity_score=severity_score,
            handling_result=str(handling_result) if handling_result is not None else None,
        )

    def to_payload(self) -> dict[str, str | float | bool]:
        payload: dict[str, str | float | bool] = {
            "validation_status": self.validation_status,
            "recommended_use": self.recommended_use,
            "governance_effect": self.governance_effect,
            "direct_status_change": self.direct_status_change,
        }
        if self.severity_score is not None:
            payload["severity_score"] = self.severity_score
        if self.handling_result is not None:
            payload["handling_result"] = self.handling_result
        return payload


