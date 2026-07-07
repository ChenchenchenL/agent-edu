"""Unit tests for the Phase 1 AnswerGradingService (deterministic/llm/hybrid)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import pytest

from agent_core.application.services.quiz_grading import AnswerGradingService
from agent_core.domain.errors import ProviderError, ValidationError
from agent_core.infrastructure.llm.types import AnswerGradingDraft


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _StubLLMProvider:
    draft: AnswerGradingDraft | None = None
    exc: Exception | None = None
    calls: list[dict[str, Any]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.calls is None:
            object.__setattr__(self, "calls", [])

    async def generate_answer_grading(
        self,
        *,
        question_prompt: str,
        question_type: str,
        reference_answer: str,
        learner_answer: str,
        options: list[str] | None = None,
    ) -> AnswerGradingDraft:
        self.calls.append(
            {
                "question_prompt": question_prompt,
                "question_type": question_type,
                "reference_answer": reference_answer,
                "learner_answer": learner_answer,
                "options": options,
            }
        )
        if self.exc is not None:
            raise self.exc
        assert self.draft is not None
        return self.draft


def _valid_draft(**overrides: Any) -> AnswerGradingDraft:
    base = {
        "score": 0.9,
        "is_correct": True,
        "confidence": 0.8,
        "rubric_feedback": "Good reasoning.",
        "misconception_codes": [],
        "reasoning_quality": "sound",
        "provider": "stub",
        "model": "stub-model",
        "latency_ms": 0,
        "retry_count": 0,
        "response_shape_valid": True,
    }
    base.update(overrides)
    return AnswerGradingDraft(**base)


# ---------------------------------------------------------------------------
# Deterministic strategy
# ---------------------------------------------------------------------------


class TestDeterministicStrategy:
    def test_short_answer_exact_match(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="What is 2+2?",
            reference_answer="4",
            question_type="short_answer",
            options=(),
            learner_answer="4",
        )
        assert result.grading_status == "graded"
        assert result.grading_source == "deterministic"
        assert result.is_correct is True
        assert result.score == 1.0
        assert result.confidence == 1.0

    def test_short_answer_wrong(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="What is 2+2?",
            reference_answer="4",
            question_type="short_answer",
            options=(),
            learner_answer="5",
        )
        assert result.grading_status == "graded"
        assert result.is_correct is False
        assert result.score == 0.0

    def test_short_answer_normalizes_punctuation_and_case(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="What is the capital of France?",
            reference_answer="Paris",
            question_type="short_answer",
            options=(),
            learner_answer="  PARIS. ",
        )
        assert result.is_correct is True

    def test_mcq_correct(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="Pick the prime number.",
            reference_answer="7",
            question_type="mcq",
            options=("4", "6", "7", "9"),
            learner_answer="7",
        )
        assert result.grading_status == "graded"
        assert result.is_correct is True

    def test_mcq_wrong_option(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="Pick the prime number.",
            reference_answer="7",
            question_type="mcq",
            options=("4", "6", "7", "9"),
            learner_answer="4",
        )
        assert result.grading_status == "graded"
        assert result.is_correct is False

    def test_mcq_not_in_options_rejected(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="Pick the prime number.",
            reference_answer="7",
            question_type="mcq",
            options=("4", "6", "7", "9"),
            learner_answer="42",
        )
        assert result.grading_status == "rejected"
        assert result.validation_error == "mcq_answer_not_in_options"

    def test_open_ended_rejected(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        result = svc._grade_deterministic(
            question_prompt="Explain matrix multiplication.",
            reference_answer="Row-column dot product.",
            question_type="open_ended",
            options=(),
            learner_answer="anything",
        )
        assert result.grading_status == "rejected"
        assert result.validation_error == "deterministic_unsupported_for_open_ended"


# ---------------------------------------------------------------------------
# LLM strategy
# ---------------------------------------------------------------------------


class TestLLMStrategy:
    @pytest.mark.asyncio
    async def test_llm_valid_output(self) -> None:
        provider = _StubLLMProvider(draft=_valid_draft())
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="Explain something",
            reference_answer="reference",
            question_type="open_ended",
            options=(),
            learner_answer="learner text",
        )
        assert result.grading_status == "graded"
        assert result.grading_source == "llm"
        assert result.score == 0.9
        assert result.is_correct is True
        assert result.confidence == 0.8

    @pytest.mark.asyncio
    async def test_llm_invalid_score_becomes_needs_review(self) -> None:
        provider = _StubLLMProvider(draft=_valid_draft(score=1.5))
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="q",
            reference_answer="r",
            question_type="short_answer",
            options=(),
            learner_answer="x",
        )
        assert result.grading_status == "needs_review"
        assert result.score is None
        assert result.is_correct is None
        assert result.validation_error is not None
        assert "score" in result.validation_error

    @pytest.mark.asyncio
    async def test_llm_invalid_confidence_becomes_needs_review(self) -> None:
        provider = _StubLLMProvider(draft=_valid_draft(confidence=-0.1))
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="q",
            reference_answer="r",
            question_type="short_answer",
            options=(),
            learner_answer="x",
        )
        assert result.grading_status == "needs_review"
        assert "confidence" in (result.validation_error or "")

    @pytest.mark.asyncio
    async def test_llm_validation_error_becomes_needs_review(self) -> None:
        provider = _StubLLMProvider(exc=ValidationError("schema invalid"))
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="q",
            reference_answer="r",
            question_type="open_ended",
            options=(),
            learner_answer="x",
        )
        assert result.grading_status == "needs_review"
        assert result.needs_human_review is True
        assert "schema invalid" in (result.validation_error or "")

    @pytest.mark.asyncio
    async def test_llm_provider_error_becomes_needs_review(self) -> None:
        provider = _StubLLMProvider(exc=ProviderError("upstream boom"))
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="q",
            reference_answer="r",
            question_type="open_ended",
            options=(),
            learner_answer="x",
        )
        assert result.grading_status == "needs_review"
        assert "upstream boom" in (result.validation_error or "")

    @pytest.mark.asyncio
    async def test_llm_shape_flagged_invalid(self) -> None:
        provider = _StubLLMProvider(
            draft=replace(_valid_draft(), response_shape_valid=False)
        )
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_llm(
            question_prompt="q",
            reference_answer="r",
            question_type="open_ended",
            options=(),
            learner_answer="x",
        )
        assert result.grading_status == "needs_review"
        assert result.validation_error == "provider_flagged_invalid_shape"


# ---------------------------------------------------------------------------
# Hybrid strategy
# ---------------------------------------------------------------------------


class TestHybridStrategy:
    @pytest.mark.asyncio
    async def test_hybrid_uses_deterministic_for_short_answer(self) -> None:
        provider = _StubLLMProvider(draft=_valid_draft())
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_hybrid(
            question_prompt="2+2?",
            reference_answer="4",
            question_type="short_answer",
            options=(),
            learner_answer="4",
        )
        assert result.grading_status == "graded"
        assert result.grading_source == "hybrid"
        assert result.is_correct is True
        # Deterministic path short-circuits; LLM must NOT have been called.
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_hybrid_falls_back_to_llm_for_open_ended(self) -> None:
        provider = _StubLLMProvider(draft=_valid_draft(score=0.7, is_correct=True))
        svc = AnswerGradingService(llm_provider=provider)  # type: ignore[arg-type]
        result = await svc._grade_hybrid(
            question_prompt="Explain matrix multiplication",
            reference_answer="Row-column dot product",
            question_type="open_ended",
            options=(),
            learner_answer="it is row times column",
        )
        assert result.grading_status == "graded"
        assert result.grading_source == "hybrid"
        assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------


class TestStrategyDispatch:
    @pytest.mark.asyncio
    async def test_invalid_strategy_rejected(self) -> None:
        svc = AnswerGradingService(llm_provider=_StubLLMProvider())  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="Invalid grading strategy"):
            await svc.grade(
                question_prompt="q",
                reference_answer="r",
                question_type="short_answer",
                learner_answer="x",
                strategy="random",
            )
