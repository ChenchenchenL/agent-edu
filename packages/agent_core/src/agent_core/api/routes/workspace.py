from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext, require_goal_access, require_profile_access
from agent_core.api.dependencies import get_access_context, get_db_session, get_workspace_service
from agent_core.domain.schemas.workspace import WorkspaceSummaryResponse

router = APIRouter(tags=["workspace"])


@router.get("/learner-profiles/{profile_id}/workspace", response_model=WorkspaceSummaryResponse)
async def get_workspace_summary(
    profile_id: str,
    goal_id: str | None = Query(default=None, max_length=36),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> WorkspaceSummaryResponse:
    require_profile_access(profile_id, context)
    if goal_id is not None:
        await require_goal_access(goal_id, context, session, expected_profile_id=profile_id)
    service = get_workspace_service(session)
    return await service.get_workspace_summary(learner_profile_id=profile_id, learner_goal_id=goal_id)
