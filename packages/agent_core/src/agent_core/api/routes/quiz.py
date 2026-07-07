from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext
from agent_core.api.dependencies import (
    get_access_context,
    get_db_session,
    get_quiz_observability_service,
    get_quiz_service,
)
from agent_core.domain.schemas.quiz import (
    AdaptivePolicyAuditTrailResponse,
    GenerateQuizRequest,
    LearnerQuizAttemptHistoryResponse,
    LearningGainDashboardResponse,
    MisconceptionTrendResponse,
    OperatorAttemptBrowseResponse,
    OperatorGradingQueueResponse,
    QuizAdaptationRationaleResponse,
    QuizDraftResponse,
    RecommendedNextActionResponse,
    TopicMasteryResponse,
)

router = APIRouter(tags=["quiz"])


@router.post("/quizzes/generate", response_model=QuizDraftResponse)
async def generate_quiz(
    payload: GenerateQuizRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QuizDraftResponse:
    service = get_quiz_service(session)
    return await service.generate_quiz(payload)


# ---------------------------------------------------------------------------
# 11.1 Learner-Facing API
# ---------------------------------------------------------------------------


@router.get("/quizzes/attempts/history", response_model=LearnerQuizAttemptHistoryResponse)
async def get_quiz_attempt_history(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerQuizAttemptHistoryResponse:
    if context.actor_type != "learner":
        raise HTTPException(status_code=403, detail="Learner access required")

    service = get_quiz_observability_service(session)
    attempts = await service.get_learner_attempt_history(
        learner_profile_id=context.learner_profile_id,
        limit=limit,
        offset=offset,
    )
    return LearnerQuizAttemptHistoryResponse(attempts=attempts)


@router.get("/learner/mastery/{topic_key}", response_model=TopicMasteryResponse)
async def get_current_topic_mastery(
    topic_key: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> TopicMasteryResponse:
    if context.actor_type != "learner":
        raise HTTPException(status_code=403, detail="Learner access required")

    service = get_quiz_observability_service(session)
    return await service.get_learner_topic_mastery(
        learner_profile_id=context.learner_profile_id,
        topic_key=topic_key,
    )


@router.get("/quizzes/next-action", response_model=RecommendedNextActionResponse)
async def get_next_recommended_action(
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> RecommendedNextActionResponse:
    if context.actor_type != "learner":
        raise HTTPException(status_code=403, detail="Learner access required")

    service = get_quiz_observability_service(session)
    return await service.get_learner_next_action(
        learner_profile_id=context.learner_profile_id,
    )


@router.get("/quizzes/rationale/{quiz_id}", response_model=QuizAdaptationRationaleResponse)
async def get_quiz_adaptation_rationale(
    quiz_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> QuizAdaptationRationaleResponse:
    if context.actor_type != "learner":
        raise HTTPException(status_code=403, detail="Learner access required")

    service = get_quiz_observability_service(session)
    rationale = await service.get_quiz_adaptation_rationale(
        learner_profile_id=context.learner_profile_id,
        quiz_id=quiz_id,
    )
    if rationale is None:
        raise HTTPException(status_code=404, detail="Quiz not found or access denied")

    return QuizAdaptationRationaleResponse(
        quiz_id=quiz_id,
        adaptation_rationale=rationale,
    )


# ---------------------------------------------------------------------------
# 11.2 Operator-Facing API
# ---------------------------------------------------------------------------


@router.get("/operator/quizzes/attempts", response_model=OperatorAttemptBrowseResponse)
async def browse_answer_attempts(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> OperatorAttemptBrowseResponse:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")

    service = get_quiz_observability_service(session)
    attempts, total_count = await service.browse_operator_attempts(
        limit=limit, offset=offset
    )
    return OperatorAttemptBrowseResponse(attempts=attempts, total_count=total_count)


@router.get("/operator/quizzes/grading/needs-review", response_model=OperatorGradingQueueResponse)
async def get_grading_needs_review_queue(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> OperatorGradingQueueResponse:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")

    service = get_quiz_observability_service(session)
    queue = await service.get_operator_grading_queue(limit=limit, offset=offset)
    return OperatorGradingQueueResponse(queue=queue)


@router.get("/operator/quizzes/misconceptions/trend", response_model=MisconceptionTrendResponse)
async def get_misconception_trend(
    limit: int = Query(default=1000, ge=1, le=10000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> MisconceptionTrendResponse:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")

    service = get_quiz_observability_service(session)
    trends = await service.get_operator_misconception_trend(limit=limit)
    return MisconceptionTrendResponse(trends=trends)


@router.get("/operator/quizzes/adaptive-policy/audit", response_model=AdaptivePolicyAuditTrailResponse)
async def get_adaptive_policy_audit_trail(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> AdaptivePolicyAuditTrailResponse:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")

    service = get_quiz_observability_service(session)
    audit_trail = await service.get_operator_adaptive_policy_audit(
        limit=limit, offset=offset
    )
    return AdaptivePolicyAuditTrailResponse(audit_trail=audit_trail)


@router.get("/operator/skills/learning-gain", response_model=LearningGainDashboardResponse)
async def get_skill_learning_gain_dashboard(
    limit: int = Query(default=1000, ge=1, le=10000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearningGainDashboardResponse:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access required")

    service = get_quiz_observability_service(session)
    learning_gains = await service.get_operator_learning_gain_dashboard(limit=limit)
    return LearningGainDashboardResponse(learning_gains=learning_gains)
