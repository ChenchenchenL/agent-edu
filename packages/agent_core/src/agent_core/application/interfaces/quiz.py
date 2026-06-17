"""Quiz service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.domain.schemas.quiz import GenerateQuizRequest, QuizDraftResponse


class QuizServiceProtocol(Protocol):
    """Contract for quiz generation."""

    async def generate_quiz(
        self,
        payload: GenerateQuizRequest,
        *,
        commit: bool = True,
    ) -> QuizDraftResponse:
        """Generate a quiz for a session."""
