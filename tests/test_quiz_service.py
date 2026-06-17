from datetime import datetime, timezone

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.dynamic_runtime_registry import DynamicRuntimeRegistryService
from agent_core.application.services.quiz import QuizService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.reflection_closure import ReflectionProposalRollout
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.quiz import GenerateQuizRequest, QuizQuestion
from agent_core.infrastructure.llm.types import QuizDraft


class FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1


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


class StubSessionRepository:
    def __init__(self, session_entity):
        self.session_entity = session_entity

    async def get_by_id(self, session_id):
        if self.session_entity and self.session_entity.id == session_id:
            return self.session_entity
        return None


class StubQuizRepository:
    def __init__(self):
        self.quizzes = {}
        self.questions = {}

    async def create_quiz(self, entity: SessionQuiz):
        self.quizzes[entity.id] = entity

    async def create_questions(self, entities: list[SessionQuizQuestion]):
        for entity in entities:
            self.questions.setdefault(entity.quiz_id, []).append(entity)

    async def list_by_session(self, session_id):
        return [item for item in self.quizzes.values() if item.session_id == session_id]

    async def get_quiz_with_questions(self, *, session_id, quiz_id):
        quiz = self.quizzes[quiz_id]
        return type(
            "StoredQuiz",
            (),
            {
                "quiz": quiz,
                "questions": [
                    QuizQuestion(prompt=item.prompt, answer=item.answer)
                    for item in sorted(self.questions.get(quiz_id, []), key=lambda q: q.position)
                ],
            },
        )()


class StubLLMProvider:
    provider_name = "mock"
    model_name = "mock-tutor-v1"

    async def generate_quiz_draft(self, *, topic, difficulty, question_count, skill_directives=None, feedback_style=None):
        return QuizDraft(
            topic=topic,
            difficulty=difficulty,
            questions=[
                QuizQuestion(prompt=f"{topic} question {index + 1}", answer=f"answer {index + 1}")
                for index in range(question_count)
            ],
            provider="mock",
            model="mock-tutor-v1",
            latency_ms=12,
            retry_count=0,
            response_shape_valid=True,
        )


class CaptureQuizProvider:
    provider_name = "capture"
    model_name = "capture-model"

    def __init__(self):
        self.last_question_count = None
        self.last_skill_directives = None
        self.last_feedback_style = None

    async def generate_quiz_draft(self, *, topic, difficulty, question_count, skill_directives=None, feedback_style=None):
        self.last_question_count = question_count
        self.last_skill_directives = list(skill_directives or [])
        self.last_feedback_style = feedback_style
        return QuizDraft(
            topic=topic,
            difficulty=difficulty,
            questions=[
                QuizQuestion(prompt=f"{topic} question {index + 1}", answer=f"answer {index + 1}")
                for index in range(question_count)
            ],
            provider="capture",
            model="capture-model",
            latency_ms=5,
            retry_count=0,
            response_shape_valid=True,
        )


class StubSkillUsageService:
    def __init__(self, execution_plan: SkillExecutionPlan | None = None):
        self.execution_plan = execution_plan
        self.events = []

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
                execution_kind="quiz_draft",
                runtime_directives={},
                tool_plan=[],
                binding_metadata={},
            )
        return self.execution_plan

    async def record_usage(self, **kwargs):
        self.events.append(dict(kwargs))
        return None


async def test_generate_quiz_persists_session_quiz_and_questions():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    repository = StubQuizRepository()
    audit_repository = StubAuditRepository()
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(audit_repository),
        session_repository=StubSessionRepository(session),
        quiz_repository=repository,
        llm_provider=StubLLMProvider(),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
    )

    response = await service.generate_quiz(
        GenerateQuizRequest(
            session_id=session.id,
            topic="Matrices",
            difficulty="easy",
            question_count=2,
        )
    )

    assert response.session_id == session.id
    assert response.question_count == 2
    assert response.skill_trace == ["create_quiz"]
    assert len(repository.quizzes) == 1
    quiz_id = next(iter(repository.quizzes))
    assert len(repository.questions[quiz_id]) == 2
    assert len(audit_repository.events) == 2


async def test_generate_quiz_requires_session_id():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        session_repository=StubSessionRepository(session),
        quiz_repository=StubQuizRepository(),
        llm_provider=StubLLMProvider(),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
    )

    try:
        await service.generate_quiz(
            GenerateQuizRequest(
                topic="Matrices",
                difficulty="easy",
                question_count=2,
            )
        )
        assert False, "Expected ValidationError"
    except ValidationError:
        assert True


async def test_generate_quiz_uses_runtime_execution_plan_directives():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    repository = StubQuizRepository()
    provider = CaptureQuizProvider()
    execution_plan = SkillExecutionPlan(
        resolution=SkillResolution.build(
            skill_name="create_quiz",
            surface="quiz",
            implementation_binding="llm_create_quiz_v1",
            artifact_id="artifact-1",
            skill_version="1.0.1",
            artifact_status="active",
        ),
        execution_kind="quiz_draft",
        runtime_directives={
            "question_count": 3,
            "skill_directives": ["guided_correction", "show_work"],
            "feedback_style": "guided_correction",
        },
        tool_plan=[],
        binding_metadata={"skill_package_rollout": {"proposal_id": "proposal-1"}},
    )
    skill_usage_service = StubSkillUsageService(execution_plan)
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        session_repository=StubSessionRepository(session),
        quiz_repository=repository,
        llm_provider=provider,
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        skill_usage_service=skill_usage_service,
    )

    response = await service.generate_quiz(
        GenerateQuizRequest(
            session_id=session.id,
            topic="Matrices",
            difficulty="easy",
            question_count=1,
        )
    )

    assert response.question_count == 3
    assert provider.last_question_count == 3
    assert provider.last_skill_directives == ["guided_correction", "show_work"]
    assert provider.last_feedback_style == "guided_correction"
    assert skill_usage_service.events[-1]["metadata"]["implementation_binding"] == "llm_create_quiz_v1"
    assert skill_usage_service.events[-1]["metadata"]["execution_kind"] == "quiz_draft"


async def test_generate_quiz_usage_metadata_includes_dynamic_runtime_registry_summary():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    repository = StubQuizRepository()
    provider = CaptureQuizProvider()
    execution_plan = SkillExecutionPlan(
        resolution=SkillResolution.build(
            skill_name="create_quiz",
            surface="quiz",
            implementation_binding="llm_create_quiz_v1",
            artifact_id="artifact-1",
            skill_version="1.0.1",
            artifact_status="active",
        ),
        execution_kind="quiz_draft",
        runtime_directives={"question_count": 2},
        tool_plan=[],
        binding_metadata={"skill_package_rollout": {"proposal_id": "proposal-1", "rollout_id": "rollout-1", "binding_id": "binding-1"}},
    )
    skill_usage_service = StubSkillUsageService(execution_plan)
    runtime_registry = DynamicRuntimeRegistryService(
        goal_skill_binding_resolver=None,
        skill_usage_service=skill_usage_service,
    )
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        session_repository=StubSessionRepository(session),
        quiz_repository=repository,
        llm_provider=provider,
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        skill_usage_service=skill_usage_service,
        runtime_registry=runtime_registry,
    )

    await service.generate_quiz(
        GenerateQuizRequest(
            session_id=session.id,
            topic="Matrices",
            difficulty="easy",
            question_count=2,
        )
    )

    metadata = skill_usage_service.events[-1]["metadata"]
    assert metadata["dynamic_registry_version"] == "v1"
    assert metadata["source_summary"]["artifact_source"] == "artifact"


async def test_generate_quiz_schedules_rollout_observation_for_active_surface():
    session = LearningSession.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        title="Linear Algebra",
        subject="Matrices",
    )
    repository = StubQuizRepository()
    audit_repository = StubAuditRepository()
    audit_service = AuditService(audit_repository)
    job_repository = StubScheduledAutonomyJobRepository()
    rollout_repository = StubProposalRolloutRepository()
    await rollout_repository.create(
        ReflectionProposalRollout.build(
            proposal_id="proposal-quiz-1",
            learner_goal_id="goal-1",
            surface="quiz",
            baseline_snapshot={},
            runtime_overlay_payload={},
            activated_by="operator",
        ).with_status("rolled_out")
    )
    service = QuizService(
        db_session=FakeSession(),
        audit_service=audit_service,
        session_repository=StubSessionRepository(session),
        quiz_repository=repository,
        llm_provider=StubLLMProvider(),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
        rollout_observation_scheduler=ReflectionProposalRolloutObservationScheduler(
            rollout_repository=rollout_repository,
            autonomy_job_service=AutonomyJobService(repository=job_repository, audit_service=audit_service),
            audit_service=audit_service,
        ),
    )

    response = await service.generate_quiz(
        GenerateQuizRequest(
            session_id=session.id,
            topic="Matrices",
            difficulty="easy",
            question_count=2,
        )
    )

    observation_jobs = [
        item
        for item in job_repository.jobs.values()
        if item.job_type == "reflection_proposal_rollout_observation"
    ]
    assert len(observation_jobs) == 1
    assert observation_jobs[0].learner_goal_id == "goal-1"
    assert observation_jobs[0].trigger_source == "quiz_generation"
    assert observation_jobs[0].payload["surface"] == "quiz"
    assert observation_jobs[0].payload["source_ref"] == response.quiz_id


async def test_list_and_get_quiz_for_session():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Matrices")
    repository = StubQuizRepository()
    quiz = SessionQuiz(
        id="quiz-1",
        session_id=session.id,
        topic="Matrices",
        difficulty="easy",
        question_count=1,
        skill_trace=["create_quiz"],
        created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
    )
    question = SessionQuizQuestion(
        id="qq-1",
        quiz_id="quiz-1",
        position=1,
        prompt="What is a matrix?",
        answer="A rectangular array of numbers.",
    )
    repository.quizzes[quiz.id] = quiz
    repository.questions[quiz.id] = [question]
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        session_repository=StubSessionRepository(session),
        quiz_repository=repository,
        llm_provider=StubLLMProvider(),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
    )

    summaries = await service.list_quizzes(session.id)
    detail = await service.get_quiz(session_id=session.id, quiz_id=quiz.id)

    assert len(summaries) == 1
    assert summaries[0].quiz_id == quiz.id
    assert detail.quiz_id == quiz.id
    assert detail.questions[0].prompt == "What is a matrix?"


async def test_list_quizzes_missing_session_raises_not_found():
    service = QuizService(
        db_session=FakeSession(),
        audit_service=AuditService(StubAuditRepository()),
        session_repository=StubSessionRepository(None),
        quiz_repository=StubQuizRepository(),
        llm_provider=StubLLMProvider(),
        skill_registry=SkillRegistry.from_allowed_skills(
            ["explain_concept", "create_quiz", "adaptive_hint"]
        ),
    )

    try:
        await service.list_quizzes("missing")
        assert False, "Expected NotFoundError"
    except NotFoundError:
        assert True
