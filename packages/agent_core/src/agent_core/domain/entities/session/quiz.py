from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from agent_core.domain.schemas.quiz import QuizQuestion


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

    @classmethod
    def build(
        cls,
        *,
        quiz_id: str,
        position: int,
        prompt: str,
        answer: str,
    ) -> "SessionQuizQuestion":
        return cls(
            id=str(uuid4()),
            quiz_id=quiz_id,
            position=position,
            prompt=prompt,
            answer=answer,
        )


@dataclass(frozen=True)
class StoredSessionQuiz:
    quiz: SessionQuiz
    questions: list[QuizQuestion]
