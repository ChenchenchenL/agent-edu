from __future__ import annotations

from datetime import date, timedelta


def _create_profile_with_key(client) -> tuple[str, str]:
    response = client.post("/api/v1/learner-profiles", json={})
    assert response.status_code == 200
    payload = response.json()
    return payload["id"], payload["access_key"]


def _learner_headers(access_key: str) -> dict[str, str]:
    return {"X-Learner-Key": access_key}


def _operator_headers() -> dict[str, str]:
    return {"X-Operator-Key": "secret-operator"}


def test_session_endpoints_cover_create_list_get_update_and_errors(app_client_factory):
    client = app_client_factory()

    first = client.post("/api/v1/sessions", json={"title": "Algebra", "subject": "Equations"})
    assert first.status_code == 200
    first_payload = first.json()

    second = client.post("/api/v1/sessions", json={"title": "Geometry", "subject": "Triangles"})
    assert second.status_code == 200
    second_payload = second.json()

    listed = client.get("/api/v1/sessions")
    assert listed.status_code == 200
    session_ids = {item["id"] for item in listed.json()}
    assert {first_payload["id"], second_payload["id"]}.issubset(session_ids)

    fetched = client.get(f"/api/v1/sessions/{first_payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["subject"] == "Equations"

    updated = client.patch(
        f"/api/v1/sessions/{first_payload['id']}/status",
        json={"status": "archived"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "archived"

    missing = client.get("/api/v1/sessions/missing-session")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    invalid_status = client.patch(
        f"/api/v1/sessions/{first_payload['id']}/status",
        json={"status": "paused"},
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error"]["code"] == "validation_error"


def test_message_endpoints_persist_history_and_validate_errors(app_client_factory):
    client = app_client_factory()
    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    session_id = session_response.json()["id"]

    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["assistant_payload"]["type"] == "explanation"
    assert chat_payload["skill_trace"] == ["explain_concept"]

    hint_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Give me a hint instead.", "mode": "hint"},
    )
    assert hint_response.status_code == 200
    assert hint_response.json()["assistant_payload"]["type"] == "hint"

    history_response = client.get(f"/api/v1/sessions/{session_id}/messages", params={"limit": 2})
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert history_payload["total"] == 4
    assert len(history_payload["items"]) == 2
    assert history_payload["items"][-1]["role"] == "assistant"
    assert history_payload["next_before_id"] is not None

    paged_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"limit": 2, "before_id": history_payload["next_before_id"]},
    )
    assert paged_response.status_code == 200
    assert len(paged_response.json()["items"]) >= 1

    invalid_cursor = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"before_id": "missing-cursor"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "validation_error"

    invalid_mode = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain this.", "mode": "quiz"},
    )
    assert invalid_mode.status_code == 422

    missing_session = client.post(
        "/api/v1/sessions/missing-session/messages",
        json={"content": "Explain this.", "mode": "chat"},
    )
    assert missing_session.status_code == 404


def test_quiz_endpoints_cover_generate_list_detail_and_errors(app_client_factory):
    client = app_client_factory()
    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Probability", "subject": "Distributions"},
    )
    session_id = session_response.json()["id"]

    generated = client.post(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        json={"topic": "Distributions", "difficulty": "easy", "question_count": 2},
    )
    assert generated.status_code == 200
    quiz_payload = generated.json()
    assert quiz_payload["question_count"] == 2
    assert quiz_payload["skill_trace"] == ["create_quiz"]

    listed = client.get(f"/api/v1/sessions/{session_id}/quizzes")
    assert listed.status_code == 200
    assert listed.json()[0]["quiz_id"] == quiz_payload["quiz_id"]

    detail = client.get(f"/api/v1/sessions/{session_id}/quizzes/{quiz_payload['quiz_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["questions"]) == 2

    missing_session = client.get("/api/v1/sessions/missing-session/quizzes")
    assert missing_session.status_code == 404

    missing_quiz = client.get(f"/api/v1/sessions/{session_id}/quizzes/missing-quiz")
    assert missing_quiz.status_code == 404


def test_profile_access_key_api_returns_key_once_and_rotates_operator_only(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_payload = profile.json()
    profile_id = profile_payload["id"]
    access_key = profile_payload["access_key"]
    assert access_key.startswith("edu_prof_")

    listed = client.get("/api/v1/learner-profiles")
    assert listed.status_code == 401

    listed = client.get("/api/v1/learner-profiles", headers=_operator_headers())
    assert listed.status_code == 200
    assert "access_key" not in listed.json()[0]
    assert "access_key_hash" not in listed.json()[0]

    fetched = client.get(f"/api/v1/learner-profiles/{profile_id}")
    assert fetched.status_code == 401

    fetched = client.get(f"/api/v1/learner-profiles/{profile_id}", headers=_learner_headers(access_key))
    assert fetched.status_code == 200
    assert "access_key" not in fetched.json()
    assert "access_key_hash" not in fetched.json()

    own_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
    )
    assert own_workspace.status_code == 200

    learner_rotate = client.post(
        f"/api/v1/learner-profiles/{profile_id}/access-key/rotate",
        headers=_learner_headers(access_key),
    )
    assert learner_rotate.status_code == 403

    rotated = client.post(
        f"/api/v1/learner-profiles/{profile_id}/access-key/rotate",
        headers=_operator_headers(),
    )
    assert rotated.status_code == 200
    rotated_key = rotated.json()["access_key"]
    assert rotated_key != access_key

    old_key_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
    )
    assert old_key_workspace.status_code == 401

    new_key_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(rotated_key),
    )
    assert new_key_workspace.status_code == 200


def test_profile_goal_and_autonomy_routes_require_owner_or_operator(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    other_profile_id, other_access_key = _create_profile_with_key(client)
    headers = _learner_headers(access_key)
    other_headers = _learner_headers(other_access_key)

    missing_profile_goals = client.get(f"/api/v1/learner-profiles/{profile_id}/goals")
    assert missing_profile_goals.status_code == 401

    wrong_profile_goals = client.get(f"/api/v1/learner-profiles/{profile_id}/goals", headers=other_headers)
    assert wrong_profile_goals.status_code == 404

    wrong_create_goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=other_headers,
        json={
            "title": "Should not create",
            "subject": "Linear Algebra",
            "target_outcome": "No access",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert wrong_create_goal.status_code == 404

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve matrix exercises",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    missing_goal = client.get(f"/api/v1/goals/{goal_id}")
    assert missing_goal.status_code == 401

    wrong_goal = client.get(f"/api/v1/goals/{goal_id}", headers=other_headers)
    assert wrong_goal.status_code == 404

    operator_goal = client.get(f"/api/v1/goals/{goal_id}", headers=_operator_headers())
    assert operator_goal.status_code == 200
    assert operator_goal.json()["learner_profile_id"] == profile_id

    plan = client.post(
        f"/api/v1/goals/{goal_id}/plans",
        headers=headers,
        json={"trigger_source": "initial"},
    )
    assert plan.status_code == 200
    plan_id = plan.json()["id"]

    missing_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks")
    assert missing_tasks.status_code == 401

    wrong_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=other_headers)
    assert wrong_tasks.status_code == 404

    operator_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=_operator_headers())
    assert operator_tasks.status_code == 200
    task_id = operator_tasks.json()[0]["id"]

    wrong_plan = client.get(f"/api/v1/plans/{plan_id}", headers=other_headers)
    assert wrong_plan.status_code == 404

    operator_plan = client.get(f"/api/v1/plans/{plan_id}", headers=_operator_headers())
    assert operator_plan.status_code == 200

    wrong_task = client.get(f"/api/v1/tasks/{task_id}", headers=other_headers)
    assert wrong_task.status_code == 404

    operator_task = client.get(f"/api/v1/tasks/{task_id}", headers=_operator_headers())
    assert operator_task.status_code == 200

    wrong_autonomy = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=other_headers)
    assert wrong_autonomy.status_code == 404

    operator_autonomy = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=_operator_headers())
    assert operator_autonomy.status_code == 200
    assert other_profile_id != profile_id


def test_memory_endpoints_are_available(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    other_profile_id, other_access_key = _create_profile_with_key(client)

    knowledge = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert knowledge.status_code == 200
    assert "items" in knowledge.json()

    behavior = client.get(
        "/api/v1/memory/behavior",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "query_text": "I need a hint"},
    )
    assert behavior.status_code == 200
    assert "items" in behavior.json()

    missing_key = client.get(
        "/api/v1/memory/knowledge",
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert missing_key.status_code == 401

    wrong_key = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers("wrong-key"),
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert wrong_key.status_code == 401

    wrong_profile = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": other_profile_id, "query_text": "matrix multiplication"},
    )
    assert wrong_profile.status_code == 404

    own_other_profile = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(other_access_key),
        params={"learner_profile_id": other_profile_id, "query_text": "matrix multiplication"},
    )
    assert own_other_profile.status_code == 200

    corpus = client.get(
        "/api/v1/memory/reflection-corpus",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert corpus.status_code == 200
    assert "items" in corpus.json()
    assert "summary" in corpus.json()

    learner_corpus = client.get(
        "/api/v1/memory/reflection-corpus",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id},
    )
    assert learner_corpus.status_code == 403

    summary = client.get(
        "/api/v1/memory/governance-summary",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert summary.status_code == 200
    assert "knowledge_total" in summary.json()
    assert "behavior_total" in summary.json()

    interpretation = client.get(
        "/api/v1/memory/interpretation",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert interpretation.status_code == 200
    assert "facts" in interpretation.json()
    assert "recommended_constraints" in interpretation.json()

    conflicts = client.get(
        "/api/v1/memory/conflicts",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)


def test_memory_operator_endpoints_cover_detail_suppress_restore_and_annotation(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    session_id = session_response.json()["id"]
    message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "I am confused about matrix multiplication.", "mode": "chat"},
    )
    assert message_response.status_code == 200

    learner_profile_id = client.get(f"/api/v1/sessions/{session_id}").json()["learner_profile_id"]

    unauthorized = client.post(
        "/api/v1/memory/knowledge/missing/suppress",
        json={"reason_code": "manual_block", "note": "bad memory"},
    )
    assert unauthorized.status_code == 403

    from agent_core.api import dependencies as api_dependencies
    from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
    import asyncio

    async def seed_memory_direct() -> str:
        session_factory = api_dependencies.get_session_factory()
        source_message_id = message_response.json()["user_message_id"]
        async with session_factory() as db:
            service = api_dependencies.get_memory_service(db)
            materialization_service = LongTermMemoryMaterializationService(service)
            memory_events = await service.record_learning_memories(
                session_id=session_id,
                learner_profile_id=learner_profile_id,
                learner_message="I am confused about matrix multiplication.",
                assistant_message="Matrix multiplication combines rows and columns.",
                source_message_id=source_message_id,
                mode="chat",
                subject="Matrices",
                session_title="Linear Algebra",
            )
            result = await materialization_service.materialize_from_chat_turn(
                session_id=session_id,
                learner_profile_id=learner_profile_id,
                learner_goal_id=None,
                learner_message="I am confused about matrix multiplication.",
                assistant_message="Matrix multiplication combines rows and columns.",
                source_message_id=source_message_id,
                mode="chat",
                subject="Matrices",
                session_title="Linear Algebra",
                memory_events=memory_events,
                persist_embeddings=True,
            )
            await db.commit()
            return result.knowledge[0].memory.id

    loop = asyncio.new_event_loop()
    try:
        knowledge_id = loop.run_until_complete(seed_memory_direct())
    finally:
        loop.close()

    detail = client.get(f"/api/v1/memory/knowledge/{knowledge_id}", headers=_operator_headers())
    assert detail.status_code == 200
    assert detail.json()["status"] == "candidate"

    rotated = client.post(
        f"/api/v1/learner-profiles/{learner_profile_id}/access-key/rotate",
        headers=_operator_headers(),
    )
    assert rotated.status_code == 200
    learner_detail = client.get(
        f"/api/v1/memory/knowledge/{knowledge_id}",
        headers=_learner_headers(rotated.json()["access_key"]),
    )
    assert learner_detail.status_code == 200
    assert learner_detail.json()["details"] is None
    assert learner_detail.json()["source_event_ids"] == []
    assert learner_detail.json()["source_memory_ids"] == []
    assert learner_detail.json()["provenance_source_id"] is None
    assert learner_detail.json()["scope_ref"] == {}
    assert learner_detail.json()["promotion_rationale"] is None

    other_profile_id, other_access_key = _create_profile_with_key(client)
    other_detail = client.get(
        f"/api/v1/memory/knowledge/{knowledge_id}",
        headers=_learner_headers(other_access_key),
    )
    assert other_profile_id != learner_profile_id
    assert other_detail.status_code == 404

    suppressed = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/suppress",
        headers=_operator_headers(),
        json={"reason_code": "manual_block", "note": "Needs review"},
    )
    assert suppressed.status_code == 200
    assert suppressed.json()["status"] == "suppressed"

    annotation = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/annotate",
        headers=_operator_headers(),
        json={"annotation_code": "promotion_blocker", "note": "Reviewed by operator"},
    )
    assert annotation.status_code == 200
    assert annotation.json()["annotation_code"] == "promotion_blocker"

    annotations = client.get(f"/api/v1/memory/knowledge/{knowledge_id}/annotations", headers=_operator_headers())
    assert annotations.status_code == 200
    assert len(annotations.json()) == 1

    restored = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/restore",
        headers=_operator_headers(),
        json={"restore_to_status": "active", "reason": "Approved"},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_reflection_endpoints_cover_goal_task_and_detail(app_client_factory):
    client = app_client_factory()

    profile_response = client.post("/api/v1/learner-profiles", json={})
    assert profile_response.status_code == 200
    profile_id = profile_response.json()["id"]
    access_key = profile_response.json()["access_key"]
    headers = _learner_headers(access_key)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    plan_response = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert plan_response.status_code == 200

    tasks_response = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_response.status_code == 200
    task_id = tasks_response.json()[0]["id"]

    execute_response = client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
    assert execute_response.status_code == 200

    failed_response = client.patch(
        f"/api/v1/tasks/{task_id}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Still confused"},
    )
    assert failed_response.status_code == 200

    goal_reflections = client.get(f"/api/v1/goals/{goal_id}/reflections", headers=headers)
    assert goal_reflections.status_code == 200
    assert goal_reflections.json()["total"] >= 1

    task_reflections = client.get(f"/api/v1/tasks/{task_id}/reflections", headers=headers)
    assert task_reflections.status_code == 200
    assert task_reflections.json()["total"] >= 1

    reflection_id = task_reflections.json()["items"][0]["id"]
    detail = client.get(f"/api/v1/reflections/{reflection_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == reflection_id
    assert "actions" in detail.json()


def test_reflective_memories_route_requires_owner_and_returns_redacted_shape(app_client_factory):
    client = app_client_factory()
    profile_id, access_key = _create_profile_with_key(client)
    _, other_access_key = _create_profile_with_key(client)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve matrix exercises",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    from agent_core.api import dependencies as api_dependencies
    from agent_core.domain.entities.reflection import ReflectionRecord
    from agent_core.domain.entities.reflection_v2 import ReflectiveMemory
    from agent_core.infrastructure.db.repositories import ReflectionRecordRepository, ReflectiveMemoryRepository
    import asyncio

    async def seed_reflective_memory() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            reflection = ReflectionRecord.build(
                learner_profile_id=profile_id,
                learner_goal_id=goal_id,
                daily_task_id=None,
                workflow_run_id=None,
                study_plan_id=None,
                scope="goal",
                target_type="learner_goal",
                target_id=goal_id,
                trigger_source="task_failed",
                reflection_depth=1,
                dedupe_key=f"test-reflective-memory:{goal_id}",
                aggregation_key=f"test-reflective-memory:{goal_id}",
                duplicate_count=0,
                priority_score=0.7,
                last_duplicate_at=None,
                cooldown_until=None,
                primary_root_cause="knowledge_gap",
                secondary_root_causes=[],
                severity="medium",
                confidence_score=0.8,
                summary="Learner needs more worked examples.",
                evidence_summary="Internal reflection evidence.",
                recommended_next_step="Add guided practice.",
                evidence_payload={"internal": "evidence"},
            )
            await ReflectionRecordRepository(db).create(reflection)
            await ReflectiveMemoryRepository(db).create(
                ReflectiveMemory.build(
                    learner_profile_id=profile_id,
                    learner_goal_id=goal_id,
                    reflection_record_id=reflection.id,
                    memory_key=f"goal:{goal_id}:strategy:knowledge_gap",
                    title="Guided practice helps",
                    summary="Use guided matrix practice.",
                    details="Internal reflection details should not be returned.",
                    memory_level="pattern",
                    importance_score=0.7,
                    confidence_score=0.8,
                    freshness_score=1.0,
                    evidence_count=1,
                    source_reflection_ids=[reflection.id],
                    source_action_ids=["action-1"],
                    tags=["knowledge_gap"],
                    status="active",
                )
            )
            await db.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed_reflective_memory())
    finally:
        loop.close()

    missing_key = client.get(f"/api/v1/goals/{goal_id}/reflective-memories")
    assert missing_key.status_code == 401

    wrong_key = client.get(
        f"/api/v1/goals/{goal_id}/reflective-memories",
        headers=_learner_headers(other_access_key),
    )
    assert wrong_key.status_code == 404

    response = client.get(
        f"/api/v1/goals/{goal_id}/reflective-memories",
        headers=_learner_headers(access_key),
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["summary"] == "Use guided matrix practice."
    assert "details" not in payload[0]
    assert "reflection_record_id" not in payload[0]
    assert "source_reflection_ids" not in payload[0]
    assert "source_action_ids" not in payload[0]


def test_reflection_proposal_sandbox_and_approval_endpoints(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})

    profile_response = client.post("/api/v1/learner-profiles", json={})
    assert profile_response.status_code == 200
    profile_id = profile_response.json()["id"]
    access_key = profile_response.json()["access_key"]
    headers = _learner_headers(access_key)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    plan_response = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert plan_response.status_code == 200

    tasks_response = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_response.status_code == 200
    task_id = tasks_response.json()[0]["id"]

    execute_response = client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
    assert execute_response.status_code == 200

    failed_response = client.patch(
        f"/api/v1/tasks/{task_id}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Still confused"},
    )
    assert failed_response.status_code == 200

    reflections = client.get(f"/api/v1/tasks/{task_id}/reflections", headers=headers)
    assert reflections.status_code == 200
    reflection_id = reflections.json()["items"][0]["id"]

    proposals = client.get(f"/api/v1/reflections/{reflection_id}/proposals", headers=headers)
    assert proposals.status_code == 200
    assert len(proposals.json()) >= 1
    proposal_id = proposals.json()[0]["id"]

    unauthorized = client.post(
        f"/api/v1/proposals/{proposal_id}/sandbox",
        json={"reason_code": "queue", "reason_note": "Run sandbox"},
    )
    assert unauthorized.status_code == 403

    queued = client.post(
        f"/api/v1/proposals/{proposal_id}/sandbox",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "queue", "reason_note": "Run sandbox"},
    )
    assert queued.status_code == 200
    assert queued.json()["status"] in {"sandbox_queued", "sandbox_running", "sandbox_completed"}

    from agent_core.api import dependencies as api_dependencies
    import asyncio

    async def run_worker_once() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            service = api_dependencies.get_task_service(db)
            await service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="test-worker")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_worker_once())
    finally:
        loop.close()

    proposal_detail = client.get(
        f"/api/v1/proposals/{proposal_id}",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert proposal_detail.status_code == 200
    proposal_payload = proposal_detail.json()
    assert proposal_payload["status"] == "sandbox_completed"
    assert proposal_payload["latest_sandbox_run_id"] is not None
    assert "auto_sandbox_eligible" in proposal_payload
    assert "activation_surface" in proposal_payload

    learner_proposal_detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers)
    assert learner_proposal_detail.status_code == 200

    missing_proposal_key = client.get(f"/api/v1/proposals/{proposal_id}")
    assert missing_proposal_key.status_code == 401

    sandbox_runs = client.get(
        f"/api/v1/proposals/{proposal_id}/sandbox-runs",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert sandbox_runs.status_code == 200
    assert len(sandbox_runs.json()) >= 1

    evaluation = client.get(
        f"/api/v1/proposals/{proposal_id}/evaluation",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["proposal_id"] == proposal_id

    approved = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "validated", "reason_note": "Sandbox passed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    activated = client.post(
        f"/api/v1/proposals/{proposal_id}/activate",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "activate", "reason_note": "Start staged rollout"},
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "staged"
    rollout_id = activated.json()["id"]

    rollout_list = client.get(
        f"/api/v1/proposals/{proposal_id}/rollouts",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert rollout_list.status_code == 200
    assert len(rollout_list.json()) == 1

    rollout_session = client.post(
        "/api/v1/sessions",
        json={
            "learner_profile_id": profile_id,
            "learner_goal_id": goal_id,
            "title": "Matrices rollout check",
            "subject": "Linear Algebra",
        },
    )
    assert rollout_session.status_code == 200
    rollout_session_id = rollout_session.json()["id"]

    hint_response = client.post(
        f"/api/v1/sessions/{rollout_session_id}/messages",
        json={
            "content": "Give me a first hint.",
            "mode": "hint",
            "question_prompt": "What is the next step in matrix multiplication?",
        },
    )
    assert hint_response.status_code == 200
    if proposal_payload["activation_surface"] == "hint":
        assert hint_response.json()["assistant_payload"]["hint_level"] == "scaffolded"

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_worker_once())
    finally:
        loop.close()

    observations = client.get(
        f"/api/v1/rollouts/{rollout_id}/observations",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert observations.status_code == 200
    assert len(observations.json()) >= 1

    promoted = client.post(
        f"/api/v1/rollouts/{rollout_id}/promote",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "promote", "reason_note": "Signals look stable"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "rolled_out"

    rolled_back = client.post(
        f"/api/v1/rollouts/{rollout_id}/rollback",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "rollback", "reason_note": "End staged rollout"},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "rolled_back"


def test_workspace_summary_and_memory_browse_endpoints(app_client_factory):
    client = app_client_factory()
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    other_profile_id, other_access_key = _create_profile_with_key(client)

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Linear Algebra",
            "subject": "Matrices",
            "target_outcome": "Understand matrix operations.",
            "baseline_note": "Needs structure.",
            "deadline_date": (date.today() + timedelta(days=30)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=_learner_headers(access_key), json={"trigger_source": "initial"})
    assert plan.status_code == 200

    session = client.post(
        "/api/v1/sessions",
        json={
            "learner_profile_id": profile_id,
            "learner_goal_id": goal_id,
            "title": "Matrices intro",
            "subject": "Matrices",
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
    )
    assert message.status_code == 200

    missing_workspace_key = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        params={"goal_id": goal_id},
    )
    assert missing_workspace_key.status_code == 401

    wrong_workspace_key = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(other_access_key),
        params={"goal_id": goal_id},
    )
    assert other_profile_id != profile_id
    assert wrong_workspace_key.status_code == 404

    workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
        params={"goal_id": goal_id},
    )
    assert workspace.status_code == 200
    workspace_payload = workspace.json()
    assert workspace_payload["learner_goal"]["id"] == goal_id
    assert workspace_payload["active_plan"] is not None
    assert len(workspace_payload["today_tasks"]) >= 1
    assert workspace_payload["memory_summary"]["knowledge_count"] >= 1
    assert workspace_payload["memory_summary"]["behavior_count"] >= 1
    assert any(item["id"] == session_id for item in workspace_payload["recent_sessions"])

    filtered_tasks = client.get(
        f"/api/v1/goals/{goal_id}/tasks",
        headers=_learner_headers(access_key),
        params={
            "status": ["pending"],
            "scheduled_to": (date.today() + timedelta(days=14)).isoformat(),
        },
    )
    assert filtered_tasks.status_code == 200
    assert len(filtered_tasks.json()) >= 1
    assert all(item["status"] == "pending" for item in filtered_tasks.json())

    knowledge_browse = client.get(
        "/api/v1/memory/knowledge/browse",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "learner_goal_id": goal_id, "limit": 5, "offset": 0},
    )
    assert knowledge_browse.status_code == 200
    assert knowledge_browse.json()["total"] >= 1
    assert len(knowledge_browse.json()["items"]) >= 1

    behavior_browse = client.get(
        "/api/v1/memory/behavior/browse",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "learner_goal_id": goal_id, "limit": 5, "offset": 0},
    )
    assert behavior_browse.status_code == 200
    assert behavior_browse.json()["total"] >= 1


def test_skills_readyz_and_metrics_endpoints(app_client_factory):
    client = app_client_factory(
        env_overrides={
            "AGENT_EDU_METRICS_ENABLED": "1",
            "AGENT_EDU_OPERATOR_API_KEY": "secret-operator",
        }
    )

    skills = client.get("/api/v1/skills")
    assert skills.status_code == 401

    skills = client.get("/api/v1/skills", headers=_operator_headers())
    assert skills.status_code == 200
    assert len(skills.json()) >= 1

    _, access_key = _create_profile_with_key(client)
    learner_skills = client.get("/api/v1/skills", headers=_learner_headers(access_key))
    assert learner_skills.status_code == 200
    assert len(learner_skills.json()) >= 1

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert healthz.json() == {"status": "ok"}

    readyz = client.get("/readyz")
    assert readyz.status_code == 200
    assert readyz.json() == {"status": "ready"}

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Calculus", "subject": "Derivatives"},
    )
    session_id = session_response.json()["id"]
    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain derivatives simply.", "mode": "chat"},
    )
    assert chat_response.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "agent_edu_http_requests_total" in metrics.text
    assert 'route="/api/v1/sessions/{session_id}/messages"' in metrics.text
    assert "agent_edu_llm_operations_total" in metrics.text
    assert "agent_edu_audit_writes_total" in metrics.text


def test_phase2_profile_goal_plan_task_workflow_chain(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": "Learner struggles with dimensions.",
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    plan = client.post(
        f"/api/v1/goals/{goal_id}/plans",
        headers=headers,
        json={"trigger_source": "initial"},
    )
    assert plan.status_code == 200
    plan_payload = plan.json()
    assert plan_payload["version"] == 1
    assert len(plan_payload["stages"]) >= 2

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks.status_code == 200
    task_payloads = tasks.json()
    assert len(task_payloads) >= 1
    first_task = task_payloads[0]

    execute = client.post(f"/api/v1/tasks/{first_task['id']}/execute", headers=headers)
    assert execute.status_code == 200
    execute_payload = execute.json()
    assert execute_payload["reused_existing_execution"] is False
    assert execute_payload["task"]["status"] == "in_progress"
    assert execute_payload["execution_session_id"] is not None

    complete = client.patch(
        f"/api/v1/tasks/{first_task['id']}/status",
        headers=headers,
        json={"status": "completed", "result_note": "Finished"},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"

    tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_after.status_code == 200
    assert any(item["task_type"] == "review" for item in tasks_after.json())

    runs = client.get(f"/api/v1/goals/{goal_id}/workflow-runs", headers=headers)
    assert runs.status_code == 200
    workflow_types = {item["workflow_type"] for item in runs.json()}
    assert {"plan_generation", "task_execution", "review_scheduling"}.issubset(workflow_types)


def test_phase2_failed_task_triggers_replan_and_supersedes_future_tasks(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    goal_id = goal.json()["id"]
    initial_plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"}).json()

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers).json()
    pending_task = tasks[0]
    failed = client.patch(
        f"/api/v1/tasks/{pending_task['id']}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Learner blocked"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"

    plans = client.get(f"/api/v1/goals/{goal_id}/plans", headers=headers)
    assert plans.status_code == 200
    plan_versions = sorted(item["version"] for item in plans.json())
    assert plan_versions == [1, 2]
    latest_plan = plans.json()[0]
    assert latest_plan["version"] == 2

    old_plan = next(item for item in plans.json() if item["id"] == initial_plan["id"])
    assert old_plan["status"] == "superseded"


def test_autonomy_endpoints_cover_state_availability_pause_and_manual_replan(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    goal_id = goal.json()["id"]
    plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"}).json()

    state = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=headers)
    assert state.status_code == 200
    state_payload = state.json()
    assert state_payload["phase"] == "active"
    assert state_payload["current_plan_id"] == plan["id"]

    availability = client.put(
        f"/api/v1/goals/{goal_id}/availability",
        headers=headers,
        json={
            "timezone": "Asia/Shanghai",
            "available_days": ["mon", "wed", "fri"],
            "time_windows": [{"start": "19:00", "end": "21:00"}],
            "max_daily_minutes": 90,
            "preferred_session_length_minutes": 45,
        },
    )
    assert availability.status_code == 200
    assert availability.json()["timezone"] == "Asia/Shanghai"

    listed_mastery = client.get(f"/api/v1/goals/{goal_id}/mastery", headers=headers)
    assert listed_mastery.status_code == 200
    assert listed_mastery.json() == []

    jobs = client.get(f"/api/v1/goals/{goal_id}/autonomy/jobs", headers=headers)
    assert jobs.status_code == 200
    assert isinstance(jobs.json(), list)
    materialization_jobs = [item for item in jobs.json() if item["job_type"] == "daily_task_materialization"]
    assert materialization_jobs
    assert materialization_jobs[0]["payload"]["target_timezone"] == "Asia/Shanghai"
    assert materialization_jobs[0]["payload"]["scheduled_local_time"] == "19:00"

    paused = client.patch(
        f"/api/v1/goals/{goal_id}/autonomy/pause",
        headers=headers,
        json={"reason": "travel"},
    )
    assert paused.status_code == 200
    assert paused.json()["phase"] == "paused"

    resumed = client.patch(f"/api/v1/goals/{goal_id}/autonomy/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["phase"] == "active"

    replanned = client.post(
        f"/api/v1/goals/{goal_id}/replan",
        headers=headers,
        json={"trigger_source": "manual_replan", "mode": "full"},
    )
    assert replanned.status_code == 200
    assert replanned.json()["phase"] == "active"

    materialized = client.post(f"/api/v1/goals/{goal_id}/autonomy/materialize-today", headers=headers)
    assert materialized.status_code == 200
    assert materialized.json()["phase"] == "active"

    plans = client.get(f"/api/v1/goals/{goal_id}/plans", headers=headers)
    assert plans.status_code == 200
    plan_versions = sorted(item["version"] for item in plans.json())
    assert plan_versions == [1, 2]


def test_milestone_gate_surfaces_assessment_due_phase(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    planned = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert planned.status_code == 200

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks.status_code == 200
    first_stage_id = tasks.json()[0]["plan_stage_id"]
    first_stage_tasks = [item for item in tasks.json() if item["plan_stage_id"] == first_stage_id and item["task_type"] in {"lesson", "practice"}]
    target_count = max(1, (len(first_stage_tasks) + 1) // 2)
    for item in first_stage_tasks[:target_count]:
        executed = client.post(f"/api/v1/tasks/{item['id']}/execute", headers=headers)
        assert executed.status_code == 200
        completed = client.patch(
            f"/api/v1/tasks/{item['id']}/status",
            headers=headers,
            json={"status": "completed", "result_note": "Done"},
        )
        assert completed.status_code == 200

    worker_materialized = client.post(f"/api/v1/goals/{goal_id}/autonomy/materialize-today", headers=headers)
    assert worker_materialized.status_code == 200

    state = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=headers)
    assert state.status_code == 200
    assert state.json()["phase"] in {"active", "assessment_due"}

    tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_after.status_code == 200
    assert any(item["task_type"] == "milestone" for item in tasks_after.json())


def test_skill_operator_usage_api_records_chat_usage(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    missing_key = client.get("/api/v1/skill-usage")
    assert missing_key.status_code == 403

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Algebra", "subject": "Equations"},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain linear equations.", "mode": "chat"},
    )
    assert chat_response.status_code == 200

    usage_response = client.get(
        "/api/v1/skill-usage",
        headers=_operator_headers(),
        params={"session_id": session_id},
    )
    assert usage_response.status_code == 200
    usage = usage_response.json()
    chat_usage = next(item for item in usage if item["skill_name"] == "explain_concept" and item["surface"] == "chat")
    assert chat_usage["resolver_status"] == "missing_artifact"
    assert chat_usage["selection_reason"] == "artifact_missing_static_fallback"
    assert chat_usage["input_fingerprint"] is not None
    assert chat_usage["output_fingerprint"] is not None
    assert chat_usage["outcome_signals"] == {}

    artifacts_response = client.get("/api/v1/skill-artifacts", headers=_operator_headers())
    assert artifacts_response.status_code == 200

    filtered_usage = client.get(
        "/api/v1/skill-usage",
        headers=_operator_headers(),
        params={"resolver_status": "missing_artifact", "surface": "chat"},
    )
    assert filtered_usage.status_code == 200
    assert any(item["id"] == chat_usage["id"] for item in filtered_usage.json())

    resolution_response = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "explain_concept", "surface": "chat"},
    )
    assert resolution_response.status_code == 200
    assert resolution_response.json()["resolver_status"] == "missing_artifact"
