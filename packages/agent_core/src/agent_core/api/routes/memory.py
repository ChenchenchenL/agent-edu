from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext, require_memory_access, require_profile_access
from agent_core.api.dependencies import get_access_context, get_db_session, get_memory_service, require_operator_api_key
from agent_core.domain.schemas.memory import (
    AnnotateMemoryRequest,
    BehaviorMemoryResponse,
    BehaviorMemoryBrowseItemResponse,
    BehaviorMemoryBrowseResponse,
    BehaviorMemoryRetrievalItemResponse,
    BehaviorMemoryRetrievalResponse,
    KnowledgeMemoryResponse,
    KnowledgeMemoryBrowseItemResponse,
    KnowledgeMemoryBrowseResponse,
    KnowledgeMemoryRetrievalItemResponse,
    KnowledgeMemoryRetrievalResponse,
    MemoryAnnotationResponse,
    MemoryConflictDetailResponse,
    MemoryConflictMemberResponse,
    MemoryConflictSetResponse,
    MemoryEvidenceLinkResponse,
    MemoryGovernanceSummaryResponse,
    MemoryGovernanceDecisionResponse,
    MemoryInterpretationResponse,
    ReflectionCorpusResponse,
    RestoreMemoryRequest,
    SuppressMemoryRequest,
)

router = APIRouter(tags=["memory"])


@router.get("/memory/knowledge/browse", response_model=KnowledgeMemoryBrowseResponse)
async def browse_knowledge_memories(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    status: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> KnowledgeMemoryBrowseResponse:
    require_profile_access(learner_profile_id, context)
    service = get_memory_service(session)
    result = await service.browse_knowledge_memories(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        statuses=set(status) if status else None,
        limit=limit,
        offset=offset,
    )
    items = [KnowledgeMemoryBrowseItemResponse.model_validate(await service.describe_knowledge_memory(item)) for item in result.items]
    return KnowledgeMemoryBrowseResponse(
        items=items,
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/memory/behavior/browse", response_model=BehaviorMemoryBrowseResponse)
async def browse_behavior_memories(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    status: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> BehaviorMemoryBrowseResponse:
    require_profile_access(learner_profile_id, context)
    service = get_memory_service(session)
    result = await service.browse_behavior_memories(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        statuses=set(status) if status else None,
        limit=limit,
        offset=offset,
    )
    items = [BehaviorMemoryBrowseItemResponse.model_validate(await service.describe_behavior_memory(item)) for item in result.items]
    return BehaviorMemoryBrowseResponse(
        items=items,
        total=result.total,
        limit=result.limit,
        offset=result.offset,
    )


@router.get("/memory/knowledge", response_model=KnowledgeMemoryRetrievalResponse)
async def retrieve_knowledge_memories(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    query_text: str = Query(min_length=1, max_length=4000),
    limit: int = Query(default=3, ge=1, le=20),
    candidate_limit: int = Query(default=24, ge=1, le=100),
    min_score: float = Query(default=0.15, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> KnowledgeMemoryRetrievalResponse:
    require_profile_access(learner_profile_id, context)
    service = get_memory_service(session)
    result = await service.retrieve_relevant_knowledge_memories(
        learner_profile_id=learner_profile_id,
        query_text=query_text,
        limit=limit,
        candidate_limit=candidate_limit,
        min_score=min_score,
    )
    return KnowledgeMemoryRetrievalResponse(
        items=[KnowledgeMemoryRetrievalItemResponse.model_validate(item) for item in result.memories],
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        candidate_count=result.candidate_count,
    )


@router.get("/memory/behavior", response_model=BehaviorMemoryRetrievalResponse)
async def retrieve_behavior_memories(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    query_text: str = Query(min_length=1, max_length=4000),
    limit: int = Query(default=3, ge=1, le=20),
    candidate_limit: int = Query(default=24, ge=1, le=100),
    min_score: float = Query(default=0.15, ge=0.0, le=1.0),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> BehaviorMemoryRetrievalResponse:
    require_profile_access(learner_profile_id, context)
    service = get_memory_service(session)
    result = await service.retrieve_relevant_behavior_memories(
        learner_profile_id=learner_profile_id,
        query_text=query_text,
        limit=limit,
        candidate_limit=candidate_limit,
        min_score=min_score,
    )
    return BehaviorMemoryRetrievalResponse(
        items=[BehaviorMemoryRetrievalItemResponse.model_validate(item) for item in result.memories],
        provider=result.provider,
        model=result.model,
        latency_ms=result.latency_ms,
        candidate_count=result.candidate_count,
    )


@router.get("/memory/knowledge/{memory_id}", response_model=KnowledgeMemoryResponse)
async def get_knowledge_memory(
    memory_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> KnowledgeMemoryResponse:
    service = get_memory_service(session)
    memory = await require_memory_access("knowledge", memory_id, context, service)
    payload = await service.describe_knowledge_memory(memory)
    if context.actor_type == "learner":
        payload = _redact_knowledge_memory_payload(payload)
    return KnowledgeMemoryResponse.model_validate(payload)


@router.get("/memory/behavior/{memory_id}", response_model=BehaviorMemoryResponse)
async def get_behavior_memory(
    memory_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> BehaviorMemoryResponse:
    service = get_memory_service(session)
    memory = await require_memory_access("behavior", memory_id, context, service)
    payload = await service.describe_behavior_memory(memory)
    if context.actor_type == "learner":
        payload = _redact_behavior_memory_payload(payload)
    return BehaviorMemoryResponse.model_validate(payload)


@router.get("/memory/{memory_type}/{memory_id}/evidence-links", response_model=list[MemoryEvidenceLinkResponse])
async def list_memory_evidence_links(
    memory_type: str,
    memory_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryEvidenceLinkResponse]:
    service = get_memory_service(session)
    return [
        MemoryEvidenceLinkResponse.model_validate(item)
        for item in await service.list_evidence_links(memory_type=memory_type, memory_id=memory_id)
    ]


@router.get("/memory/{memory_type}/{memory_id}/governance-decisions", response_model=list[MemoryGovernanceDecisionResponse])
async def list_memory_governance_decisions(
    memory_type: str,
    memory_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryGovernanceDecisionResponse]:
    service = get_memory_service(session)
    return [
        MemoryGovernanceDecisionResponse.model_validate(item)
        for item in await service.list_governance_decisions(memory_type=memory_type, memory_id=memory_id)
    ]


@router.get("/memory/{memory_type}/{memory_id}/annotations", response_model=list[MemoryAnnotationResponse])
async def list_memory_annotations(
    memory_type: str,
    memory_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryAnnotationResponse]:
    service = get_memory_service(session)
    return [
        MemoryAnnotationResponse.model_validate(item)
        for item in await service.list_annotations(memory_type=memory_type, memory_id=memory_id)
    ]


@router.get("/memory/reflection-corpus", response_model=ReflectionCorpusResponse)
async def build_reflection_corpus(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    limit_per_type: int = Query(default=8, ge=1, le=20),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionCorpusResponse:
    service = get_memory_service(session)
    result = await service.build_reflection_corpus(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        limit_per_type=limit_per_type,
    )
    return ReflectionCorpusResponse.model_validate(result)


@router.get("/memory/governance-summary", response_model=MemoryGovernanceSummaryResponse)
async def build_memory_governance_summary(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryGovernanceSummaryResponse:
    service = get_memory_service(session)
    result = await service.build_governance_summary(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
    )
    return MemoryGovernanceSummaryResponse.model_validate(result)


@router.get("/memory/interpretation", response_model=MemoryInterpretationResponse)
async def build_memory_interpretation(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    limit_per_type: int = Query(default=8, ge=1, le=20),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryInterpretationResponse:
    service = get_memory_service(session)
    result = await service.build_interpretation(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        limit_per_type=limit_per_type,
    )
    return MemoryInterpretationResponse.model_validate(result)


@router.get("/memory/conflicts", response_model=list[MemoryConflictSetResponse])
async def list_memory_conflicts(
    learner_profile_id: str = Query(min_length=1, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemoryConflictSetResponse]:
    service = get_memory_service(session)
    return [
        MemoryConflictSetResponse.model_validate(item)
        for item in await service.list_conflict_sets(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            status=status,
            limit=limit,
        )
    ]


@router.get("/memory/conflicts/{conflict_set_id}", response_model=MemoryConflictDetailResponse)
async def get_memory_conflict_detail(
    conflict_set_id: str,
    learner_profile_id: str = Query(min_length=1, max_length=36),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryConflictDetailResponse:
    service = get_memory_service(session)
    conflict_sets = await service.list_conflict_sets(
        learner_profile_id=learner_profile_id,
        status=None,
        limit=100,
    )
    conflict_set = next((item for item in conflict_sets if item.id == conflict_set_id), None)
    if conflict_set is None:
        from agent_core.domain.errors import NotFoundError

        raise NotFoundError(f"Memory conflict set '{conflict_set_id}' was not found.")
    members = await service.list_conflict_member_details(conflict_set_id=conflict_set_id)
    return MemoryConflictDetailResponse(
        conflict_set=MemoryConflictSetResponse.model_validate(conflict_set),
        members=[MemoryConflictMemberResponse.model_validate(item) for item in members],
    )


@router.post("/memory/{memory_type}/{memory_id}/suppress", response_model=KnowledgeMemoryResponse | BehaviorMemoryResponse)
async def suppress_memory(
    memory_type: str,
    memory_id: str,
    payload: SuppressMemoryRequest,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    service = get_memory_service(session)
    memory = await service.suppress_memory(
        memory_type=memory_type,
        memory_id=memory_id,
        reason_code=payload.reason_code,
        note=payload.note,
        actor_id="operator",
    )
    await session.commit()
    if memory_type == "knowledge":
        return KnowledgeMemoryResponse.model_validate(await service.describe_knowledge_memory(memory))
    return BehaviorMemoryResponse.model_validate(await service.describe_behavior_memory(memory))


@router.post("/memory/{memory_type}/{memory_id}/restore", response_model=KnowledgeMemoryResponse | BehaviorMemoryResponse)
async def restore_memory(
    memory_type: str,
    memory_id: str,
    payload: RestoreMemoryRequest,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    service = get_memory_service(session)
    memory = await service.restore_memory(
        memory_type=memory_type,
        memory_id=memory_id,
        restore_to_status=payload.restore_to_status,
        reason=payload.reason,
        actor_id="operator",
    )
    await session.commit()
    if memory_type == "knowledge":
        return KnowledgeMemoryResponse.model_validate(await service.describe_knowledge_memory(memory))
    return BehaviorMemoryResponse.model_validate(await service.describe_behavior_memory(memory))


@router.post("/memory/{memory_type}/{memory_id}/annotate", response_model=MemoryAnnotationResponse)
async def annotate_memory(
    memory_type: str,
    memory_id: str,
    payload: AnnotateMemoryRequest,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> MemoryAnnotationResponse:
    service = get_memory_service(session)
    annotation = await service.annotate_memory(
        memory_type=memory_type,
        memory_id=memory_id,
        annotation_code=payload.annotation_code,
        note=payload.note,
        actor_id="operator",
    )
    await session.commit()
    return MemoryAnnotationResponse.model_validate(annotation)


def _redact_knowledge_memory_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "details": None,
        "source_event_ids": [],
        "source_memory_ids": [],
        "provenance_source_id": None,
        "scope_ref": {},
        "promotion_rationale": None,
        "suppressed_reason_code": None,
        "suppressed_reason_note": None,
        "suppressed_by": None,
        "suppressed_at": None,
    }


def _redact_behavior_memory_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "details": None,
        "source_event_ids": [],
        "source_memory_ids": [],
        "provenance_source_id": None,
        "scope_ref": {},
        "promotion_rationale": None,
        "suppressed_reason_code": None,
        "suppressed_reason_note": None,
        "suppressed_by": None,
        "suppressed_at": None,
    }
