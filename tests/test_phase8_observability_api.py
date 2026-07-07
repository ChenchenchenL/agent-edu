import pytest
from datetime import datetime, timezone, date
from fastapi.testclient import TestClient
from sqlalchemy import delete

from agent_core.api.app import create_app
from agent_core.api.dependencies import get_session_factory
from agent_core.infrastructure.db.models import (
    LearnerProfileModel,
    LearnerGoalModel,
    LearningSessionModel,
    SessionQuizModel,
    SessionQuizQuestionModel,
    SessionQuizAnswerAttemptModel,
    LearnerTopicMasteryModel,
    AuditEventModel,
    SkillUsageEventModel,
)


@pytest.fixture(autouse=True)
async def cleanup_db(app_client_factory):
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Clean up specific seeded database records by ID (deleting children first)
        await session.execute(delete(SkillUsageEventModel).where(SkillUsageEventModel.id == "use-1"))
        await session.execute(delete(SessionQuizAnswerAttemptModel).where(SessionQuizAnswerAttemptModel.id == "att-1"))
        await session.execute(delete(SessionQuizQuestionModel).where(SessionQuizQuestionModel.id == "q-1"))
        await session.execute(delete(SessionQuizModel).where(SessionQuizModel.id == "quiz-1"))
        await session.execute(delete(LearningSessionModel).where(LearningSessionModel.id == "session-1"))
        await session.execute(delete(LearnerTopicMasteryModel).where(LearnerTopicMasteryModel.id == "m-1"))
        await session.execute(delete(LearnerGoalModel).where(LearnerGoalModel.id == "goal-1"))
        await session.execute(delete(LearnerProfileModel).where(LearnerProfileModel.id == "p-1"))
        await session.execute(delete(AuditEventModel).where(AuditEventModel.id == "aud-1"))
        await session.commit()


def test_learner_endpoints(app_client_factory) -> None:
    api_client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    session_factory = get_session_factory()
    from agent_core.application.services.profile_access import hash_profile_access_key
    import asyncio
    
    # Seed database
    access_key = "test-learner-key-1"
    
    async def seed_db():
        async with session_factory() as db:
            # 1. Seed learner profile with proper access key
            profile = LearnerProfileModel(
                id="p-1",
                access_key_hash=hash_profile_access_key(access_key),
                access_key_created_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(profile)
            await db.flush()

            # 2. Seed learner goal
            goal = LearnerGoalModel(
                id="goal-1",
                learner_profile_id="p-1",
                title="Math",
                subject="Algebra",
                target_outcome="Understand algebra",
                weekly_study_minutes=120,
                deadline_date=date.today(),
                status="active",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(goal)
            await db.flush()

            # 3. Seed learning session
            learning_session = LearningSessionModel(
                id="session-1",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                status="active",
                message_count=0,
                last_activity_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(learning_session)
            await db.flush()

            # 4. Seed quiz
            quiz = SessionQuizModel(
                id="quiz-1",
                session_id="session-1",
                topic="LinearAlgebra",
                difficulty="medium",
                question_count=1,
                skill_trace=[],
                created_at=datetime.now(timezone.utc),
            )
            db.add(quiz)
            await db.flush()

            # 5. Seed question
            question = SessionQuizQuestionModel(
                id="q-1",
                quiz_id="quiz-1",
                position=1,
                prompt="P",
                answer="A",
                question_type="open_ended",
                options=[],
            )
            db.add(question)
            await db.flush()

            # 6. Seed topic mastery
            mastery = LearnerTopicMasteryModel(
                id="m-1",
                learner_goal_id="goal-1",
                topic_key="LinearAlgebra",
                mastery_score=0.6,
                confidence=0.8,
                evidence_count=5,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(mastery)

            # 7. Seed quiz attempts
            attempt1 = SessionQuizAnswerAttemptModel(
                id="att-1",
                session_id="session-1",
                quiz_id="quiz-1",
                question_id="q-1",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                topic_key="LinearAlgebra",
                subskill_keys=[],
                question_prompt="P",
                reference_answer="A",
                learner_answer="My answer",
                grading_status="needs_review",
                grading_source="llm",
                score=0.0,
                is_correct=False,
                confidence=0.9,
                rubric_feedback="None",
                misconception_codes=["mis-1"],
                hint_used=False,
                hint_count=0,
                attempt_number=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(attempt1)

            # 8. Seed audit logs for adaptation rationale
            audit = AuditEventModel(
                id="aud-1",
                event_type="quiz.generated",
                actor="system",
                resource_type="quiz",
                resource_id="quiz-1",
                event_data={"adaptation_rationale": "Overridden difficulty to supportive due to low mastery score."},
                created_at=datetime.now(timezone.utc),
            )
            db.add(audit)

            # 9. Seed skill usage events
            skill_usage = SkillUsageEventModel(
                id="use-1",
                skill_artifact_id=None,
                skill_name="quiz_generator",
                skill_version="0.1.0",
                skill_status_at_use="active",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                session_id="session-1",
                daily_task_id=None,
                workflow_run_id=None,
                surface="chat",
                topic_key="LinearAlgebra",
                trigger_source="manual",
                outcome_status="completed",
                latency_ms=120,
                cost_units=0.02,
                input_summary="I",
                input_fingerprint="IF",
                output_summary="O",
                output_fingerprint="OF",
                error_code=None,
                resolver_status="resolved",
                selection_reason="production_default",
                outcome_signals={"mastery_before": 0.4, "mastery_after": 0.7},
                usage_metadata={},
                created_at=datetime.now(timezone.utc),
            )
            db.add(skill_usage)

            await db.commit()
    
    asyncio.run(seed_db())

    # --- Test Learner API endpoints ---
    learner_headers = {"X-Learner-Key": access_key}

    # Topic Mastery read
    resp = api_client.get("/api/v1/learner/mastery/LinearAlgebra", headers=learner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["topic_key"] == "LinearAlgebra"
    assert data["mastery_score"] == 0.6

    # Quiz attempt history
    resp = api_client.get("/api/v1/quizzes/attempts/history", headers=learner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["attempts"]) == 1
    assert data["attempts"][0]["id"] == "att-1"

    # Next recommended action
    resp = api_client.get("/api/v1/quizzes/next-action", headers=learner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "recommended_next_action" in data
    assert data["recommended_next_action"] == "review_scheduling"

    # Adaptation rationale
    resp = api_client.get("/api/v1/quizzes/rationale/quiz-1", headers=learner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "adaptation_rationale" in data
    assert "Overridden difficulty" in data["adaptation_rationale"]


def test_operator_endpoints(app_client_factory) -> None:
    api_client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    session_factory = get_session_factory()
    import asyncio
    
    async def seed_db():
        async with session_factory() as db:
            # Seed parent models
            profile = LearnerProfileModel(
                id="p-1",
                access_key_hash="hash-1",
                access_key_created_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(profile)
            await db.flush()

            goal = LearnerGoalModel(
                id="goal-1",
                learner_profile_id="p-1",
                title="Math",
                subject="Algebra",
                target_outcome="Understand algebra",
                weekly_study_minutes=120,
                deadline_date=date.today(),
                status="active",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(goal)
            await db.flush()

            learning_session = LearningSessionModel(
                id="session-1",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                status="active",
                message_count=0,
                last_activity_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(learning_session)
            await db.flush()

            quiz = SessionQuizModel(
                id="quiz-1",
                session_id="session-1",
                topic="LinearAlgebra",
                difficulty="medium",
                question_count=1,
                skill_trace=[],
                created_at=datetime.now(timezone.utc),
            )
            db.add(quiz)
            await db.flush()

            question = SessionQuizQuestionModel(
                id="q-1",
                quiz_id="quiz-1",
                position=1,
                prompt="P",
                answer="A",
                question_type="open_ended",
                options=[],
            )
            db.add(question)
            await db.flush()

            # Seed attempts
            attempt1 = SessionQuizAnswerAttemptModel(
                id="att-1",
                session_id="session-1",
                quiz_id="quiz-1",
                question_id="q-1",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                topic_key="LinearAlgebra",
                subskill_keys=[],
                question_prompt="P",
                reference_answer="A",
                learner_answer="My answer",
                grading_status="needs_review",
                grading_source="llm",
                score=0.0,
                is_correct=False,
                confidence=0.9,
                rubric_feedback="None",
                misconception_codes=["mis-1", "mis-2"],
                hint_used=False,
                hint_count=0,
                attempt_number=1,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(attempt1)

            # Seed audit event
            audit = AuditEventModel(
                id="aud-1",
                event_type="quiz.adaptive_policy.applied",
                actor="system",
                resource_type="quiz",
                resource_id="quiz-1",
                event_data={"rationale": "Applied remedial policy due to low mastery score."},
                created_at=datetime.now(timezone.utc),
            )
            db.add(audit)

            # Seed skill usage
            skill_usage = SkillUsageEventModel(
                id="use-1",
                skill_artifact_id=None,
                skill_name="quiz_generator",
                skill_version="0.1.0",
                skill_status_at_use="active",
                learner_profile_id="p-1",
                learner_goal_id="goal-1",
                session_id="session-1",
                daily_task_id=None,
                workflow_run_id=None,
                surface="chat",
                topic_key="LinearAlgebra",
                trigger_source="manual",
                outcome_status="completed",
                latency_ms=120,
                cost_units=0.02,
                input_summary="I",
                input_fingerprint="IF",
                output_summary="O",
                output_fingerprint="OF",
                error_code=None,
                resolver_status="resolved",
                selection_reason="production_default",
                outcome_signals={"mastery_before": 0.4, "mastery_after": 0.7},
                usage_metadata={},
                created_at=datetime.now(timezone.utc),
            )
            db.add(skill_usage)

            await db.commit()
    
    asyncio.run(seed_db())

    # --- Test Operator API endpoints ---
    operator_headers = {"X-Operator-Key": "secret-operator"}

    # Answer attempt browse
    resp = api_client.get("/api/v1/operator/quizzes/attempts", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_count"] == 1
    assert data["attempts"][0]["id"] == "att-1"

    # Grading needs_review queue
    resp = api_client.get("/api/v1/operator/quizzes/grading/needs-review", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["queue"]) == 1
    assert data["queue"][0]["id"] == "att-1"

    # Misconception trend
    resp = api_client.get("/api/v1/operator/quizzes/misconceptions/trend", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    trends = {item["misconception_code"]: item["count"] for item in data["trends"]}
    assert trends.get("mis-1") == 1
    assert trends.get("mis-2") == 1

    # Adaptive policy audit trail
    resp = api_client.get("/api/v1/operator/quizzes/adaptive-policy/audit", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["audit_trail"]) == 1
    assert data["audit_trail"][0]["event_type"] == "quiz.adaptive_policy.applied"

    # Skill learning gain dashboard
    resp = api_client.get("/api/v1/operator/skills/learning-gain", headers=operator_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["learning_gains"]) == 1
    assert data["learning_gains"][0]["skill_name"] == "quiz_generator"
    assert data["learning_gains"][0]["average_learning_gain"] == pytest.approx(0.3)


def test_unauthenticated_request_returns_401(app_client_factory) -> None:
    """Test that unauthenticated requests to Phase 8 endpoints return 401."""
    api_client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    
    # Learner-facing endpoints
    resp = api_client.get("/api/v1/quizzes/attempts/history")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/learner/mastery/LinearAlgebra")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/quizzes/next-action")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/quizzes/rationale/quiz-1")
    assert resp.status_code == 401
    
    # Operator-facing endpoints
    resp = api_client.get("/api/v1/operator/quizzes/attempts")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/operator/quizzes/grading/needs-review")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/operator/quizzes/misconceptions/trend")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/operator/quizzes/adaptive-policy/audit")
    assert resp.status_code == 401
    
    resp = api_client.get("/api/v1/operator/skills/learning-gain")
    assert resp.status_code == 401


def test_learner_cannot_access_operator_endpoints(app_client_factory) -> None:
    """Test that learner credentials cannot access operator endpoints."""
    api_client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    
    # First, create a learner profile with access key
    session_factory = get_session_factory()
    import asyncio
    asyncio.run(_create_learner_profile_with_key(session_factory, "p-test", "test-learner-key"))
    
    learner_headers = {"X-Learner-Key": "test-learner-key"}
    
    # Try to access operator endpoints with learner credentials
    resp = api_client.get("/api/v1/operator/quizzes/attempts", headers=learner_headers)
    assert resp.status_code == 403
    assert "Operator access required" in resp.json()["detail"]
    
    resp = api_client.get("/api/v1/operator/quizzes/grading/needs-review", headers=learner_headers)
    assert resp.status_code == 403
    
    resp = api_client.get("/api/v1/operator/quizzes/misconceptions/trend", headers=learner_headers)
    assert resp.status_code == 403
    
    resp = api_client.get("/api/v1/operator/quizzes/adaptive-policy/audit", headers=learner_headers)
    assert resp.status_code == 403
    
    resp = api_client.get("/api/v1/operator/skills/learning-gain", headers=learner_headers)
    assert resp.status_code == 403


def test_operator_cannot_access_learner_endpoints(app_client_factory) -> None:
    """Test that operator credentials cannot access learner endpoints."""
    api_client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    operator_headers = {"X-Operator-Key": "secret-operator"}
    
    # Try to access learner endpoints with operator credentials
    resp = api_client.get("/api/v1/quizzes/attempts/history", headers=operator_headers)
    assert resp.status_code == 403
    assert "Learner access required" in resp.json()["detail"]
    
    resp = api_client.get("/api/v1/learner/mastery/LinearAlgebra", headers=operator_headers)
    assert resp.status_code == 403
    
    resp = api_client.get("/api/v1/quizzes/next-action", headers=operator_headers)
    assert resp.status_code == 403
    
    resp = api_client.get("/api/v1/quizzes/rationale/quiz-1", headers=operator_headers)
    assert resp.status_code == 403


async def _create_learner_profile_with_key(session_factory, profile_id: str, access_key: str):
    """Helper function to create a learner profile with access key."""
    from agent_core.infrastructure.db.models import LearnerProfileModel
    from agent_core.application.services.profile_access import hash_profile_access_key
    
    async with session_factory() as session:
        # Clean up if exists
        await session.execute(delete(LearnerProfileModel).where(LearnerProfileModel.id == profile_id))
        await session.commit()
        
        # Create new profile
        profile = LearnerProfileModel(
            id=profile_id,
            access_key_hash=hash_profile_access_key(access_key),
            access_key_created_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(profile)
        await session.commit()
