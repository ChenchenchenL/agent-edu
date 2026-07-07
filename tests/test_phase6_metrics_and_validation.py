"""Tests for Phase 6 observability metrics and SkillResolution confidence validation."""

from __future__ import annotations

import pytest

from agent_core.domain.entities.skill.execution import SkillResolution
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.observability.metrics import (
    observe_corpus_trigger_reflection,
    observe_high_risk_auto_sandbox,
    observe_low_confidence_burst,
    observe_routing_regression,
)


class TestSkillResolutionConfidenceValidation:
    def test_confidence_none_is_valid(self) -> None:
        resolution = SkillResolution.build(
            skill_name="tutor",
            surface="chat",
            implementation_binding="tutor_v1",
            confidence=None,
        )
        assert resolution.confidence is None

    def test_confidence_zero_is_valid(self) -> None:
        resolution = SkillResolution.build(
            skill_name="tutor",
            surface="chat",
            implementation_binding="tutor_v1",
            confidence=0.0,
        )
        assert resolution.confidence == 0.0

    def test_confidence_one_is_valid(self) -> None:
        resolution = SkillResolution.build(
            skill_name="tutor",
            surface="chat",
            implementation_binding="tutor_v1",
            confidence=1.0,
        )
        assert resolution.confidence == 1.0

    def test_confidence_mid_range_is_valid(self) -> None:
        resolution = SkillResolution.build(
            skill_name="tutor",
            surface="chat",
            implementation_binding="tutor_v1",
            confidence=0.75,
        )
        assert resolution.confidence == 0.75

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence must be between 0.0 and 1.0"):
            SkillResolution.build(
                skill_name="tutor",
                surface="chat",
                implementation_binding="tutor_v1",
                confidence=1.5,
            )

    def test_confidence_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence must be between 0.0 and 1.0"):
            SkillResolution.build(
                skill_name="tutor",
                surface="chat",
                implementation_binding="tutor_v1",
                confidence=-0.1,
            )


class TestObserveMetricsFunctions:
    """Verify each observe_* helper can be called without error and increments its counter."""

    def test_observe_routing_regression(self) -> None:
        observe_routing_regression(skill_name="tutor", surface="chat")

    def test_observe_low_confidence_burst(self) -> None:
        observe_low_confidence_burst(skill_name="tutor", surface="chat")

    def test_observe_corpus_trigger_reflection(self) -> None:
        observe_corpus_trigger_reflection(scope="goal", trigger_source="corpus_review_threshold")

    def test_observe_high_risk_auto_sandbox(self) -> None:
        observe_high_risk_auto_sandbox(proposal_type="routing_policy")

    def test_observe_routing_regression_increments_counter(self) -> None:
        from prometheus_client import REGISTRY

        before = REGISTRY.get_sample_value(
            "agent_edu_routing_regression_total",
            {"skill_name": "counter_test", "surface": "chat"},
        ) or 0.0
        observe_routing_regression(skill_name="counter_test", surface="chat")
        after = REGISTRY.get_sample_value(
            "agent_edu_routing_regression_total",
            {"skill_name": "counter_test", "surface": "chat"},
        ) or 0.0
        assert after == before + 1.0

    def test_observe_high_risk_auto_sandbox_increments_counter(self) -> None:
        from prometheus_client import REGISTRY

        before = REGISTRY.get_sample_value(
            "agent_edu_high_risk_auto_sandbox_total",
            {"proposal_type": "template_policy"},
        ) or 0.0
        observe_high_risk_auto_sandbox(proposal_type="template_policy")
        after = REGISTRY.get_sample_value(
            "agent_edu_high_risk_auto_sandbox_total",
            {"proposal_type": "template_policy"},
        ) or 0.0
        assert after == before + 1.0
