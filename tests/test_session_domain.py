from agent_core.domain.entities.session import LearningSession


def test_learning_session_defaults():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")

    assert session.status == "active"
    assert session.learner_goal_id is None
    assert session.daily_task_id is None
    assert session.message_count == 0
    assert session.summary is None
    assert session.last_activity_at == session.created_at


def test_learning_session_status_transition_updates_timestamp():
    session = LearningSession.build(learner_profile_id="profile-1", title="Calculus", subject="Limits")
    updated = session.with_status("completed")

    assert updated.status == "completed"
    assert updated.id == session.id
    assert updated.updated_at >= session.updated_at
    assert updated.last_activity_at == session.last_activity_at
