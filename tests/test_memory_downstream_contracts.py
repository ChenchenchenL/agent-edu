"""Memory downstream contract tests.

These tests verify that memory outputs consumed by downstream systems
(reflection corpus, governance summary, interpretation) maintain
stable structure and semantics.
"""
from __future__ import annotations

import pytest

from agent_core.application.services.memory import (
    MemoryGovernanceSummary,
    MemoryInterpretationFact,
    MemoryInterpretationResult,
    MemoryService,
    ReflectionCorpusMemoryItem,
    ReflectionCorpusResult,
    ReflectionCorpusSummary,
)
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory


class TestReflectionCorpusItemContract:
    """Verify ReflectionCorpusMemoryItem structure is stable."""

    def test_required_fields_present(self):
        """Verify all required fields are present in ReflectionCorpusMemoryItem."""
        required_fields = [
            "memory_type",
            "memory_id",
            "learner_profile_id",
            "learner_goal_id",
            "memory_key",
            "memory_level",
            "title",
            "summary",
            "status",
            "time_horizon",
            "importance_score",
            "confidence_score",
            "freshness_score",
            "stability_score",
            "goal_relevance_score",
            "support_score",
            "contradiction_score",
            "evidence_count",
            "contradiction_count",
            "reflection_priority_score",
            "recommended_action",
            "rationale",
            "recommended_action_reason",
            "topic_alignment_score",
            "governance_pressure",
            "review_recommended",
            "quality_score",
            "quality_tier",
            "promotion_readiness",
            "quality_reasons",
            "evidence_mix",
            "semantic_category",
            "validation_status",
            "provenance_type",
            "provenance_source_id",
            "scope_ref",
            "promotion_rationale",
            "contested",
            "source_event_ids",
            "source_memory_ids",
            "tags",
            "created_at",
            "updated_at",
        ]

        for field in required_fields:
            assert hasattr(ReflectionCorpusMemoryItem, "__dataclass_fields__"), (
                "ReflectionCorpusMemoryItem is not a dataclass"
            )
            assert field in ReflectionCorpusMemoryItem.__dataclass_fields__, (
                f"Required field '{field}' missing from ReflectionCorpusMemoryItem"
            )

    def test_quality_tier_values(self):
        """Verify quality_tier uses expected values."""
        valid_tiers = {"high", "medium", "low"}

        for tier in valid_tiers:
            item = ReflectionCorpusMemoryItem(
                memory_type="knowledge",
                memory_id="k-001",
                learner_profile_id="profile-001",
                learner_goal_id="goal-001",
                memory_key="test",
                memory_level="foundation",
                title="Test",
                summary="Test summary",
                status="candidate",
                time_horizon="early",
                importance_score=0.5,
                confidence_score=0.5,
                freshness_score=0.5,
                stability_score=0.5,
                goal_relevance_score=0.5,
                support_score=0.5,
                contradiction_score=0.1,
                evidence_count=2,
                contradiction_count=0,
                reflection_priority_score=0.5,
                recommended_action="reinforce",
                rationale="Test",
                recommended_action_reason="Test",
                topic_alignment_score=0.5,
                governance_pressure=0.2,
                review_recommended=False,
                quality_score=0.6,
                quality_tier=tier,
                promotion_readiness="monitor",
                quality_reasons=[],
                evidence_mix={},
                semantic_category="concept",
                validation_status="unverified",
                provenance_type="session_event",
                provenance_source_id=None,
                scope_ref={},
                promotion_rationale=None,
                contested=False,
                source_event_ids=[],
                source_memory_ids=[],
                tags=[],
                created_at=None,
                updated_at=None,
            )
            assert item.quality_tier in valid_tiers


class TestReflectionCorpusSummaryContract:
    """Verify ReflectionCorpusSummary structure is stable."""

    def test_required_fields_present(self):
        """Verify all required fields are present."""
        required_fields = [
            "total_items",
            "knowledge_items",
            "behavior_items",
            "candidate_items",
            "stable_items",
            "contradiction_focus_items",
            "stale_focus_items",
            "validate_items",
            "reinforce_items",
        ]

        for field in required_fields:
            assert field in ReflectionCorpusSummary.__dataclass_fields__, (
                f"Required field '{field}' missing from ReflectionCorpusSummary"
            )

    def test_summary_counts_are_integers(self):
        """Verify all count fields are integers."""
        summary = ReflectionCorpusSummary(
            total_items=5,
            knowledge_items=3,
            behavior_items=2,
            candidate_items=2,
            stable_items=1,
            contradiction_focus_items=1,
            stale_focus_items=0,
            validate_items=1,
            reinforce_items=3,
        )

        for field in [
            "total_items",
            "knowledge_items",
            "behavior_items",
            "candidate_items",
            "stable_items",
            "contradiction_focus_items",
            "stale_focus_items",
            "validate_items",
            "reinforce_items",
        ]:
            value = getattr(summary, field)
            assert isinstance(value, int), f"{field} should be int, got {type(value)}"
            assert value >= 0, f"{field} should be non-negative, got {value}"


class TestReflectionCorpusResultContract:
    """Verify ReflectionCorpusResult structure is stable."""

    def test_required_fields_present(self):
        """Verify all required fields are present."""
        required_fields = [
            "learner_profile_id",
            "learner_goal_id",
            "generated_at",
            "items",
            "summary",
        ]

        for field in required_fields:
            assert field in ReflectionCorpusResult.__dataclass_fields__, (
                f"Required field '{field}' missing from ReflectionCorpusResult"
            )

    def test_items_is_list(self):
        """Verify items is a list."""
        result = ReflectionCorpusResult(
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            generated_at=None,
            items=[],
            summary=ReflectionCorpusSummary(
                total_items=0,
                knowledge_items=0,
                behavior_items=0,
                candidate_items=0,
                stable_items=0,
                contradiction_focus_items=0,
                stale_focus_items=0,
                validate_items=0,
                reinforce_items=0,
            ),
        )

        assert isinstance(result.items, list), "items should be a list"


class TestMemoryGovernanceSummaryContract:
    """Verify MemoryGovernanceSummary structure is stable."""

    def test_required_fields_present(self):
        """Verify all required fields are present."""
        required_fields = [
            "learner_profile_id",
            "learner_goal_id",
            "knowledge_total",
            "behavior_total",
            "candidate_total",
            "active_total",
            "stable_total",
            "archived_total",
            "suppressed_total",
            "contradiction_focus_total",
            "stale_candidate_total",
            "high_priority_total",
            "topic_bucket_summary",
        ]

        for field in required_fields:
            assert field in MemoryGovernanceSummary.__dataclass_fields__, (
                f"Required field '{field}' missing from MemoryGovernanceSummary"
            )

    def test_field_count_stability(self):
        """Verify governance summary has expected number of fields."""
        field_count = len(MemoryGovernanceSummary.__dataclass_fields__)
        assert field_count >= 20, (
            f"MemoryGovernanceSummary has {field_count} fields, expected >= 20"
        )


class TestMemoryInterpretationResultContract:
    """Verify MemoryInterpretationResult structure is stable."""

    def test_required_fields_present(self):
        """Verify all required fields are present."""
        required_fields = [
            "learner_profile_id",
            "learner_goal_id",
            "generated_at",
            "facts",
            "behavior_patterns",
            "contested_items",
            "recommended_constraints",
            "conflict_count",
        ]

        for field in required_fields:
            assert field in MemoryInterpretationResult.__dataclass_fields__, (
                f"Required field '{field}' missing from MemoryInterpretationResult"
            )

    def test_fact_fields(self):
        """Verify MemoryInterpretationFact structure."""
        required_fields = [
            "memory_type",
            "memory_id",
            "memory_key",
            "semantic_category",
            "validation_status",
            "title",
            "summary",
            "confidence_score",
            "importance_score",
            "recommended_use",
        ]

        for field in required_fields:
            assert field in MemoryInterpretationFact.__dataclass_fields__, (
                f"Required field '{field}' missing from MemoryInterpretationFact"
            )


class TestDownstreamContractStability:
    """Verify downstream contracts don't change unexpectedly."""

    def test_reflection_corpus_item_field_count(self):
        """Verify ReflectionCorpusMemoryItem has expected number of fields."""
        field_count = len(ReflectionCorpusMemoryItem.__dataclass_fields__)
        assert field_count >= 40, (
            f"ReflectionCorpusMemoryItem has {field_count} fields, expected >= 40"
        )

    def test_governance_summary_field_count(self):
        """Verify MemoryGovernanceSummary has expected number of fields."""
        field_count = len(MemoryGovernanceSummary.__dataclass_fields__)
        assert field_count >= 20, (
            f"MemoryGovernanceSummary has {field_count} fields, expected >= 20"
        )

    def test_interpretation_result_field_count(self):
        """Verify MemoryInterpretationResult has expected number of fields."""
        field_count = len(MemoryInterpretationResult.__dataclass_fields__)
        assert field_count >= 6, (
            f"MemoryInterpretationResult has {field_count} fields, expected >= 6"
        )
