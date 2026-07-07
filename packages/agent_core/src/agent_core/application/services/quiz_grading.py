"""Answer grading service with deterministic / llm / hybrid strategies.

This service produces grading *evidence* only. It never writes memory,
triggers skill proposals, or returns mastery deltas. All outputs flow into
``SessionQuizAnswerAttempt`` and are audited downstream.
"""

from __future__ import annotations

import logging
import re
import string
from dataclasses import dataclass

from agent_core.domain.errors import ProviderError, ValidationError
from agent_core.infrastructure.llm.types import AnswerGradingDraft, LLMProvider

_LOGGER = logging.getLogger(__name__)

_PUNCT_REMOVER = str.maketrans("", "", string.punctuation)
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class GradingResult:
    grading_status: str
    grading_source: str | None
    score: float | None
    is_correct: bool | None
    confidence: float | None
    rubric_feedback: str | None
    misconception_codes: tuple[str, ...]
    reasoning_quality: str | None
    needs_human_review: bool
    validation_error: str | None


def _normalize_text(value: str) -> str:
    stripped = (value or "").strip().lower()
    stripped = stripped.translate(_PUNCT_REMOVER)
    return _WHITESPACE_RE.sub(" ", stripped).strip()


class AnswerGradingService:
    """Grade a learner answer using one of three strategies."""

    def __init__(self, *, llm_provider: LLMProvider) -> None:
        self._llm_provider = llm_provider

    async def grade(
        self,
        *,
        question_prompt: str,
        reference_answer: str,
        question_type: str,
        options: tuple[str, ...] | list[str] | None = None,
        learner_answer: str,
        strategy: str = "hybrid",
    ) -> GradingResult:
        if strategy not in {"deterministic", "llm", "hybrid"}:
            raise ValueError(f"Invalid grading strategy '{strategy}'.")

        normalized_options: tuple[str, ...] = tuple(options) if options else ()

        if strategy == "deterministic":
            return self._grade_deterministic(
                question_prompt=question_prompt,
                reference_answer=reference_answer,
                question_type=question_type,
                options=normalized_options,
                learner_answer=learner_answer,
            )
        if strategy == "llm":
            return await self._grade_llm(
                question_prompt=question_prompt,
                reference_answer=reference_answer,
                question_type=question_type,
                options=normalized_options,
                learner_answer=learner_answer,
            )
        return await self._grade_hybrid(
            question_prompt=question_prompt,
            reference_answer=reference_answer,
            question_type=question_type,
            options=normalized_options,
            learner_answer=learner_answer,
        )

    # ------------------------------------------------------------------ #
    # Deterministic path
    # ------------------------------------------------------------------ #
    def _grade_deterministic(
        self,
        *,
        question_prompt: str,
        reference_answer: str,
        question_type: str,
        options: tuple[str, ...],
        learner_answer: str,
    ) -> GradingResult:
        if question_type == "open_ended":
            return GradingResult(
                grading_status="rejected",
                grading_source=None,
                score=None,
                is_correct=None,
                confidence=None,
                rubric_feedback=None,
                misconception_codes=(),
                reasoning_quality=None,
                needs_human_review=False,
                validation_error="deterministic_unsupported_for_open_ended",
            )

        if question_type == "mcq":
            if not options:
                return self._rejected_with_error("deterministic_mcq_missing_options")
            normalized_answer = _normalize_text(learner_answer)
            normalized_options = {_normalize_text(opt) for opt in options}
            if normalized_answer not in normalized_options:
                return self._rejected_with_error("mcq_answer_not_in_options")
            normalized_reference = _normalize_text(reference_answer)
            is_correct = normalized_answer == normalized_reference
            return self._graded(
                source="deterministic",
                is_correct=is_correct,
                confidence=1.0,
                rubric_feedback=(
                    "Exact match with a multiple-choice option."
                    if is_correct
                    else "Option selected but does not match reference answer."
                ),
                reasoning_quality="exact_match" if is_correct else "mcq_mismatch",
            )

        # short_answer (default)
        normalized_answer = _normalize_text(learner_answer)
        normalized_reference = _normalize_text(reference_answer)
        if not normalized_reference:
            return self._rejected_with_error("deterministic_empty_reference")
        is_correct = normalized_answer == normalized_reference
        return self._graded(
            source="deterministic",
            is_correct=is_correct,
            confidence=1.0,
            rubric_feedback=(
                "Exact normalized match with reference answer."
                if is_correct
                else "Normalized answer did not match reference."
            ),
            reasoning_quality="exact_match" if is_correct else "no_match",
        )

    # ------------------------------------------------------------------ #
    # LLM path
    # ------------------------------------------------------------------ #
    async def _grade_llm(
        self,
        *,
        question_prompt: str,
        reference_answer: str,
        question_type: str,
        options: tuple[str, ...],
        learner_answer: str,
        source_label: str = "llm",
    ) -> GradingResult:
        try:
            draft: AnswerGradingDraft = await self._llm_provider.generate_answer_grading(
                question_prompt=question_prompt,
                question_type=question_type,
                reference_answer=reference_answer,
                learner_answer=learner_answer,
                options=list(options) if options else None,
            )
        except (ValidationError, ProviderError) as exc:
            return self._needs_review(error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive logging
            _LOGGER.exception("unexpected grading provider failure")
            return self._needs_review(error_message=f"unexpected_provider_failure:{type(exc).__name__}")

        if not draft.response_shape_valid:
            return self._needs_review(error_message="provider_flagged_invalid_shape")

        try:
            self._validate_draft(draft)
        except ValueError as exc:
            return self._needs_review(error_message=str(exc))

        return GradingResult(
            grading_status="graded",
            grading_source=source_label,
            score=draft.score,
            is_correct=draft.is_correct,
            confidence=draft.confidence,
            rubric_feedback=draft.rubric_feedback,
            misconception_codes=tuple(draft.misconception_codes or ()),
            reasoning_quality=draft.reasoning_quality,
            needs_human_review=False,
            validation_error=None,
        )

    # ------------------------------------------------------------------ #
    # Hybrid path
    # ------------------------------------------------------------------ #
    async def _grade_hybrid(
        self,
        *,
        question_prompt: str,
        reference_answer: str,
        question_type: str,
        options: tuple[str, ...],
        learner_answer: str,
    ) -> GradingResult:
        deterministic = self._grade_deterministic(
            question_prompt=question_prompt,
            reference_answer=reference_answer,
            question_type=question_type,
            options=options,
            learner_answer=learner_answer,
        )
        if deterministic.grading_status == "graded":
            return GradingResult(
                grading_status="graded",
                grading_source="hybrid",
                score=deterministic.score,
                is_correct=deterministic.is_correct,
                confidence=deterministic.confidence,
                rubric_feedback=deterministic.rubric_feedback,
                misconception_codes=deterministic.misconception_codes,
                reasoning_quality=deterministic.reasoning_quality,
                needs_human_review=False,
                validation_error=None,
            )
        return await self._grade_llm(
            question_prompt=question_prompt,
            reference_answer=reference_answer,
            question_type=question_type,
            options=options,
            learner_answer=learner_answer,
            source_label="hybrid",
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_draft(draft: AnswerGradingDraft) -> None:
        if not 0.0 <= draft.score <= 1.0:
            raise ValueError(f"Grading score {draft.score} out of range 0.0-1.0.")
        if not 0.0 <= draft.confidence <= 1.0:
            raise ValueError(f"Grading confidence {draft.confidence} out of range 0.0-1.0.")
        if not isinstance(draft.misconception_codes, list) or not all(
            isinstance(code, str) for code in draft.misconception_codes
        ):
            raise ValueError("Grading misconception_codes must be list[str].")

    @staticmethod
    def _graded(
        *,
        source: str,
        is_correct: bool,
        confidence: float,
        rubric_feedback: str,
        reasoning_quality: str,
    ) -> GradingResult:
        return GradingResult(
            grading_status="graded",
            grading_source=source,
            score=1.0 if is_correct else 0.0,
            is_correct=is_correct,
            confidence=confidence,
            rubric_feedback=rubric_feedback,
            misconception_codes=(),
            reasoning_quality=reasoning_quality,
            needs_human_review=False,
            validation_error=None,
        )

    @staticmethod
    def _rejected_with_error(error_code: str) -> GradingResult:
        return GradingResult(
            grading_status="rejected",
            grading_source=None,
            score=None,
            is_correct=None,
            confidence=None,
            rubric_feedback=None,
            misconception_codes=(),
            reasoning_quality=None,
            needs_human_review=False,
            validation_error=error_code,
        )

    @staticmethod
    def _needs_review(*, error_message: str) -> GradingResult:
        return GradingResult(
            grading_status="needs_review",
            grading_source=None,
            score=None,
            is_correct=None,
            confidence=None,
            rubric_feedback=None,
            misconception_codes=(),
            reasoning_quality=None,
            needs_human_review=True,
            validation_error=error_message,
        )
