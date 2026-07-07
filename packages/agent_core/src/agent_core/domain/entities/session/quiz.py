from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.domain.schemas.quiz import QuizQuestion


QUESTION_TYPES = frozenset({"short_answer", "open_ended", "mcq"})
DEFAULT_QUESTION_TYPE = "open_ended"

ANSWER_ATTEMPT_GRADING_STATUSES = frozenset({"graded", "rejected", "needs_review"})
ANSWER_ATTEMPT_GRADING_SOURCES = frozenset({"deterministic", "llm", "hybrid"})
RECOMMENDED_NEXT_ACTIONS = frozenset(
    {
        "continue",
        "review",
        "request_hint",
        "easier_question",
        "assessment_ready",
        "request_review",
    }
)


@dataclass(frozen=True)
class SessionQuiz:
    id: str
    session_id: str
    topic: str
    difficulty: str
    question_count: int
    skill_trace: list[str]
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        topic: str,
        difficulty: str,
        question_count: int,
        skill_trace: list[str],
    ) -> "SessionQuiz":
        return cls(
            id=str(uuid4()),
            session_id=session_id,
            topic=topic,
            difficulty=difficulty,
            question_count=question_count,
            skill_trace=skill_trace,
            created_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class SessionQuizQuestion:
    id: str
    quiz_id: str
    position: int
    prompt: str
    answer: str
    question_type: str = DEFAULT_QUESTION_TYPE
    options: tuple[str, ...] = ()

    @classmethod
    def build(
        cls,
        *,
        quiz_id: str,
        position: int,
        prompt: str,
        answer: str,
        question_type: str = DEFAULT_QUESTION_TYPE,
        options: tuple[str, ...] | list[str] | None = None,
    ) -> "SessionQuizQuestion":
        if question_type not in QUESTION_TYPES:
            raise ValueError(
                f"Invalid question_type '{question_type}'. Must be one of: {sorted(QUESTION_TYPES)}"
            )
        normalized_options: tuple[str, ...] = tuple(options) if options else ()
        if question_type == "mcq" and len(normalized_options) < 2:
            raise ValueError("mcq questions require at least 2 options")
        return cls(
            id=str(uuid4()),
            quiz_id=quiz_id,
            position=position,
            prompt=prompt,
            answer=answer,
            question_type=question_type,
            options=normalized_options,
        )


@dataclass(frozen=True)
class StoredSessionQuiz:
    quiz: SessionQuiz
    questions: list[QuizQuestion]


@dataclass(frozen=True)
class SessionQuizAnswerAttempt:
    id: str
    session_id: str
    quiz_id: str
    question_id: str
    learner_profile_id: str
    learner_goal_id: str | None
    daily_task_id: str | None
    topic_key: str
    subskill_keys: tuple[str, ...]
    question_prompt: str
    reference_answer: str
    learner_answer: str
    grading_status: str
    grading_source: str | None
    score: float | None
    is_correct: bool | None
    confidence: float | None
    rubric_feedback: str | None
    misconception_codes: tuple[str, ...]
    hint_used: bool
    hint_count: int
    attempt_number: int
    metadata: dict
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        quiz_id: str,
        question_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        daily_task_id: str | None,
        topic_key: str,
        subskill_keys: tuple[str, ...] | list[str] | None = None,
        question_prompt: str,
        reference_answer: str,
        learner_answer: str,
        grading_status: str,
        grading_source: str | None = None,
        score: float | None = None,
        is_correct: bool | None = None,
        confidence: float | None = None,
        rubric_feedback: str | None = None,
        misconception_codes: tuple[str, ...] | list[str] | None = None,
        hint_used: bool = False,
        hint_count: int = 0,
        attempt_number: int = 1,
        metadata: dict | None = None,
    ) -> "SessionQuizAnswerAttempt":
        if grading_status not in ANSWER_ATTEMPT_GRADING_STATUSES:
            raise ValueError(
                f"Invalid grading_status '{grading_status}'. Must be one of: {sorted(ANSWER_ATTEMPT_GRADING_STATUSES)}"
            )
        if grading_source is not None and grading_source not in ANSWER_ATTEMPT_GRADING_SOURCES:
            raise ValueError(
                f"Invalid grading_source '{grading_source}'. Must be one of: {sorted(ANSWER_ATTEMPT_GRADING_SOURCES)}"
            )
        if score is not None and not 0.0 <= score <= 1.0:
            raise ValueError(f"score must be between 0.0 and 1.0, got {score}")
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {confidence}")
        if hint_count < 0:
            raise ValueError(f"hint_count must be >= 0, got {hint_count}")
        if attempt_number < 1:
            raise ValueError(f"attempt_number must be >= 1, got {attempt_number}")
        if grading_status == "graded" and (score is None or is_correct is None):
            raise ValueError("graded attempts require score and is_correct")
        if grading_status == "graded" and grading_source is None:
            raise ValueError("graded attempts require grading_source")
        if grading_status != "graded" and (score is not None or is_correct is not None):
            raise ValueError("non-graded attempts must not carry score/is_correct")

        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            session_id=session_id,
            quiz_id=quiz_id,
            question_id=question_id,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            topic_key=topic_key,
            subskill_keys=tuple(subskill_keys) if subskill_keys else (),
            question_prompt=question_prompt,
            reference_answer=reference_answer,
            learner_answer=learner_answer,
            grading_status=grading_status,
            grading_source=grading_source,
            score=score,
            is_correct=is_correct,
            confidence=confidence,
            rubric_feedback=rubric_feedback,
            misconception_codes=tuple(misconception_codes) if misconception_codes else (),
            hint_used=hint_used,
            hint_count=hint_count,
            attempt_number=attempt_number,
            metadata=dict(metadata) if metadata else {},
            created_at=now,
            updated_at=now,
        )
