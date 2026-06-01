from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import (
    get_chat_service,
    get_db_session,
    get_message_history_service,
    get_quiz_service,
    get_session_service,
)
from agent_core.domain.schemas.session import (
    CreateSessionRequest,
    MessageHistoryResponse,
    MessageRequest,
    MessageResponse,
    SessionResponse,
    UpdateSessionStatusRequest,
)
from agent_core.domain.schemas.quiz import (
    GenerateQuizRequest,
    QuizDetailResponse,
    QuizDraftResponse,
    QuizSummaryResponse,
)

router = APIRouter(tags=["sessions"])


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    session: AsyncSession = Depends(get_db_session),
) -> list[SessionResponse]:
    service = get_session_service(session)
    return await service.list_sessions()


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    payload: CreateSessionRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    service = get_session_service(session)
    return await service.create_session(payload)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    service = get_session_service(session)
    return await service.get_session(session_id)


@router.patch("/sessions/{session_id}/status", response_model=SessionResponse)
async def update_session_status(
    session_id: str,
    payload: UpdateSessionStatusRequest,
    session: AsyncSession = Depends(get_db_session),
) -> SessionResponse:
    service = get_session_service(session)
    return await service.update_session_status(session_id, payload)


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse)
async def create_message(
    session_id: str,
    payload: MessageRequest,
    session: AsyncSession = Depends(get_db_session),
) -> MessageResponse:
    service = get_chat_service(session)
    return await service.create_message(session_id=session_id, payload=payload)


@router.get("/sessions/{session_id}/messages", response_model=MessageHistoryResponse)
async def get_message_history(
    session_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_id: str | None = Query(default=None, max_length=36),
    session: AsyncSession = Depends(get_db_session),
) -> MessageHistoryResponse:
    service = get_message_history_service(session)
    return await service.get_message_history(session_id=session_id, limit=limit, before_id=before_id)


@router.post("/sessions/{session_id}/quizzes/generate", response_model=QuizDraftResponse)
async def generate_session_quiz(
    session_id: str,
    payload: GenerateQuizRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QuizDraftResponse:
    service = get_quiz_service(session)
    session_payload = payload.model_copy(update={"session_id": session_id})
    return await service.generate_quiz(session_payload)


@router.get("/sessions/{session_id}/quizzes", response_model=list[QuizSummaryResponse])
async def list_session_quizzes(
    session_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[QuizSummaryResponse]:
    service = get_quiz_service(session)
    return await service.list_quizzes(session_id)


@router.get("/sessions/{session_id}/quizzes/{quiz_id}", response_model=QuizDetailResponse)
async def get_session_quiz(
    session_id: str,
    quiz_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> QuizDetailResponse:
    service = get_quiz_service(session)
    return await service.get_quiz(session_id=session_id, quiz_id=quiz_id)
