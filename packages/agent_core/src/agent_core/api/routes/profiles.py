from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext, require_profile_access
from agent_core.api.dependencies import get_access_context, get_db_session, get_profile_service, require_operator_api_key
from agent_core.domain.schemas.goal import CreateLearnerProfileRequest, CreateLearnerProfileResponse, LearnerProfileResponse

router = APIRouter(tags=["learner_profiles"])


@router.post("/learner-profiles", response_model=CreateLearnerProfileResponse)
async def create_learner_profile(
    _: CreateLearnerProfileRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CreateLearnerProfileResponse:
    service = get_profile_service(session)
    return await service.create_profile()


@router.get("/learner-profiles", response_model=list[LearnerProfileResponse])
async def list_learner_profiles(
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[LearnerProfileResponse]:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access is required.")
    service = get_profile_service(session)
    return await service.list_profiles()


@router.get("/learner-profiles/{profile_id}", response_model=LearnerProfileResponse)
async def get_learner_profile(
    profile_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerProfileResponse:
    require_profile_access(profile_id, context)
    service = get_profile_service(session)
    return await service.get_profile(profile_id)


@router.post("/learner-profiles/{profile_id}/access-key/rotate", response_model=CreateLearnerProfileResponse)
async def rotate_learner_profile_access_key(
    profile_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> CreateLearnerProfileResponse:
    service = get_profile_service(session)
    return await service.rotate_access_key(profile_id)
