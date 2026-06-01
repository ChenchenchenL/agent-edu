from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from agent_core.domain.schemas.session import AssistantPayload
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.schemas.quiz import QuizQuestion


@dataclass(frozen=True)
class HintContext:
    hint_level: str
    question_prompt: str | None
    learner_answer: str | None
    reference_answer: str | None
    prior_hint_count: int
    mistake_analysis: list[str]


@dataclass(frozen=True)
class TutorReply:
    content: str
    payload: AssistantPayload
    provider: str
    model: str
    latency_ms: int
    retry_count: int
    response_shape_valid: bool


@dataclass(frozen=True)
class QuizDraft:
    topic: str
    difficulty: str
    questions: list[QuizQuestion]
    provider: str
    model: str
    latency_ms: int
    retry_count: int
    response_shape_valid: bool


@dataclass(frozen=True)
class StudyPlanStageDraft:
    title: str
    objective: str
    focus_topics: list[str]


@dataclass(frozen=True)
class StudyPlanTaskDraft:
    stage_position: int
    scheduled_for: date
    due_on: date
    task_type: str
    execution_mode: str
    title: str
    instructions: str
    topic_focus: str
    difficulty: str | None
    question_count: int | None
    estimated_minutes: int


@dataclass(frozen=True)
class StudyPlanDraft:
    plan_summary: str
    stages: list[StudyPlanStageDraft]
    tasks: list[StudyPlanTaskDraft]
    provider: str
    model: str
    latency_ms: int
    retry_count: int
    response_shape_valid: bool
    fallback_used: bool = False


@dataclass(frozen=True)
class ReflectionSummaryDraft:
    summary: str
    evidence_summary: str
    recommended_next_step: str
    provider: str
    model: str
    latency_ms: int
    retry_count: int
    response_shape_valid: bool


@dataclass(frozen=True)
class SessionLearnerProfile:
    current_topic: str
    response_preference: str
    recent_struggles: list[str]
    known_context: list[str]
    long_term_context: list[str]
    teaching_goal: str
    skill_directives: list[str]


class LLMProvider(Protocol):
    async def generate_tutor_reply(
        self,
        *,
        session_title: str | None,
        subject: str | None,
        learner_message: str,
        mode: str | None,
        history: list[SessionMessage],
        memory_contexts: list[str],
        learner_profile: SessionLearnerProfile,
        hint_context: HintContext | None = None,
    ) -> TutorReply:
        ...

    async def generate_quiz_draft(
        self,
        *,
        topic: str,
        difficulty: str,
        question_count: int,
        skill_directives: list[str] | None = None,
        feedback_style: str | None = None,
    ) -> QuizDraft:
        ...

    async def generate_study_plan_draft(
        self,
        *,
        subject: str,
        target_outcome: str,
        baseline_note: str | None,
        weekly_study_minutes: int,
        stage_blueprint: list[dict[str, object]],
        task_blueprint: list[dict[str, object]],
        strategy_summary: dict[str, object] | None = None,
        skill_directives: list[str] | None = None,
    ) -> StudyPlanDraft:
        ...

    async def generate_reflection_summary(
        self,
        *,
        scope: str,
        trigger_source: str,
        primary_root_cause: str,
        severity: str,
        verdict_payload: dict[str, object],
        evidence_payload: dict[str, object],
        proposed_actions: list[dict[str, object]],
    ) -> ReflectionSummaryDraft:
        ...
