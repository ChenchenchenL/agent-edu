"""Memory quality regression tests.

These tests verify that quality score, quality tier, promotion readiness,
and quality reasons calculations remain stable across changes.

Fixtures are loaded from tests/fixtures/memory/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_core.application.services.memory import MemoryService
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "memory"


def _load_json(filename: str) -> dict:
    return json.loads((FIXTURES_DIR / filename).read_text())


def _build_knowledge_memory(data: dict) -> KnowledgeMemory:
    """Build a KnowledgeMemory from fixture data."""
    return KnowledgeMemory(
        id=data["id"],
        learner_profile_id=data["learner_profile_id"],
        learner_goal_id=data["learner_goal_id"],
        knowledge_key=data["knowledge_key"],
        title=data["title"],
        summary=data["summary"],
        details=data.get("details"),
        knowledge_level=data["knowledge_level"],
        time_horizon=data["time_horizon"],
        importance_score=data["importance_score"],
        confidence_score=data["confidence_score"],
        freshness_score=data["freshness_score"],
        stability_score=data.get("stability_score", 0.0),
        goal_relevance_score=data.get("goal_relevance_score", 0.0),
        support_score=data.get("support_score", 0.0),
        contradiction_score=data.get("contradiction_score", 0.0),
        evidence_count=data.get("evidence_count", 0),
        contradiction_count=data.get("contradiction_count", 0),
        assessment_evidence_count=data.get("assessment_evidence_count", 0),
        task_evidence_count=data.get("task_evidence_count", 0),
        source_event_ids=data.get("source_event_ids", []),
        status=data.get("status", "candidate"),
        semantic_category=data.get("semantic_category", "concept"),
        validation_status=data.get("validation_status", "unverified"),
    )


def _build_behavior_memory(data: dict) -> BehaviorMemory:
    """Build a BehaviorMemory from fixture data."""
    return BehaviorMemory(
        id=data["id"],
        learner_profile_id=data["learner_profile_id"],
        learner_goal_id=data["learner_goal_id"],
        behavior_key=data["behavior_key"],
        behavior_category=data["behavior_category"],
        title=data["title"],
        summary=data["summary"],
        details=data.get("details"),
        behavior_level=data["behavior_level"],
        time_horizon=data["time_horizon"],
        importance_score=data["importance_score"],
        confidence_score=data["confidence_score"],
        freshness_score=data["freshness_score"],
        stability_score=data.get("stability_score", 0.0),
        goal_relevance_score=data.get("goal_relevance_score", 0.0),
        support_score=data.get("support_score", 0.0),
        contradiction_score=data.get("contradiction_score", 0.0),
        evidence_count=data.get("evidence_count", 0),
        contradiction_count=data.get("contradiction_count", 0),
        intervention_success_count=data.get("intervention_success_count", 0),
        intervention_failure_count=data.get("intervention_failure_count", 0),
        cross_session_recurrence_count=data.get("cross_session_recurrence_count", 0),
        source_event_ids=data.get("source_event_ids", []),
        status=data.get("status", "candidate"),
        semantic_category=data.get("semantic_category", "strategy"),
        validation_status=data.get("validation_status", "unverified"),
    )


class TestKnowledgeQualityScore:
    """Knowledge memory quality score regression tests."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with minimal dependencies."""
        return MemoryService(
            repository=None,
            embedding_repository=None,
            knowledge_memory_repository=None,
            behavior_memory_repository=None,
            embedding_provider=None,
            audit_service=None,
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_knowledge_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_knowledge_quality_score(self, service, case):
        """Verify knowledge quality score falls within expected range."""
        memory = _build_knowledge_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._knowledge_quality_score(memory)

        assert expected["quality_score_min"] <= quality_score <= expected["quality_score_max"], (
            f"Quality score {quality_score:.4f} not in range "
            f"[{expected['quality_score_min']}, {expected['quality_score_max']}]"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_knowledge_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_knowledge_quality_tier(self, service, case):
        """Verify knowledge quality tier matches expected."""
        memory = _build_knowledge_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._knowledge_quality_score(memory)
        quality_tier = service._quality_tier(quality_score)

        assert quality_tier == expected["quality_tier"], (
            f"Quality tier {quality_tier} != expected {expected['quality_tier']}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_knowledge_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_knowledge_promotion_readiness(self, service, case):
        """Verify knowledge promotion readiness matches expected."""
        memory = _build_knowledge_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._knowledge_quality_score(memory)
        readiness = service._knowledge_promotion_readiness(memory, quality_score)

        assert readiness == expected["promotion_readiness"], (
            f"Promotion readiness {readiness} != expected {expected['promotion_readiness']}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_knowledge_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_knowledge_quality_reasons(self, service, case):
        """Verify knowledge quality reasons contain expected reasons."""
        memory = _build_knowledge_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._knowledge_quality_score(memory)
        readiness = service._knowledge_promotion_readiness(memory, quality_score)
        reasons = service._quality_reasons(
            memory=memory, quality_score=quality_score, readiness=readiness
        )

        for expected_reason in expected["expected_reasons"]:
            assert expected_reason in reasons, (
                f"Expected reason '{expected_reason}' not in {reasons}"
            )


class TestBehaviorQualityScore:
    """Behavior memory quality score regression tests."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with minimal dependencies."""
        return MemoryService(
            repository=None,
            embedding_repository=None,
            knowledge_memory_repository=None,
            behavior_memory_repository=None,
            embedding_provider=None,
            audit_service=None,
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_behavior_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_behavior_quality_score(self, service, case):
        """Verify behavior quality score falls within expected range."""
        memory = _build_behavior_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._behavior_quality_score(memory)

        assert expected["quality_score_min"] <= quality_score <= expected["quality_score_max"], (
            f"Quality score {quality_score:.4f} not in range "
            f"[{expected['quality_score_min']}, {expected['quality_score_max']}]"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_behavior_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_behavior_quality_tier(self, service, case):
        """Verify behavior quality tier matches expected."""
        memory = _build_behavior_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._behavior_quality_score(memory)
        quality_tier = service._quality_tier(quality_score)

        assert quality_tier == expected["quality_tier"], (
            f"Quality tier {quality_tier} != expected {expected['quality_tier']}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_behavior_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_behavior_promotion_readiness(self, service, case):
        """Verify behavior promotion readiness matches expected."""
        memory = _build_behavior_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._behavior_quality_score(memory)
        readiness = service._behavior_promotion_readiness(memory, quality_score)

        assert readiness == expected["promotion_readiness"], (
            f"Promotion readiness {readiness} != expected {expected['promotion_readiness']}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("quality_behavior_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_behavior_quality_reasons(self, service, case):
        """Verify behavior quality reasons contain expected reasons."""
        memory = _build_behavior_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._behavior_quality_score(memory)
        readiness = service._behavior_promotion_readiness(memory, quality_score)
        reasons = service._quality_reasons(
            memory=memory, quality_score=quality_score, readiness=readiness
        )

        for expected_reason in expected["expected_reasons"]:
            assert expected_reason in reasons, (
                f"Expected reason '{expected_reason}' not in {reasons}"
            )


class TestPromotionReadinessEdgeCases:
    """Promotion readiness edge case tests."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with minimal dependencies."""
        return MemoryService(
            repository=None,
            embedding_repository=None,
            knowledge_memory_repository=None,
            behavior_memory_repository=None,
            embedding_provider=None,
            audit_service=None,
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("promotion_readiness_cases.json")["knowledge_cases"],
        ids=lambda c: c["name"],
    )
    def test_knowledge_promotion_readiness_edge(self, service, case):
        """Verify knowledge promotion readiness at edge cases."""
        memory = _build_knowledge_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._knowledge_quality_score(memory)
        readiness = service._knowledge_promotion_readiness(memory, quality_score)

        assert readiness == expected["promotion_readiness"], (
            f"Edge case {case['name']}: readiness {readiness} != {expected['promotion_readiness']}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_json("promotion_readiness_cases.json")["behavior_cases"],
        ids=lambda c: c["name"],
    )
    def test_behavior_promotion_readiness_edge(self, service, case):
        """Verify behavior promotion readiness at edge cases."""
        memory = _build_behavior_memory(case["memory"])
        expected = case["expected"]

        quality_score = service._behavior_quality_score(memory)
        readiness = service._behavior_promotion_readiness(memory, quality_score)

        assert readiness == expected["promotion_readiness"], (
            f"Edge case {case['name']}: readiness {readiness} != {expected['promotion_readiness']}"
        )


class TestQualityTierBoundaries:
    """Quality tier boundary tests."""

    def test_high_tier_boundary(self):
        """Verify high tier starts at 0.7."""
        assert MemoryService._quality_tier(0.7) == "high"
        assert MemoryService._quality_tier(0.69) == "medium"
        assert MemoryService._quality_tier(1.0) == "high"

    def test_medium_tier_boundary(self):
        """Verify medium tier range."""
        assert MemoryService._quality_tier(0.45) == "medium"
        assert MemoryService._quality_tier(0.44) == "low"
        assert MemoryService._quality_tier(0.69) == "medium"

    def test_low_tier_boundary(self):
        """Verify low tier below 0.45."""
        assert MemoryService._quality_tier(0.0) == "low"
        assert MemoryService._quality_tier(0.44) == "low"
