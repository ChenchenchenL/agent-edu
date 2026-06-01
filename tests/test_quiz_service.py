from datetime import datetime, timezone

from agent_core.application.services.audit import AuditService
from agent_core.application.services.quiz import QuizService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.session import LearningSession
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
