from agent_core.application.services.chat import ChatService
from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.dynamic_runtime_registry import DynamicRuntimeRegistryService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.domain.entities.memory import (
    BehaviorMemoryRetrievalResult,
    KnowledgeMemoryRetrievalResult,
    MemoryRetrievalResult,
    RetrievedMemory,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.reflection_closure import ReflectionProposalRollout
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.session import ExplanationPayload, HintPayload, MessageRequest
from agent_core.infrastructure.llm.mock_provider import MockLLMProvider
from agent_core.infrastructure.llm.types import TutorReply


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def begin(self):
        return FakeTransaction()

    def begin_nested(self):
        return FakeTransaction()

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


class StubSessionRepository:
    def __init__(self, session_entity, other_sessions=None):
        self.session_entity = session_entity
        self.other_sessions = list(other_sessions or [])
        self.updated = None

    async def get_by_id(self, session_id):
        if self.session_entity and self.session_entity.id == session_id:
            return self.session_entity
        return None

    async def list_sessions(self):
        sessions = list(self.other_sessions)
        if self.session_entity is not None:
            sessions.append(self.session_entity)
        return sessions

    async def list_recent_by_goal(self, learner_goal_id, *, limit=10, exclude_id=None):
        sessions = [
            item
            for item in self.other_sessions
            if item.learner_goal_id == learner_goal_id and item.id != exclude_id
        ]
        return sessions[:limit]

    async def update(self, entity):
        self.updated = entity
        self.session_entity = entity


class StubMessageRepository:
    def __init__(self):
        self.messages = []

    async def create(self, entity: SessionMessage):
        self.messages.append(entity)

    async def list_history(self, *, session_id, limit, before_id):
        assert before_id is None
        return [item for item in self.messages if item.session_id == session_id][-limit:]


class StubMemoryRepository:
    def __init__(self):
        self.events = []

    async def create(self, entity: MemoryEvent):
        self.events.append(entity)


class StubAuditRepository:
    def __init__(self):
        self.events = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubScheduledAutonomyJobRepository:
    def __init__(self):
        self.jobs: dict[str, ScheduledAutonomyJob] = {}

    async def create(self, entity: ScheduledAutonomyJob):
        for job in self.jobs.values():
            if job.idempotency_key == entity.idempotency_key:
                return job
        self.jobs[entity.id] = entity
        return entity


class StubProposalRolloutRepository:
    def __init__(self):
        self.items: dict[str, ReflectionProposalRollout] = {}

    async def create(self, entity: ReflectionProposalRollout):
        self.items[entity.id] = entity

    async def get_by_id(self, rollout_id: str):
        return self.items.get(rollout_id)

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ):
        statuses = {"staged", "rolled_out"} if include_staged else {"rolled_out"}
        active = [
            item
            for item in self.items.values()
            if item.learner_goal_id == learner_goal_id and item.surface == surface and item.status in statuses
        ]
        return active[-1] if active else None


class StubStrategyCardService:
    async def get_active(self, learner_goal_id: str):
        return None


class StubRolloutResolver:
    def __init__(self, overlays=None):
        self.overlays = dict(overlays or {})

    async def get_active_overlay(self, *, learner_goal_id: str, surface: str, include_staged: bool = False):
        payload = self.overlays.get((learner_goal_id, surface))
        if payload is None:
            return None
        return type(
            "Overlay",
            (),
            {
                "rollout_id": "rollout-1",
                "proposal_id": "proposal-1",
                "learner_goal_id": learner_goal_id,
                "surface": surface,
                "status": "staged",
                "payload": payload,
                "baseline_snapshot": {},
            },
        )()


class StubSkillUsageService:
    def __init__(self, execution_plan: SkillExecutionPlan | None = None):
        self.execution_plan = execution_plan
        self.events: list[dict[str, object]] = []

    async def resolve_for_runtime(self, *, skill_name: str, surface: str, resource_id: str | None = None):
        if self.execution_plan is not None:
            return self.execution_plan.resolution
        return SkillResolution.build(
            skill_name=skill_name,
            surface=surface,
            implementation_binding=skill_name,
        )

    async def resolve_execution_plan(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        skill_binding=None,
    ):
        if self.execution_plan is None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                implementation_binding=skill_name,
            )
            return SkillExecutionPlan(
                resolution=resolution,
                execution_kind="tutor_reply",
                runtime_directives={},
                tool_plan=[],
                binding_metadata={},
            )
        return self.execution_plan

    async def record_usage(self, **kwargs):
        self.events.append(dict(kwargs))
        return None


class CaptureTutorReplyProvider:
    provider_name = "capture"
    model_name = "capture-model"

    def __init__(self):
        self.last_skill_directives = None

    async def generate_tutor_reply(
        self,
        *,
        session_title,
        subject,
        learner_message,
        mode,
        history,
        memory_contexts,
        learner_profile,
        hint_context=None,
    ):
        self.last_skill_directives = list(learner_profile.skill_directives)
        return TutorReply(
            content="captured reply",
            payload=ExplanationPayload(
                definition="definition",
                core_principles=["principle"],
                worked_example="example",
                common_mistake="mistake",
                next_step="next",
            ),
            provider="capture",
            model="capture-model",
            latency_ms=1,
            retry_count=0,
            response_shape_valid=True,
        )


class StubSemanticMemoryService:
    def __init__(self, created_at):
        self.recorded = []
        self.queries = []
        self._created_at = created_at
        self.embedding_provider_name = "stub"
        self.embedding_model_name = "stub-embedding-v1"

    async def record_learning_memories(self, **kwargs):
        events = [
            MemoryEvent.build(
                session_id=kwargs["session_id"],
                learner_profile_id=kwargs["learner_profile_id"],
                event_type="session.note",
                memory_scope="session",
                memory_level="episodic",
                summary="session memory",
                progress_note="progress",
                struggle_note="struggle",
                concept_focus="concept",
                source_message_id=kwargs["source_message_id"],
                tags=["session", kwargs["mode"] or "chat"],
            ),
            MemoryEvent.build(
                session_id=kwargs["session_id"],
                learner_profile_id=kwargs["learner_profile_id"],
                event_type="session.note",
                memory_scope="profile",
                memory_level="semantic",
                summary="profile memory",
                progress_note="progress",
                struggle_note="struggle",
                concept_focus="concept",
                source_message_id=kwargs["source_message_id"],
                tags=["profile", kwargs["mode"] or "chat"],
            ),
        ]
        self.recorded.extend(events)
        return events

    async def retrieve_relevant_session_memories(self, **kwargs):
        self.queries.append(kwargs)
        return MemoryRetrievalResult(
            memories=[
                RetrievedMemory(
                    memory_event_id="mem-1",
                    summary="Learner previously mixed up rows and columns.",
                    memory_scope="session",
                    memory_level="episodic",
                    progress_note=None,
                    struggle_note="Learner previously mixed up rows and columns.",
                    concept_focus="matrix multiplication",
                    score=0.82,
                    created_at=self._created_at,
                )
            ],
            provider="stub",
            model="stub-embedding-v1",
            latency_ms=3,
            candidate_count=1,
        )

    async def retrieve_relevant_profile_memories(self, **kwargs):
        return MemoryRetrievalResult(
            memories=[
                RetrievedMemory(
                    memory_event_id="mem-2",
                    summary="Learner profile update for Matrices. Recurring struggle: determinants.",
                    memory_scope="profile",
                    memory_level="semantic",
                    progress_note=None,
                    struggle_note="determinants",
                    concept_focus="matrices",
                    score=0.71,
                    created_at=self._created_at,
                )
            ],
            provider="stub",
            model="stub-embedding-v1",
            latency_ms=2,
            candidate_count=1,
        )

    async def retrieve_relevant_knowledge_memories(self, **kwargs):
        return KnowledgeMemoryRetrievalResult(
            memories=[],
            provider="stub",
            model="stub-embedding-v1",
            latency_ms=1,
            candidate_count=0,
        )

    async def retrieve_relevant_behavior_memories(self, **kwargs):
        return BehaviorMemoryRetrievalResult(
            memories=[],
            provider="stub",
            model="stub-embedding-v1",
            latency_ms=1,
            candidate_count=0,
        )


class FailingProfileMemoryService(StubSemanticMemoryService):
    async def retrieve_relevant_profile_memories(self, **kwargs):
        raise RuntimeError("profile retrieval failed")


class FailingLongTermMemoryMaterializationService:
    async def materialize_from_chat_turn(self, **kwargs):
        raise RuntimeError("materialization failed")


class StubQuizRepository:
    def __init__(self):
        self.quiz = None
        self.questions = []

    async def get_quiz_with_questions(self, *, session_id, quiz_id):
        if self.quiz is None or self.quiz.id != quiz_id or self.quiz.session_id != session_id:
            raise NotFoundError(f"Quiz '{quiz_id}' was not found in session '{session_id}'.")
        return type(
            "StoredQuiz",
            (),
            {
                "quiz": self.quiz,
                "questions": self.questions,
            },
        )()


async def test_chat_message_chain_updates_session_and_writes_events():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    fake_session = FakeSession()
    message_repository = StubMessageRepository()
    memory_repository = StubMemoryRepository()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    chat_service = ChatService(
        db_session=fake_session,
        session_repository=StubSessionRepository(session),
        message_repository=message_repository,
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(memory_repository, audit_service=audit_service),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    assert response.session_id == session.id
    assert response.skill_trace == ["explain_concept"]
    assert "structured explanation" in response.assistant_message
    assert isinstance(response.assistant_payload, ExplanationPayload)
    assert response.turn_metrics.history_count == 0
    assert response.turn_metrics.memory_context_count == 0
    assert response.turn_metrics.cross_session_context_count == 0
    assert response.turn_metrics.response_shape_valid is True
    assert chat_service._session_repository.updated is not None
    assert chat_service._session_repository.updated.message_count == 2
    assert "learner asked about" in chat_service._session_repository.updated.summary
    assert len(message_repository.messages) == 2
    assert len(memory_repository.events) == 2
    assert len(audit_repository.events) == 7
    assert [item.event_type for item in audit_repository.events].count("memory.event.recorded") == 2
    assert any(item.event_type == "memory.events.recorded" for item in audit_repository.events)
    assert fake_session.committed == 1


async def test_hint_mode_returns_hint_style_reply():
    session = LearningSession.build(learner_profile_id="profile-1", title="Geometry", subject="Triangles")
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="How do I start this proof?", mode="hint"),
    )

    assert response.skill_trace == ["adaptive_hint"]
    assert "conceptual hint" in response.assistant_message
    assert "short, structured explanation" not in response.assistant_message
    assert isinstance(response.assistant_payload, HintPayload)
    assert response.assistant_payload.hint_level == "conceptual"
    assert response.assistant_payload.direct_answer_given is False
    assert response.turn_metrics.llm_retry_count == 0
    assert response.turn_metrics.hint_level == "conceptual"


async def test_chat_uses_runtime_execution_plan_skill_directives():
    session = LearningSession.build(learner_profile_id="profile-1", title="Geometry", subject="Triangles")
    provider = CaptureTutorReplyProvider()
    execution_plan = SkillExecutionPlan(
        resolution=SkillResolution.build(
            skill_name="explain_concept",
            surface="chat",
            implementation_binding="llm_explain_concept_v1",
            artifact_id="artifact-1",
            skill_version="1.0.1",
            artifact_status="active",
        ),
        execution_kind="tutor_reply",
        runtime_directives={"skill_directives": ["be_socratic", "use_counterexample"]},
        tool_plan=[],
        binding_metadata={"skill_package_rollout": {"proposal_id": "proposal-1"}},
    )
    skill_usage_service = StubSkillUsageService(execution_plan)
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=provider,
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
        skill_usage_service=skill_usage_service,
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain triangle congruence.", mode="chat"),
    )

    assert response.skill_trace == ["explain_concept"]
    assert provider.last_skill_directives == ["be_socratic", "use_counterexample"]
    assert skill_usage_service.events[-1]["metadata"]["implementation_binding"] == "llm_explain_concept_v1"
    assert skill_usage_service.events[-1]["metadata"]["execution_kind"] == "tutor_reply"


async def test_missing_session_raises_not_found():
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(None),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    try:
        await chat_service.create_message(
            session_id="missing",
            payload=MessageRequest(content="Explain this.", mode="chat"),
        )
        assert False, "Expected NotFoundError"
    except NotFoundError:
        assert True


async def test_hint_mode_rejects_disabled_skill():
    session = LearningSession.build(learner_profile_id="profile-1", title="Geometry", subject="Triangles")
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(["explain_concept"]),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    try:
        await chat_service.create_message(
            session_id=session.id,
            payload=MessageRequest(content="How do I start this proof?", mode="hint"),
        )
        assert False, "Expected ValidationError"
    except ValidationError:
        assert True


async def test_chat_message_uses_retrieved_memory_context():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    semantic_memory = StubSemanticMemoryService(session.created_at)
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=semantic_memory,
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    assert "retrieved memory" in response.assistant_message
    assert response.assistant_payload.type == "explanation"
    assert len(semantic_memory.queries) == 1
    assert semantic_memory.queries[0]["query_text"] == "Explain matrix multiplication simply."
    assert response.turn_metrics.cross_session_context_count >= 1


async def test_chat_message_uses_cross_session_profile_context():
    session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Linear Algebra",
        subject="Matrices",
    )
    past_session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Linear Algebra Review",
        subject="Matrices",
    )
    past_session = past_session.with_message_activity(
        message_count_delta=2,
        last_activity_at=past_session.last_activity_at,
        summary="Working on Matrices: learner asked about determinants (hint).",
    )
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session, other_sessions=[past_session]),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    assert response.turn_metrics.cross_session_context_count == 1
    assert response.turn_metrics.history_count == 0


async def test_chat_message_profile_memory_failure_is_audited():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    memory_service = FailingProfileMemoryService(session.created_at)
    audit_repository = StubAuditRepository()
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=memory_service,
        audit_service=AuditService(audit_repository),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    assert response.turn_metrics.memory_context_count == 1
    assert any(
        item.event_type == "embedding.query.failed"
        and item.event_data["operation"] == "profile_memory_retrieval"
        for item in audit_repository.events
    )


async def test_chat_materialization_failure_is_audited_without_blocking_message():
    session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Linear Algebra",
        subject="Matrices",
    )
    audit_repository = StubAuditRepository()
    job_repository = StubScheduledAutonomyJobRepository()
    audit_service = AuditService(audit_repository)
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        long_term_memory_materialization_service=FailingLongTermMemoryMaterializationService(),
        long_term_memory_replay_scheduler=LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=AutonomyJobService(repository=job_repository, audit_service=audit_service),
        ),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    assert response.assistant_message
    assert any(item.event_type == "session.message.assistant_created" for item in audit_repository.events)
    failed = next(
        item
        for item in audit_repository.events
        if item.event_type == "long_term_memory.materialization.failed"
    )
    assert failed.event_data["source_type"] == "chat_turn"
    assert failed.event_data["session_id"] == session.id
    assert failed.event_data["learner_profile_id"] == session.learner_profile_id
    assert failed.event_data["learner_goal_id"] == session.learner_goal_id
    assert failed.event_data["assistant_message_id"] == response.assistant_message_id
    assert failed.event_data["replay_enqueued"] is True
    assert failed.event_data["replay_skip_reason"] is None
    assert len(job_repository.jobs) == 1
    job = next(iter(job_repository.jobs.values()))
    assert job.job_type == "long_term_memory_materialization_replay"
    assert job.learner_goal_id == "goal-1"
    assert job.idempotency_key == (
        f"ltm-replay:chat_turn:{session.id}:{response.user_message_id}:{response.assistant_message_id}"
    )
    assert job.payload == {
        "source_type": "chat_turn",
        "session_id": session.id,
        "user_message_id": response.user_message_id,
        "assistant_message_id": response.assistant_message_id,
    }


async def test_chat_materialization_failure_without_goal_skips_replay_queue():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    audit_repository = StubAuditRepository()
    job_repository = StubScheduledAutonomyJobRepository()
    audit_service = AuditService(audit_repository)
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        long_term_memory_materialization_service=FailingLongTermMemoryMaterializationService(),
        long_term_memory_replay_scheduler=LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=AutonomyJobService(repository=job_repository, audit_service=audit_service),
        ),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    failed = next(
        item
        for item in audit_repository.events
        if item.event_type == "long_term_memory.materialization.failed"
    )
    assert failed.event_data["replay_enqueued"] is False
    assert failed.event_data["replay_skip_reason"] == "missing_learner_goal_id"
    assert job_repository.jobs == {}


async def test_chat_schedules_rollout_observation_for_active_surface():
    session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Linear Algebra",
        subject="Matrices",
    )
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    job_repository = StubScheduledAutonomyJobRepository()
    rollout_repository = StubProposalRolloutRepository()
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-chat-1",
            learner_goal_id="goal-1",
            surface="chat",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=audit_service,
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
        rollout_observation_scheduler=ReflectionProposalRolloutObservationScheduler(
            rollout_repository=rollout_repository,
            autonomy_job_service=AutonomyJobService(repository=job_repository, audit_service=audit_service),
            audit_service=audit_service,
        ),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(content="Explain matrix multiplication simply.", mode="chat"),
    )

    observation_jobs = [
        item
        for item in job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == "goal-1"
    assert observation_jobs[0].trigger_source == "session_turn_completed"
    assert observation_jobs[0].payload["surface"] == "chat"
    assert observation_jobs[0].payload["source_ref"] == response.assistant_message_id


async def test_hint_mode_uses_targeted_level_with_quiz_and_wrong_answer():
    session = LearningSession.build(learner_profile_id="profile-1", title="Algebra", subject="Equations")
    quiz_repository = StubQuizRepository()
    quiz_repository.quiz = SessionQuiz(
        id="quiz-1",
        session_id=session.id,
        topic="Equations",
        difficulty="easy",
        question_count=1,
        skill_trace=["create_quiz"],
        created_at=session.created_at,
    )
    quiz_repository.questions = [
        SessionQuizQuestion(
            id="question-1",
            quiz_id="quiz-1",
            position=1,
            prompt="Solve x + 2 = 5",
            answer="x = 3",
        )
    ]
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=quiz_repository,
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(
            content="My answer feels wrong. Give me a hint.",
            mode="hint",
            related_quiz_id="quiz-1",
            question_prompt="Solve x + 2 = 5",
            learner_answer="x = 5",
        ),
    )

    assert response.assistant_payload.hint_level == "targeted"
    assert response.turn_metrics.hint_level == "targeted"
    assert response.turn_metrics.used_quiz_context is True
    assert response.turn_metrics.used_error_analysis is True


async def test_hint_mode_uses_scaffolded_level_after_prior_hint():
    session = LearningSession.build(learner_profile_id="profile-1", title="Geometry", subject="Triangles")
    message_repository = StubMessageRepository()
    message_repository.messages.append(
        SessionMessage.build(
            session_id=session.id,
            role="assistant",
            content="Earlier hint",
            mode="hint",
            skill_trace=["adaptive_hint"],
            content_payload=HintPayload(
                hint_level="conceptual",
                next_step_hint="Start with the angle sum rule.",
                key_principle="Triangle angles sum to 180 degrees.",
                pitfall="Do not assume equal sides.",
                encouragement="You are close.",
                direct_answer_given=False,
            ).model_dump(),
        )
    )
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=message_repository,
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(
            content="Give me another hint.",
            mode="hint",
            question_prompt="Find the missing angle in the triangle.",
        ),
    )

    assert response.assistant_payload.hint_level == "scaffolded"
    assert response.turn_metrics.hint_history_count == 1


async def test_hint_rollout_overlay_raises_hint_level_floor():
    session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Geometry",
        subject="Triangles",
    )
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
        rollout_resolver=StubRolloutResolver(
            {("goal-1", "hint"): {"hint_level_preference": "scaffolded", "teaching_goal": "unblock next step"}}
        ),
    )

    response = await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(
            content="Give me a first hint.",
            mode="hint",
            question_prompt="Find the missing angle in the triangle.",
        ),
    )

    assert response.assistant_payload.hint_level == "scaffolded"
    assert response.turn_metrics.hint_level == "scaffolded"


async def test_chat_usage_metadata_includes_dynamic_runtime_registry_summary():
    session = LearningSession.build(learner_profile_id="profile-1", title="Geometry", subject="Triangles")
    execution_plan = SkillExecutionPlan(
        resolution=SkillResolution.build(
            skill_name="explain_concept",
            surface="chat",
            implementation_binding="llm_explain_concept_v1",
            artifact_id="artifact-1",
            skill_version="1.0.0",
            artifact_status="active",
        ),
        execution_kind="tutor_reply",
        runtime_directives={"skill_directives": ["scaffold"]},
        tool_plan=[],
        binding_metadata={"skill_package_rollout": {"proposal_id": "proposal-1", "rollout_id": "rollout-1", "binding_id": "binding-1"}},
    )
    skill_usage_service = StubSkillUsageService(execution_plan)
    runtime_registry = DynamicRuntimeRegistryService(
        goal_skill_binding_resolver=None,
        skill_usage_service=skill_usage_service,
    )
    chat_service = ChatService(
        db_session=FakeSession(),
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(),
        quiz_repository=StubQuizRepository(),
        memory_service=MemoryService(StubMemoryRepository()),
        audit_service=AuditService(StubAuditRepository()),
        llm_provider=MockLLMProvider("mock-tutor-v1"),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        reflection_evidence_service=None,
        strategy_card_service=StubStrategyCardService(),
        skill_usage_service=skill_usage_service,
        runtime_registry=runtime_registry,
    )

    await chat_service.create_message(
        session_id=session.id,
        payload=MessageRequest(
            content="Explain triangles.",
            mode="chat",
        ),
    )

    metadata = skill_usage_service.events[-1]["metadata"]
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"]["artifact_source"] == "artifact"
