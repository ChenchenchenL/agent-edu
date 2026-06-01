from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ExplanationPayload(BaseModel):
    type: Literal["explanation"] = "explanation"
    definition: str = Field(min_length=1)
    core_principles: list[str] = Field(min_length=1)
    worked_example: str = Field(min_length=1)
    common_mistake: str = Field(min_length=1)
    next_step: str = Field(min_length=1)


class HintPayload(BaseModel):
    type: Literal["hint"] = "hint"
    hint_level: Literal["conceptual", "scaffolded", "targeted"]
    next_step_hint: str = Field(min_length=1)
    key_principle: str = Field(min_length=1)
    pitfall: str = Field(min_length=1)
    encouragement: str = Field(min_length=1)
    direct_answer_given: bool = False


AssistantPayload = ExplanationPayload | HintPayload


class MessageTurnMetrics(BaseModel):
    history_count: int
    memory_context_count: int
    cross_session_context_count: int
    hint_level: Literal["conceptual", "scaffolded", "targeted"] | None = None
    hint_history_count: int = 0
    used_quiz_context: bool = False
    used_error_analysis: bool = False
    retrieval_latency_ms: int
    llm_latency_ms: int
    llm_retry_count: int
    response_shape_valid: bool


class CreateSessionRequest(BaseModel):
    learner_profile_id: str | None = Field(default=None, max_length=36)
    learner_goal_id: str | None = Field(default=None, max_length=36)
    title: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=255)


class SessionResponse(BaseModel):
    id: str
    learner_profile_id: str
    learner_goal_id: str | None = None
    daily_task_id: str | None = None
    title: str | None
    subject: str | None
    status: str
    message_count: int
    last_activity_at: datetime
    summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateSessionStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class MessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    mode: Literal["chat", "hint"] = "chat"
    related_quiz_id: str | None = Field(default=None, max_length=36)
    question_prompt: str | None = Field(default=None, max_length=4000)
    learner_answer: str | None = Field(default=None, max_length=4000)


class MessageResponse(BaseModel):
    session_id: str
    user_message_id: str
    assistant_message_id: str
    assistant_message: str
    assistant_payload: AssistantPayload
    skill_trace: list[str]
    turn_metrics: MessageTurnMetrics


class MessageHistoryItemResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    mode: str | None
    skill_trace: list[str]
    content_payload: AssistantPayload | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageHistoryResponse(BaseModel):
    items: list[MessageHistoryItemResponse]
    total: int
    next_before_id: str | None
