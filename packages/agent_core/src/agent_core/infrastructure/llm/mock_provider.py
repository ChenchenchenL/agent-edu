from agent_core.domain.schemas.session import ExplanationPayload, HintPayload
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.schemas.quiz import QuizQuestion
from datetime import date

from agent_core.infrastructure.llm.types import (
    HintContext,
    QuizDraft,
    ReflectionSummaryDraft,
    SessionLearnerProfile,
    StudyPlanDraft,
    StudyPlanStageDraft,
    StudyPlanTaskDraft,
    TutorReply,
)


class MockLLMProvider:
    provider_name = "mock"

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self.model_name = model_name

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
        mode_label = mode or "chat"
        subject_label = subject or session_title or "your current topic"
        history_label = "with prior context" if history else "without prior context"
        memory_label = " and retrieved memory" if memory_contexts else ""
        long_term_label = " and long-term learning context" if learner_profile.long_term_context else ""
        if mode_label == "hint":
            hint_level = hint_context.hint_level if hint_context is not None else "conceptual"
            next_step = (
                f"Check the mismatch in '{hint_context.learner_answer}'."
                if hint_context is not None and hint_context.hint_level == "targeted" and hint_context.learner_answer
                else f"Start from the next step behind '{learner_message}'."
            )
            payload = HintPayload(
                hint_level=hint_level,
                next_step_hint=next_step,
                key_principle=f"Focus on the core rule for {subject_label}.",
                pitfall="Do not jump straight to the final answer.",
                encouragement="You already have enough context to make progress.",
                direct_answer_given=False,
            )
            return TutorReply(
                content=(
                    f"[{self._model_name}] {hint_level} hint for {subject_label}: "
                    f"focus on the next step behind '{learner_message}'. "
                    "Start by identifying the key rule or relationship before solving it."
                ),
                payload=payload,
                provider="mock",
                model=self._model_name,
                latency_ms=0,
                retry_count=0,
                response_shape_valid=True,
            )
        payload = ExplanationPayload(
            definition=f"{subject_label} is the current concept under study.",
            core_principles=[
                f"Link the learner question to the core idea in {subject_label}.",
                f"Use prior context from the session when explaining {subject_label}.",
            ],
            worked_example=f"A simple example for {subject_label} starts from '{learner_message}'.",
            common_mistake="Giving the result without explaining the reasoning.",
            next_step=f"Ask the learner to restate the key idea of {subject_label} in their own words.",
        )
        return TutorReply(
            content=(
                f"[{self._model_name}] Let's work on {subject_label}. "
                f"You asked in {mode_label} mode: {learner_message}. "
                f"Here is a short, structured explanation to move you forward {history_label}{memory_label}{long_term_label}."
            ),
            payload=payload,
            provider="mock",
            model=self._model_name,
            latency_ms=0,
            retry_count=0,
            response_shape_valid=True,
        )

    async def generate_quiz_draft(
        self,
        *,
        topic: str,
        difficulty: str,
        question_count: int,
        skill_directives: list[str] | None = None,
        feedback_style: str | None = None,
    ) -> QuizDraft:
        questions = [
            QuizQuestion(
                prompt=f"Question {index + 1} about {topic} ({difficulty})",
                answer=f"Reference answer {index + 1} for {topic}",
            )
            for index in range(question_count)
        ]
        return QuizDraft(
            topic=topic,
            difficulty=difficulty,
            questions=questions,
            provider="mock",
            model=self._model_name,
            latency_ms=0,
            retry_count=0,
            response_shape_valid=True,
        )

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
        stages = [
            StudyPlanStageDraft(
                title=str(item["title"]),
                objective=f"Build progress toward {target_outcome} through {item['title'].lower()}.",
                focus_topics=[str(topic) for topic in item["focus_topics"]],
            )
            for item in stage_blueprint
        ]
        tasks = [
            StudyPlanTaskDraft(
                stage_position=int(item["stage_position"]),
                scheduled_for=self._ensure_date(item["scheduled_for"]),
                due_on=self._ensure_date(item["due_on"]),
                task_type=str(item["task_type"]),
                execution_mode=str(item["execution_mode"]),
                title=f"{subject} {str(item['task_type']).title()}",
                instructions=f"Work on {item['topic_focus']} for {weekly_study_minutes} minute/week pacing.",
                topic_focus=str(item["topic_focus"]),
                difficulty=str(item["difficulty"]) if item.get("difficulty") is not None else None,
                question_count=int(item["question_count"]) if item.get("question_count") is not None else None,
                estimated_minutes=int(item["estimated_minutes"]),
            )
            for item in task_blueprint
        ]
        return StudyPlanDraft(
            plan_summary=(
                f"[{self._model_name}] Structured study path for {subject} toward {target_outcome}."
                + (
                    f" Strategy: {strategy_summary['primary_instruction_mode']}/{strategy_summary['difficulty_bias']}."
                    if strategy_summary is not None
                    else ""
                )
                + (
                    f" Skills: {', '.join(skill_directives[:2])}."
                    if skill_directives
                    else ""
                )
            ),
            stages=stages,
            tasks=tasks,
            provider="mock",
            model=self._model_name,
            latency_ms=0,
            retry_count=0,
            response_shape_valid=True,
            fallback_used=False,
        )

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
        topic = str(evidence_payload.get("task", {}).get("topic_focus") or evidence_payload.get("topic_key") or "current topic")
        action_labels = ", ".join(str(item.get("action_type")) for item in proposed_actions) or "observe_only"
        verdict_code = str(verdict_payload.get("primary_verdict") or primary_root_cause)
        verdict_confidence = float(verdict_payload.get("verdict_confidence") or 0.0)
        return ReflectionSummaryDraft(
            summary=(
                f"[{self._model_name}] {scope} reflection for {topic}: "
                f"{verdict_code} detected at {severity} severity."
            ),
            evidence_summary=(
                f"Trigger={trigger_source}; topic={topic}; "
                f"verdict_confidence={verdict_confidence:.2f}; "
                f"actions={action_labels}; evidence_keys={', '.join(sorted(evidence_payload.keys()))}."
            ),
            recommended_next_step=f"Proceed with {action_labels} while monitoring {topic}.",
            provider="mock",
            model=self._model_name,
            latency_ms=0,
            retry_count=0,
            response_shape_valid=True,
        )

    @staticmethod
    def _ensure_date(value: object) -> date:
        if isinstance(value, date):
            return value
        raise TypeError("Expected date value in mock study plan blueprint.")
