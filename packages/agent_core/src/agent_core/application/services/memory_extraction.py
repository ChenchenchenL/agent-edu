from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError as PydanticValidationError

from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.domain.errors import ValidationError


class StructuredMemoryExtractionCandidateInput(BaseModel):
    """Untrusted model output boundary.

    This schema intentionally rejects unknown fields such as `status`; validated
    input is converted to an internal dataclass only after normalization so model
    output cannot bypass candidate-only memory governance.
    """

    model_config = ConfigDict(extra="forbid")

    memory_type: Literal["knowledge", "behavior"]
    topic: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    summary: str = Field(min_length=1, max_length=2000)
    details: str | None = Field(default=None, max_length=4000)
    semantic_category: str | None = Field(default=None, max_length=64)
    behavior_category: str | None = Field(default=None, max_length=64)
    evidence_role: str | None = Field(default=None, max_length=32)
    confidence_score: float = Field(default=0.4, ge=0.0, le=1.0)
    importance_score: float = Field(default=0.45, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=12)


@dataclass(frozen=True)
class ValidatedMemoryExtractionCandidate:
    """Normalized internal candidate accepted by the governed materializer."""

    memory_type: str
    topic: str
    topic_key: str
    title: str
    summary: str
    details: str | None
    semantic_category: str
    behavior_category: str | None
    evidence_role: str
    confidence_score: float
    importance_score: float
    tags: list[str]


@dataclass(frozen=True)
class RejectedMemoryExtractionCandidate:
    index: int
    reason_code: str
    reason: str


@dataclass(frozen=True)
class MemoryExtractionValidationResult:
    candidates: list[ValidatedMemoryExtractionCandidate] = field(default_factory=list)
    rejected: list[RejectedMemoryExtractionCandidate] = field(default_factory=list)


def validate_structured_memory_extraction(
    raw_candidates: list[dict[str, object]],
) -> MemoryExtractionValidationResult:
    candidates: list[ValidatedMemoryExtractionCandidate] = []
    rejected: list[RejectedMemoryExtractionCandidate] = []
    for index, raw_candidate in enumerate(raw_candidates):
        try:
            candidate = StructuredMemoryExtractionCandidateInput.model_validate(raw_candidate)
            candidates.append(_normalize_candidate(candidate))
        except PydanticValidationError as exc:
            rejected.append(
                RejectedMemoryExtractionCandidate(
                    index=index,
                    reason_code="schema_validation_failed",
                    reason=str(exc),
                )
            )
        except ValidationError as exc:
            rejected.append(
                RejectedMemoryExtractionCandidate(
                    index=index,
                    reason_code="normalization_validation_failed",
                    reason=str(exc),
                )
            )
    return MemoryExtractionValidationResult(candidates=candidates, rejected=rejected)


def _normalize_candidate(candidate: StructuredMemoryExtractionCandidateInput) -> ValidatedMemoryExtractionCandidate:
    if candidate.memory_type == "knowledge" and candidate.behavior_category is not None:
        raise ValidationError("behavior_category is only supported for behavior memories.")
    behavior_category = None
    if candidate.memory_type == "behavior":
        behavior_category = MemoryNormalizer.classify_behavior_category(
            mode=None,
            struggle_note=None,
            progress_note=None,
            raw_category=candidate.behavior_category,
        )
    semantic_category = MemoryNormalizer.classify_semantic_category(
        memory_type=candidate.memory_type,
        behavior_category=behavior_category,
        raw_category=candidate.semantic_category,
    )
    evidence_role = MemoryNormalizer.classify_evidence_role(
        memory_type=candidate.memory_type,
        evidence_source_type="structured_extraction",
        raw_role=candidate.evidence_role,
    )
    topic = candidate.topic.strip()
    if not topic:
        raise ValidationError("topic is required.")
    summary = candidate.summary.strip()
    if not summary:
        raise ValidationError("summary is required.")
    title = candidate.title.strip() if candidate.title is not None and candidate.title.strip() else topic
    return ValidatedMemoryExtractionCandidate(
        memory_type=candidate.memory_type,
        topic=topic,
        topic_key=MemoryNormalizer.normalize_topic_key(topic),
        title=title,
        summary=summary,
        details=candidate.details.strip() if candidate.details is not None and candidate.details.strip() else None,
        semantic_category=semantic_category,
        behavior_category=behavior_category,
        evidence_role=evidence_role,
        confidence_score=candidate.confidence_score,
        importance_score=candidate.importance_score,
        tags=[tag.strip().casefold() for tag in candidate.tags if tag.strip()][:12],
    )
