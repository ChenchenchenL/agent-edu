from __future__ import annotations

from agent_core.domain.errors import NotFoundError
from agent_core.domain.schemas.session import MessageHistoryResponse
from agent_core.infrastructure.db.repositories import SessionMessageRepository, SessionRepository


class MessageHistoryService:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        message_repository: SessionMessageRepository,
    ) -> None:
        self._session_repository = session_repository
        self._message_repository = message_repository

    async def get_message_history(
        self,
        *,
        session_id: str,
        limit: int,
        before_id: str | None,
    ) -> MessageHistoryResponse:
        session = await self._session_repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")

        total = await self._message_repository.count_by_session(session_id)
        items = await self._message_repository.list_history(
            session_id=session_id,
            limit=limit,
            before_id=before_id,
        )
        has_more = len(items) > limit
        visible_items = items[-limit:] if has_more else items
        next_before_id = visible_items[0].id if has_more and visible_items else None

        return MessageHistoryResponse(
            items=visible_items,
            total=total,
            next_before_id=next_before_id,
        )
