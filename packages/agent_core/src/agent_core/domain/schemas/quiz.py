from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GenerateQuizRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    difficulty: str = Field(default="medium")
    question_count: int = Field(default=3, ge=1, le=10)
    session_id: str | None = None


class QuizQuestion(BaseModel):
    prompt: str
    answer: str


class QuizDraftResponse(BaseModel):
    quiz_id: str
    session_id: str
    topic: str
    difficulty: str
    question_count: int
    questions: list[QuizQuestion]
    skill_trace: list[str]
    created_at: datetime


class QuizSummaryResponse(BaseModel):
    quiz_id: str
    session_id: str
    topic: str
    difficulty: str
    question_count: int
    skill_trace: list[str]
    created_at: datetime


class QuizDetailResponse(BaseModel):
    quiz_id: str
    session_id: str
    topic: str
    difficulty: str
    question_count: int
    questions: list[QuizQuestion]
    skill_trace: list[str]
    created_at: datetime
