from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import get_db_session, get_quiz_service
from agent_core.domain.schemas.quiz import GenerateQuizRequest, QuizDraftResponse

router = APIRouter(tags=["quiz"])


@router.post("/quizzes/generate", response_model=QuizDraftResponse)
async def generate_quiz(
    payload: GenerateQuizRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QuizDraftResponse:
    service = get_quiz_service(session)
    return await service.generate_quiz(payload)
