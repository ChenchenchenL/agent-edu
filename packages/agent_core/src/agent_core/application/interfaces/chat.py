"""Chat service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.schemas.session import MessageRequest, MessageResponse


class ChatServiceProtocol(Protocol):
    """Contract for chat message creation."""

    async def create_message(
        self,
        *,
        session_id: str,
        payload: MessageRequest,
        commit: bool = True,
    ) -> MessageResponse:
        """Create a chat message."""
