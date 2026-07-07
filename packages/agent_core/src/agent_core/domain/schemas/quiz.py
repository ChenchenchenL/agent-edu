from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GenerateQuizRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=255)
    difficulty: str = Field(default="medium")
    question_count: int = Field(default=3, ge=1, le=10)
    session_id: str | None = None


class QuizQuestion(BaseModel):
    id: str | None = None
    prompt: str
    answer: str
    question_type: str = Field(default="open_ended")
    options: list[str] = Field(default_factory=list)


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


class SubmitAnswerAttemptRequest(BaseModel):
    learner_answer: str = Field(min_length=1, max_length=4000)
    hint_used: bool = False
    hint_count: int = Field(default=0, ge=0, le=20)
    client_context: dict[str, Any] | None = None
    grading_strategy: str = Field(
        default="hybrid", pattern="^(deterministic|llm|hybrid)$"
    )


class GradingFeedback(BaseModel):
    grading_status: str
    grading_source: str | None
    score: float | None
    is_correct: bool | None
    confidence: float | None
    rubric_feedback: str | None
    misconception_codes: list[str]
    needs_human_review: bool


class MasterySnapshotResponse(BaseModel):
    topic_key: str
    mastery_score: float
    confidence: float
    evidence_count: int
    last_attempt_status: str | None
    last_assessed_at: datetime | None


class AnswerAttemptResponse(BaseModel):
    attempt_id: str
    session_id: str
    quiz_id: str
    question_id: str
    attempt_number: int
    grading: GradingFeedback
    mastery_snapshot: MasterySnapshotResponse | None
    recommended_next_action: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Phase 8 Observability schemas (learner-facing + operator-facing)
# ---------------------------------------------------------------------------


class ObservabilityAttemptRecord(BaseModel):
    id: str
    session_id: str
    quiz_id: str
    question_id: str
    score: float | None
    is_correct: bool | None
    misconception_codes: list[str]
    created_at: datetime


class LearnerQuizAttemptHistoryResponse(BaseModel):
    attempts: list[ObservabilityAttemptRecord]


class TopicMasteryResponse(BaseModel):
    topic_key: str
    mastery_score: float
    confidence: float
    evidence_count: int


class RecommendedNextActionResponse(BaseModel):
    recommended_next_action: str
    rationale: str


class QuizAdaptationRationaleResponse(BaseModel):
    quiz_id: str
    adaptation_rationale: str


class OperatorAttemptBrowseResponse(BaseModel):
    attempts: list[ObservabilityAttemptRecord]
    total_count: int


class OperatorGradingQueueResponse(BaseModel):
    queue: list[ObservabilityAttemptRecord]


class MisconceptionTrendRecord(BaseModel):
    misconception_code: str
    count: int


class MisconceptionTrendResponse(BaseModel):
    trends: list[MisconceptionTrendRecord]


class AdaptivePolicyAuditRecord(BaseModel):
    id: str
    event_type: str
    resource_id: str | None
    event_data: dict[str, Any]
    created_at: datetime


class AdaptivePolicyAuditTrailResponse(BaseModel):
    audit_trail: list[AdaptivePolicyAuditRecord]


class LearningGainRecord(BaseModel):
    skill_name: str
    average_learning_gain: float
    sample_size: int


class LearningGainDashboardResponse(BaseModel):
    learning_gains: list[LearningGainRecord]
