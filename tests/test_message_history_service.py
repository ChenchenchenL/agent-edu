from datetime import datetime, timezone

from agent_core.application.services.message_history import MessageHistoryService
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.schemas.session import ExplanationPayload
from agent_core.domain.errors import NotFoundError, ValidationError


class StubSessionRepository:
    def __init__(self, session_entity):
        self.session_entity = session_entity

    async def get_by_id(self, session_id):
        if self.session_entity and self.session_entity.id == session_id:
            return self.session_entity
        return None


class StubMessageRepository:
    def __init__(self, messages):
        self.messages = list(messages)

    async def count_by_session(self, session_id):
        return len([item for item in self.messages if item.session_id == session_id])

    async def list_history(self, *, session_id, limit, before_id):
        filtered = [item for item in self.messages if item.session_id == session_id]
        if before_id is not None:
            index = None
            for position, item in enumerate(filtered):
                if item.id == before_id:
                    index = position
                    break
            if index is None:
                raise ValidationError("Invalid before_id for the requested session.")
            filtered = filtered[:index]

        filtered = filtered[-(limit + 1):]
        return filtered


def make_message(message_id, session_id, role, content, created_at):
    return SessionMessage(
        id=message_id,
        session_id=session_id,
        role=role,
        content=content,
        content_payload=(
            ExplanationPayload(
                definition="d",
                core_principles=["p"],
                worked_example="e",
                common_mistake="m",
                next_step="n",
            ).model_dump()
            if role == "assistant"
            else None
        ),
        mode="chat" if role == "user" else "assistant",
        skill_trace=["explain_concept"] if role == "assistant" else [],
        created_at=created_at,
    )


async def test_message_history_returns_sorted_page_with_total_and_cursor():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Vectors")
    messages = [
        make_message("m1", session.id, "user", "First", datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)),
        make_message("m2", session.id, "assistant", "Second", datetime(2026, 5, 19, 8, 1, tzinfo=timezone.utc)),
        make_message("m3", session.id, "user", "Third", datetime(2026, 5, 19, 8, 2, tzinfo=timezone.utc)),
    ]
    service = MessageHistoryService(
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(messages),
    )

    response = await service.get_message_history(session_id=session.id, limit=2, before_id=None)

    assert response.total == 3
    assert [item.id for item in response.items] == ["m2", "m3"]
    assert response.next_before_id == "m2"
    assert response.items[0].content_payload is not None


async def test_message_history_before_cursor_returns_older_page():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Vectors")
    messages = [
        make_message("m1", session.id, "user", "First", datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)),
        make_message("m2", session.id, "assistant", "Second", datetime(2026, 5, 19, 8, 1, tzinfo=timezone.utc)),
        make_message("m3", session.id, "user", "Third", datetime(2026, 5, 19, 8, 2, tzinfo=timezone.utc)),
    ]
    service = MessageHistoryService(
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(messages),
    )

    response = await service.get_message_history(session_id=session.id, limit=2, before_id="m2")

    assert response.total == 3
    assert [item.id for item in response.items] == ["m1"]
    assert response.next_before_id is None


async def test_message_history_empty_session_returns_empty_items():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Vectors")
    service = MessageHistoryService(
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository([]),
    )

    response = await service.get_message_history(session_id=session.id, limit=20, before_id=None)

    assert response.total == 0
    assert response.items == []
    assert response.next_before_id is None


async def test_message_history_missing_session_raises_not_found():
    service = MessageHistoryService(
        session_repository=StubSessionRepository(None),
        message_repository=StubMessageRepository([]),
    )

    try:
        await service.get_message_history(session_id="missing", limit=20, before_id=None)
        assert False, "Expected NotFoundError"
    except NotFoundError:
        assert True


async def test_message_history_invalid_before_id_raises_validation_error():
    session = LearningSession.build(learner_profile_id="profile-1", title="Linear Algebra", subject="Vectors")
    messages = [
        make_message("m1", session.id, "user", "First", datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc)),
    ]
    service = MessageHistoryService(
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository(messages),
    )

    try:
        await service.get_message_history(session_id=session.id, limit=20, before_id="missing-cursor")
        assert False, "Expected ValidationError"
    except ValidationError:
        assert True
