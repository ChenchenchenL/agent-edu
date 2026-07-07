from datetime import datetime, timezone, timedelta
import pytest

from agent_core.application.services.reflection_trigger_policy import (
    ReflectionTriggerPolicy,
    ReflectionTriggerContext,
    ExistingReflectionSummary,
)


def test_goal_inactive_returns_empty():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="paused",
        existing_reflections=[],
        task_status="failed",
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 0


def test_explicit_trigger():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        explicit_trigger_source="manual_run",
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 1
    assert decisions[0].should_trigger is True
    assert decisions[0].trigger_source == "manual_run"
    assert decisions[0].scope == "goal"


def test_outcome_trigger_single_failure():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        task_id="t1",
        task_status="failed",
        has_consecutive_failures=False,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    # Should trigger task reflection
    assert len(decisions) == 1
    assert decisions[0].should_trigger is True
    assert decisions[0].scope == "task"
    assert decisions[0].trigger_source == "task_failed"


def test_outcome_trigger_consecutive_failures():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        task_id="t1",
        task_status="failed",
        has_consecutive_failures=True,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    # Should trigger both task reflection and consecutive failure goal reflection
    assert len(decisions) == 2
    scopes = {d.scope for d in decisions}
    sources = {d.trigger_source for d in decisions}
    assert scopes == {"task", "goal"}
    assert sources == {"task_failed", "consecutive_failure_pattern"}


def test_outcome_trigger_assessment_completed():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        task_id="t1",
        task_status="completed",
        task_type="assessment",
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    # Should trigger both goal and task scopes
    assert len(decisions) == 2
    scopes = {d.scope for d in decisions}
    sources = {d.trigger_source for d in decisions}
    assert scopes == {"task", "goal"}
    assert sources == {"assessment_completed"}


def test_corpus_review_backlog():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        review_backlog_count=3,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 1
    assert decisions[0].should_trigger is True
    assert decisions[0].scope == "goal"
    assert decisions[0].trigger_source == "corpus_review_threshold"


def test_corpus_backlog_threshold():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        validate_backlog_count=2,
        reinforce_opportunity_count=1,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 1
    assert decisions[0].should_trigger is True
    assert decisions[0].scope == "goal"
    assert decisions[0].trigger_source == "corpus_backlog_threshold"


def test_corpus_contested_memory():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        contested_high_severity_items=[
            {"memory_key": "topic_a", "reflection_priority_score": 0.8},
            {"memory_key": "topic_b", "reflection_priority_score": 0.75},
        ]
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 2
    assert decisions[0].should_trigger is True
    assert decisions[0].scope == "task"
    assert decisions[0].topic_focus == "topic_a"
    assert decisions[1].should_trigger is True
    assert decisions[1].scope == "task"
    assert decisions[1].topic_focus == "topic_b"


def test_runtime_triggers():
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=[],
        fallback_to_baseline_count=3,
        low_confidence_count=4,
        repeated_sequence_mismatch=True,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, datetime.now(timezone.utc))
    assert len(decisions) == 3
    sources = {d.trigger_source for d in decisions}
    assert sources == {
        "fallback_to_baseline_burst",
        "low_confidence_burst",
        "repeated_sequence_mismatch",
    }


def test_cooldown_goal_scope():
    now = datetime.now(timezone.utc)
    existing = [
        ExistingReflectionSummary(
            id="r1",
            scope="goal",
            status="pending",
            cooldown_until=now + timedelta(hours=24),
            topic_focus=None,
            trigger_source="corpus_review_threshold",
            created_at=now,
        )
    ]
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=existing,
        review_backlog_count=3,
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, now)
    assert len(decisions) == 1
    assert decisions[0].should_trigger is False
    assert decisions[0].denial_reason == "goal_cooldown"


def test_cooldown_topic_focus():
    now = datetime.now(timezone.utc)
    existing = [
        ExistingReflectionSummary(
            id="r1",
            scope="task",
            status="completed",
            cooldown_until=now + timedelta(hours=12),
            topic_focus="topic_a",
            trigger_source="corpus_contested_high_priority",
            created_at=now,
        )
    ]
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=existing,
        contested_high_severity_items=[
            {"memory_key": "topic_a", "reflection_priority_score": 0.8},
        ]
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, now)
    assert len(decisions) == 1
    assert decisions[0].should_trigger is False
    assert decisions[0].denial_reason == "topic_cooldown"


def test_cooldown_source_scope():
    now = datetime.now(timezone.utc)
    existing = [
        ExistingReflectionSummary(
            id="r1",
            scope="task",
            status="completed",
            cooldown_until=now + timedelta(hours=12),
            topic_focus=None,
            trigger_source="task_failed",
            created_at=now,
        )
    ]
    context = ReflectionTriggerContext(
        learner_profile_id="p1",
        learner_goal_id="g1",
        goal_phase="active",
        existing_reflections=existing,
        task_id="t1",
        task_status="failed",
    )
    decisions = ReflectionTriggerPolicy.evaluate(context, now)
    assert len(decisions) == 1
    assert decisions[0].should_trigger is True
    assert decisions[0].denial_reason is None
