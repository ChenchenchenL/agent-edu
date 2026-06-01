from __future__ import annotations

from re import sub

from agent_core.domain.entities.memory import (
    MEMORY_BEHAVIOR_CATEGORIES,
    MEMORY_EVIDENCE_ROLES,
    MEMORY_SEMANTIC_CATEGORIES,
    MEMORY_TYPES,
)
from agent_core.domain.errors import ValidationError


class MemoryNormalizer:
    _STOPWORDS = {"the", "a", "an", "of", "for", "to", "and", "or", "is", "are"}

    @classmethod
    def normalize_topic_key(cls, value: str) -> str:
        normalized = sub(r"[^a-z0-9]+", " ", value.casefold())
        tokens = [token for token in normalized.split() if token and token not in cls._STOPWORDS]
        return "-".join(tokens[:8]) if tokens else "memory"

    @classmethod
    def topic_tokens(cls, value: str) -> list[str]:
        return [token for token in cls.normalize_topic_key(value).split("-") if token]

    @classmethod
    def classify_behavior_category(
        cls,
        *,
        mode: str | None,
        struggle_note: str | None,
        progress_note: str | None,
        raw_category: str | None = None,
    ) -> str:
        if raw_category is not None:
            return cls.normalize_behavior_category(raw_category)
        if mode == "hint":
            return "support_request"
        if struggle_note is not None and progress_note is not None:
            return "guided_progress"
        if struggle_note is not None:
            return "error_pattern"
        return "response_preference"

    @staticmethod
    def normalize_behavior_category(raw_category: str) -> str:
        category = sub(r"[^a-z0-9]+", "_", raw_category.casefold()).strip("_")
        if category not in MEMORY_BEHAVIOR_CATEGORIES:
            raise ValidationError("Unsupported behavior memory category.")
        return category

    @classmethod
    def classify_semantic_category(
        cls,
        *,
        memory_type: str,
        knowledge_level: str | None = None,
        behavior_category: str | None = None,
        raw_category: str | None = None,
    ) -> str:
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        if raw_category is not None:
            return cls.normalize_semantic_category(raw_category)
        if memory_type == "knowledge":
            return "prerequisite" if knowledge_level == "foundation" else "concept"
        if behavior_category == "affect":
            return "affect"
        return "strategy"

    @staticmethod
    def normalize_semantic_category(raw_category: str) -> str:
        category = sub(r"[^a-z0-9]+", "_", raw_category.casefold()).strip("_")
        if category not in MEMORY_SEMANTIC_CATEGORIES:
            raise ValidationError("Unsupported memory semantic category.")
        return category

    @classmethod
    def classify_evidence_role(
        cls,
        *,
        memory_type: str,
        evidence_source_type: str,
        raw_role: str | None = None,
        outcome_status: str | None = None,
        evaluation_status: str | None = None,
        has_progress: bool = False,
        has_struggle: bool = False,
    ) -> str:
        if memory_type not in MEMORY_TYPES:
            raise ValidationError("Unsupported memory type.")
        if raw_role is not None:
            return cls.normalize_evidence_role(raw_role)
        if evidence_source_type == "task_attempt":
            if outcome_status == "completed":
                return "supporting" if memory_type == "knowledge" else "contradicting"
            if outcome_status in {"failed", "skipped"}:
                return "contradicting" if memory_type == "knowledge" else "supporting"
            return "refreshing"
        if evidence_source_type == "session_memory_event":
            if memory_type == "knowledge":
                if has_progress:
                    return "supporting"
                if has_struggle:
                    return "contradicting"
                return "refreshing"
            return "supporting" if has_struggle else "refreshing"
        if evidence_source_type == "reflection_outcome":
            if evaluation_status == "effective":
                return "supporting"
            if evaluation_status == "ineffective":
                return "contradicting"
            return "refreshing"
        if evidence_source_type == "topic_mastery":
            return "refreshing"
        return "refreshing"

    @staticmethod
    def normalize_evidence_role(raw_role: str) -> str:
        role = sub(r"[^a-z0-9]+", "_", raw_role.casefold()).strip("_")
        if role not in MEMORY_EVIDENCE_ROLES:
            raise ValidationError("Unsupported memory evidence role.")
        return role


# Backward-compatible alias for callers outside this package that still import
# the old name. New application code should use MemoryNormalizer.
MemoryNormalizationPolicy = MemoryNormalizer
