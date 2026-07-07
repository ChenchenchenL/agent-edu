from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ExistingReflectionSummary:
    id: str
    scope: str
    status: str
    cooldown_until: datetime | None
    topic_focus: str | None
    trigger_source: str
    created_at: datetime


@dataclass(frozen=True)
class ReflectionTriggerContext:
    learner_profile_id: str
    learner_goal_id: str
    goal_phase: str  # e.g., "active"
    existing_reflections: list[ExistingReflectionSummary]
    scope: str | None = None

    # Task outcome (optional, populated for task outcome updates)
    task_id: str | None = None
    task_status: str | None = None
    task_type: str | None = None
    topic_focus: str | None = None
    workflow_run_id: str | None = None
    study_plan_id: str | None = None
    has_consecutive_failures: bool = False

    # Memory signals (optional)
    contested_high_severity_items: list[dict[str, Any]] = field(default_factory=list)
    validate_backlog_count: int = 0
    review_backlog_count: int = 0
    reinforce_opportunity_count: int = 0

    # Runtime signals (optional)
    fallback_to_baseline_count: int = 0
    low_confidence_count: int = 0
    repeated_sequence_mismatch: bool = False

    # Custom override source
    explicit_trigger_source: str | None = None

    # Answer attempt signals (optional)
    consecutive_wrong_answers: int = 0
    has_repeated_misconception: bool = False
    has_low_mastery_high_difficulty_mismatch: bool = False
    has_hint_dependency_failure: bool = False
    high_failure_rate_artifact: bool = False
    has_assessment_regression_from_quiz: bool = False
    has_short_guess_answer: bool = False


@dataclass(frozen=True)
class ReflectionTriggerDecision:
    should_trigger: bool
    scope: str  # "task" or "goal"
    trigger_source: str
    cooldown_key: str | None
    reason_codes: list[str]
    topic_focus: str | None = None
    denial_reason: str | None = None


class ReflectionTriggerPolicy:
    @classmethod
    def evaluate(
        cls,
        context: ReflectionTriggerContext,
        now: datetime,
    ) -> list[ReflectionTriggerDecision]:
        """Evaluate trigger rules and apply cooldown filters to generate decisions."""
        if context.goal_phase != "active":
            return []

        raw_decisions = cls._evaluate_raw_rules(context)
        final_decisions: list[ReflectionTriggerDecision] = []

        for decision in raw_decisions:
            is_outcome_or_explicit = decision.trigger_source in {
                "task_failed",
                "task_skipped",
                "assessment_completed",
                "consecutive_failure_pattern",
            } or (context.explicit_trigger_source is not None)

            denial_reason = None
            if not is_outcome_or_explicit:
                denial_reason = cls._check_cooldown_and_dedupe(decision, context.existing_reflections, now)

            if denial_reason:
                final_decisions.append(
                    ReflectionTriggerDecision(
                        should_trigger=False,
                        scope=decision.scope,
                        trigger_source=decision.trigger_source,
                        cooldown_key=decision.cooldown_key,
                        reason_codes=decision.reason_codes,
                        topic_focus=decision.topic_focus,
                        denial_reason=denial_reason,
                    )
                )
            else:
                final_decisions.append(decision)

        return final_decisions

    @classmethod
    def _evaluate_raw_rules(cls, context: ReflectionTriggerContext) -> list[ReflectionTriggerDecision]:
        decisions: list[ReflectionTriggerDecision] = []

        # 1. Explicit triggers (from manual/workflow coordinator bypasses)
        if context.explicit_trigger_source:
            scope = context.scope or ("task" if context.task_id is not None else "goal")
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope=scope,
                    trigger_source=context.explicit_trigger_source,
                    cooldown_key=f"explicit:{context.learner_goal_id}:{context.explicit_trigger_source}",
                    reason_codes=["explicit_trigger"],
                    topic_focus=context.topic_focus,
                )
            )
            return decisions

        # 2. Outcome-triggered rules
        if context.task_status in {"failed", "skipped"}:
            if context.has_consecutive_failures:
                decisions.append(
                    ReflectionTriggerDecision(
                        should_trigger=True,
                        scope="goal",
                        trigger_source="consecutive_failure_pattern",
                        cooldown_key=f"goal:{context.learner_goal_id}:consecutive_failure_pattern",
                        reason_codes=["consecutive_failures"],
                        topic_focus=context.topic_focus,
                    )
                )
            # Failures also trigger a task-level reflection
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="task_failed" if context.task_status == "failed" else "task_skipped",
                    cooldown_key=f"task:{context.task_id}:outcome_failure",
                    reason_codes=["task_outcome_failure"],
                    topic_focus=context.topic_focus,
                )
            )

        elif context.task_status == "completed" and context.task_type == "assessment":
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="assessment_completed",
                    cooldown_key=f"task:{context.task_id}:assessment_completed",
                    reason_codes=["assessment_completed_task"],
                    topic_focus=context.topic_focus,
                )
            )
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="assessment_completed",
                    cooldown_key=f"goal:{context.learner_goal_id}:assessment_completed",
                    reason_codes=["assessment_completed_goal"],
                    topic_focus=context.topic_focus,
                )
            )

        # 3. Corpus-triggered rules (proactive)
        goal_triggered = False
        if context.review_backlog_count >= 3:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="corpus_review_threshold",
                    cooldown_key=f"goal:{context.learner_goal_id}:corpus_review_threshold",
                    reason_codes=["review_backlog_high"],
                )
            )
            goal_triggered = True

        if not goal_triggered and (context.validate_backlog_count + context.reinforce_opportunity_count >= 3):
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="corpus_backlog_threshold",
                    cooldown_key=f"goal:{context.learner_goal_id}:corpus_backlog_threshold",
                    reason_codes=["backlog_high"],
                )
            )

        # Contested memory items: sort to avoid spamming more than 3
        contested_items = sorted(
            context.contested_high_severity_items,
            key=lambda x: x.get("reflection_priority_score", 0.0),
            reverse=True,
        )
        for item in contested_items[:3]:
            topic_key = item.get("memory_key")
            if topic_key:
                decisions.append(
                    ReflectionTriggerDecision(
                        should_trigger=True,
                        scope="task",
                        trigger_source="corpus_contested_high_priority",
                        cooldown_key=f"task:{context.learner_goal_id}:contested:{topic_key}",
                        reason_codes=["contested_memory_high_priority"],
                        topic_focus=topic_key,
                    )
                )

        # 4. Runtime-governance-triggered rules
        if context.fallback_to_baseline_count >= 3:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="fallback_to_baseline_burst",
                    cooldown_key=f"goal:{context.learner_goal_id}:fallback_to_baseline_burst",
                    reason_codes=["fallback_burst"],
                )
            )

        if context.low_confidence_count >= 3:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="low_confidence_burst",
                    cooldown_key=f"goal:{context.learner_goal_id}:low_confidence_burst",
                    reason_codes=["low_confidence_burst"],
                )
            )

        if context.repeated_sequence_mismatch:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="repeated_sequence_mismatch",
                    cooldown_key=f"goal:{context.learner_goal_id}:repeated_sequence_mismatch",
                    reason_codes=["sequence_mismatch_repeated"],
                )
            )

        # 5. Answer attempt trigger rules
        if context.consecutive_wrong_answers >= 3:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="consecutive_wrong_answers",
                    cooldown_key=f"task:{context.learner_goal_id}:consecutive_wrong_answers:{context.topic_focus or ''}",
                    reason_codes=["consecutive_wrong_answers"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.has_repeated_misconception:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="repeated_misconception",
                    cooldown_key=f"task:{context.learner_goal_id}:repeated_misconception:{context.topic_focus or ''}",
                    reason_codes=["repeated_misconception_pattern"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.has_low_mastery_high_difficulty_mismatch:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="low_mastery_high_difficulty_mismatch",
                    cooldown_key=f"goal:{context.learner_goal_id}:low_mastery_high_difficulty_mismatch",
                    reason_codes=["mastery_difficulty_mismatch"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.has_hint_dependency_failure:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="hint_dependency_failure",
                    cooldown_key=f"task:{context.learner_goal_id}:hint_dependency_failure:{context.topic_focus or ''}",
                    reason_codes=["hint_dependency_failure"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.high_failure_rate_artifact:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="high_failure_rate_artifact",
                    cooldown_key=f"goal:{context.learner_goal_id}:high_failure_rate_artifact",
                    reason_codes=["high_failure_rate_artifact"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.has_assessment_regression_from_quiz:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="goal",
                    trigger_source="assessment_regression_from_quiz",
                    cooldown_key=f"goal:{context.learner_goal_id}:assessment_regression_from_quiz:{context.topic_focus or ''}",
                    reason_codes=["assessment_regression_from_quiz"],
                    topic_focus=context.topic_focus,
                )
            )

        if context.has_short_guess_answer:
            decisions.append(
                ReflectionTriggerDecision(
                    should_trigger=True,
                    scope="task",
                    trigger_source="short_guess_answer",
                    cooldown_key=f"task:{context.learner_goal_id}:short_guess_answer:{context.topic_focus or ''}",
                    reason_codes=["short_guess_answer_pattern"],
                    topic_focus=context.topic_focus,
                )
            )

        return decisions

    @classmethod
    def _check_cooldown_and_dedupe(
        cls,
        decision: ReflectionTriggerDecision,
        existing_reflections: list[ExistingReflectionSummary],
        now: datetime,
    ) -> str | None:
        """Check if a decision is blocked by any active/cooldown reflections."""
        active_statuses = {"pending", "processing", "review_requested"}

        def is_future(dt: datetime | None) -> bool:
            if dt is None:
                return False
            from datetime import timezone
            if dt.tzinfo is None and now.tzinfo is not None:
                return dt.replace(tzinfo=timezone.utc) > now
            if dt.tzinfo is not None and now.tzinfo is None:
                return dt > now.replace(tzinfo=timezone.utc)
            return dt > now

        # Goal Cooldown: block any goal-scope reflection if an active/cooldown goal-scope reflection exists
        if decision.scope == "goal":
            for rec in existing_reflections:
                if rec.scope == "goal":
                    is_active = rec.status in active_statuses
                    is_cooldown = is_future(rec.cooldown_until)
                    if is_active or is_cooldown:
                        return "goal_cooldown"

        # Topic Cooldown: block any topic-specific reflection if same topic focus is active/cooldown
        if decision.topic_focus:
            for rec in existing_reflections:
                if rec.topic_focus == decision.topic_focus:
                    is_active = rec.status in active_statuses
                    is_cooldown = is_future(rec.cooldown_until)
                    if is_active or is_cooldown:
                        return "topic_cooldown"

        # Source Cooldown: block if the same source was triggered very recently
        for rec in existing_reflections:
            if rec.trigger_source == decision.trigger_source and rec.scope == decision.scope:
                is_active = rec.status in active_statuses
                is_cooldown = is_future(rec.cooldown_until)
                if is_active or is_cooldown:
                    return "source_cooldown"

        return None
