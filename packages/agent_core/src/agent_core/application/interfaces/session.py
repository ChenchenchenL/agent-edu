"""Session service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.schemas.session import CreateSessionRequest, SessionResponse


class SessionServiceProtocol(Protocol):
    """Contract for session creation used by task execution."""

    async def create_session(
        self,
        payload: CreateSessionRequest,
        *,
        daily_task_id: str | None = None,
        commit: bool = True,
    ) -> SessionResponse:
        """Create a learning session."""
