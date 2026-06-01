from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryReplayScheduleResult,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.skill import SkillResolution
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.session import MessageRequest, MessageResponse, MessageTurnMetrics
from agent_core.infrastructure.db.repositories import SessionMessageRepository, SessionQuizRepository, SessionRepository
from agent_core.infrastructure.llm.types import HintContext, LLMProvider, SessionLearnerProfile
from agent_core.infrastructure.observability.metrics import (
    observe_embedding_operation,
    observe_llm_operation,
    observe_long_term_memory_materialization,
)


class ChatService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        session_repository: SessionRepository,
        message_repository: SessionMessageRepository,
        quiz_repository: SessionQuizRepository,
        memory_service: MemoryService,
        long_term_memory_materialization_service: LongTermMemoryMaterializationService | None = None,
        long_term_memory_replay_scheduler: LongTermMemoryMaterializationReplayScheduler | None = None,
        audit_service: AuditService,
        llm_provider: LLMProvider,
        skill_registry: SkillRegistry,
        reflection_evidence_service: ReflectionEvidenceService | None = None,
        strategy_card_service: StrategyCardService | None = None,
        rollout_resolver: ReflectionProposalRolloutResolver | None = None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
        skill_usage_service: SkillUsageService | None = None,
    ) -> None:
        self._db_session = db_session
        self._session_repository = session_repository
        self._message_repository = message_repository
        self._quiz_repository = quiz_repository
        self._memory_service = memory_service
        self._long_term_memory_materialization_service = long_term_memory_materialization_service
        self._long_term_memory_replay_scheduler = long_term_memory_replay_scheduler
        self._reflection_evidence_service = reflection_evidence_service
        self._strategy_card_service = strategy_card_service
        self._rollout_resolver = rollout_resolver
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._skill_usage_service = skill_usage_service
        self._audit_service = audit_service
        self._llm_provider = llm_provider
        self._skill_registry = skill_registry

    async def create_message(
        self,
        *,
        session_id: str,
        payload: MessageRequest,
        commit: bool = True,
    ) -> MessageResponse:
        session = await self._session_repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")

        skills = self._skill_registry.trace_for_mode(payload.mode)
        skill_resolution = await self._resolve_skill_for_runtime(
            skill_name=skills[0],
            surface=payload.mode,
            resource_id=session.id,
        )
        history = await self._message_repository.list_history(
            session_id=session.id,
            limit=8,
            before_id=None,
        )
        all_sessions = await self._session_repository.list_sessions()
        past_sessions = [item for item in all_sessions if item.id != session.id]
        cross_session_context = self._build_cross_session_context(past_sessions=past_sessions)
        hint_context = await self._build_hint_context(
            session_id=session.id,
            learner_goal_id=session.learner_goal_id,
            payload=payload,
            history=history,
        )
        try:
            retrieval_result = await self._memory_service.retrieve_relevant_session_memories(
                session_id=session.id,
                query_text=payload.content,
                limit=3,
                candidate_limit=24,
            )
        except Exception as exc:
            observe_embedding_operation(
                operation="session_memory_retrieval",
                provider=self._memory_service.embedding_provider_name,
                status="failed",
                latency_ms=0,
            )
            await self._audit_service.record_durable(
                event_type="embedding.query.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": self._memory_service.embedding_provider_name,
                    "model": self._memory_service.embedding_model_name,
                    "operation": "memory_retrieval",
                    "status": "failed",
                    "latency_ms": 0,
                    "retry_count": 0,
                    "session_id": session.id,
                    "response_shape_valid": False,
                    "usage": None,
                    "error": str(exc),
                    "history_count": len(history),
                    "cross_session_context_count": len(cross_session_context),
                },
            )
            await self._record_skill_usage(
                skill_name=skills[0] if skills else ("adaptive_hint" if payload.mode == "hint" else "explain_concept"),
                surface=payload.mode,
                outcome_status="failed",
                session=session,
                latency_ms=0,
                input_summary=payload.content,
                error_code=type(exc).__name__,
                resolution=skill_resolution,
                metadata={"operation": "chat" if payload.mode == "chat" else "hint"},
            )
            if commit:
                await self._db_session.commit()
            raise
        observe_embedding_operation(
            operation="session_memory_retrieval",
            provider=retrieval_result.provider,
            status="completed",
            latency_ms=retrieval_result.latency_ms,
        )
        try:
            profile_retrieval_result = await self._memory_service.retrieve_relevant_profile_memories(
                learner_profile_id=session.learner_profile_id,
                query_text=payload.content,
                limit=3,
                candidate_limit=24,
            )
        except Exception as exc:
            observe_embedding_operation(
                operation="profile_memory_retrieval",
                provider=self._memory_service.embedding_provider_name,
                status="failed",
                latency_ms=0,
            )
            await self._audit_service.record_durable(
                event_type="embedding.query.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": self._memory_service.embedding_provider_name,
                    "model": self._memory_service.embedding_model_name,
                    "operation": "profile_memory_retrieval",
                    "status": "failed",
                    "latency_ms": 0,
                    "retry_count": 0,
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "response_shape_valid": False,
                    "usage": None,
                    "error": str(exc),
                    "history_count": len(history),
                    "cross_session_context_count": len(cross_session_context),
                    "profile_retrieved_count": 0,
                },
            )
            profile_retrieval_result = retrieval_result.__class__(
                memories=[],
                provider=retrieval_result.provider,
                model=retrieval_result.model,
                latency_ms=0,
                candidate_count=0,
            )
        else:
            observe_embedding_operation(
                operation="profile_memory_retrieval",
                provider=profile_retrieval_result.provider,
                status="completed",
                latency_ms=profile_retrieval_result.latency_ms,
            )
        long_term_context = cross_session_context + [item.summary for item in profile_retrieval_result.memories]
        strategy_card = (
            await self._strategy_card_service.get_active(session.learner_goal_id)
            if self._strategy_card_service is not None and session.learner_goal_id is not None
            else None
        )
        rollout_overlay = None
        if self._rollout_resolver is not None and session.learner_goal_id is not None:
            rollout_overlay = await self._rollout_resolver.get_active_overlay(
                learner_goal_id=session.learner_goal_id,
                surface=payload.mode,
                include_staged=True,
            )
        skill_binding = None
        if self._goal_skill_binding_resolver is not None and session.learner_goal_id is not None:
            skill_binding = await self._goal_skill_binding_resolver.get_active_binding(
                learner_goal_id=session.learner_goal_id,
                surface=payload.mode or "chat",
                topic_key=session.subject,
                trigger_source=payload.mode,
                include_staged=True,
            )
        learner_profile = self._build_learner_profile(
            session_title=session.title,
            subject=session.subject,
            payload=payload,
            history=history,
            memory_contexts=[item.summary for item in retrieval_result.memories],
            long_term_context=long_term_context,
            strategy_card=strategy_card,
            rollout_overlay_payload=dict(rollout_overlay.payload) if rollout_overlay is not None else None,
            skill_directives=list(skill_binding.runtime_directives.get("skill_directives") or []) if skill_binding is not None else None,
        )
        try:
            reply = await self._llm_provider.generate_tutor_reply(
                session_title=session.title,
                subject=session.subject,
                learner_message=payload.content,
                mode=payload.mode,
                history=history[-8:],
                memory_contexts=[item.summary for item in retrieval_result.memories],
                learner_profile=learner_profile,
                hint_context=hint_context,
            )
        except Exception as exc:
            observe_llm_operation(
                operation="chat" if payload.mode == "chat" else "hint",
                provider=getattr(self._llm_provider, "provider_name", "unknown"),
                status="failed",
                latency_ms=0,
            )
            await self._audit_service.record_durable(
                event_type="llm.chat.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": getattr(self._llm_provider, "provider_name", "unknown"),
                    "model": getattr(self._llm_provider, "model_name", None),
                    "operation": "chat" if payload.mode == "chat" else "hint",
                    "status": "failed",
                    "latency_ms": 0,
                    "retry_count": 0,
                    "session_id": session.id,
                    "response_shape_valid": False,
                    "usage": None,
                    "error": str(exc),
                    "history_count": len(history),
                    "memory_context_count": len(retrieval_result.memories) if "retrieval_result" in locals() else 0,
                    "cross_session_context_count": len(long_term_context),
                },
            )
            await self._record_skill_usage(
                skill_name=skills[0],
                surface=payload.mode,
                outcome_status="failed",
                session=session,
                latency_ms=0,
                input_summary=payload.content,
                error_code=type(exc).__name__,
                resolution=skill_resolution,
                metadata={
                    "operation": "chat" if payload.mode == "chat" else "hint",
                    "history_count": len(history),
                    "memory_context_count": len(retrieval_result.memories),
                    "response_shape_valid": False,
                },
            )
            if commit:
                await self._db_session.commit()
            raise
        observe_llm_operation(
            operation="chat" if payload.mode == "chat" else "hint",
            provider=reply.provider,
            status="completed",
            latency_ms=reply.latency_ms,
        )

        user_message = SessionMessage.build(
            session_id=session.id,
            role="user",
            content=payload.content,
            mode=payload.mode,
            skill_trace=[],
        )
        assistant_message = SessionMessage.build(
            session_id=session.id,
            role="assistant",
            content=reply.content,
            content_payload=reply.payload.model_dump(),
            mode=payload.mode,
            skill_trace=skills,
        )

        updated_session = session.with_message_activity(
            message_count_delta=2,
            last_activity_at=assistant_message.created_at,
            summary=self._build_session_summary(session_title=session.title, subject=session.subject, payload=payload),
        )
        turn_metrics = MessageTurnMetrics(
            history_count=len(history),
            memory_context_count=len(retrieval_result.memories),
            cross_session_context_count=len(long_term_context),
            hint_level=hint_context.hint_level if hint_context is not None else None,
            hint_history_count=hint_context.prior_hint_count if hint_context is not None else 0,
            used_quiz_context=hint_context.reference_answer is not None if hint_context is not None else False,
            used_error_analysis=bool(hint_context.mistake_analysis) if hint_context is not None else False,
            retrieval_latency_ms=retrieval_result.latency_ms,
            llm_latency_ms=reply.latency_ms,
            llm_retry_count=reply.retry_count,
            response_shape_valid=reply.response_shape_valid,
        )

        try:
            await self._message_repository.create(user_message)
            await self._message_repository.create(assistant_message)
            await self._session_repository.update(updated_session)
            memory_events = await self._memory_service.record_learning_memories(
                session_id=session.id,
                learner_profile_id=session.learner_profile_id,
                learner_message=payload.content,
                assistant_message=assistant_message.content,
                source_message_id=user_message.id,
                mode=payload.mode,
                subject=session.subject,
                session_title=session.title,
            )
            if self._long_term_memory_materialization_service is not None:
                await self._materialize_chat_turn_isolated(
                    session=session,
                    learner_message=payload.content,
                    assistant_message=assistant_message.content,
                    source_message_id=user_message.id,
                    assistant_message_id=assistant_message.id,
                    mode=payload.mode,
                    memory_events=memory_events,
                )
            await self._audit_service.record(
                event_type="session.message.user_created",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "message_id": user_message.id,
                    "role": "user",
                    "mode": payload.mode,
                    "hint_level": hint_context.hint_level if hint_context is not None else None,
                    "learner_profile_id": session.learner_profile_id,
                },
            )
            await self._audit_service.record(
                event_type="embedding.query.completed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": retrieval_result.provider,
                    "model": retrieval_result.model,
                    "operation": "memory_retrieval",
                    "status": "completed",
                    "latency_ms": retrieval_result.latency_ms,
                    "retry_count": 0,
                    "session_id": session.id,
                    "response_shape_valid": True,
                    "usage": None,
                    "candidate_count": retrieval_result.candidate_count,
                    "retrieved_count": len(retrieval_result.memories),
                    "history_count": len(history),
                    "cross_session_context_count": len(long_term_context),
                    "hint_level": hint_context.hint_level if hint_context is not None else None,
                    "profile_retrieved_count": len(profile_retrieval_result.memories),
                },
            )
            await self._audit_service.record(
                event_type="llm.chat.completed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": reply.provider,
                    "model": reply.model,
                    "operation": "chat" if payload.mode == "chat" else "hint",
                    "status": "completed",
                    "latency_ms": reply.latency_ms,
                    "retry_count": reply.retry_count,
                    "session_id": session.id,
                    "response_shape_valid": reply.response_shape_valid,
                    "usage": None,
                    "history_count": len(history),
                    "memory_context_count": len(retrieval_result.memories),
                    "cross_session_context_count": len(long_term_context),
                    "hint_level": hint_context.hint_level if hint_context is not None else None,
                    "hint_history_count": hint_context.prior_hint_count if hint_context is not None else 0,
                    "used_quiz_context": hint_context.reference_answer is not None if hint_context is not None else False,
                    "used_error_analysis": bool(hint_context.mistake_analysis) if hint_context is not None else False,
                    "direct_answer_given": getattr(reply.payload, "direct_answer_given", False),
                    "learner_profile_id": session.learner_profile_id,
                },
            )
            await self._audit_service.record(
                event_type="memory.events.recorded",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "count": len(memory_events),
                    "memory_scopes": [item.memory_scope for item in memory_events],
                    "memory_levels": [item.memory_level for item in memory_events],
                },
            )
            await self._audit_service.record(
                event_type="session.message.assistant_created",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "message_id": assistant_message.id,
                    "role": "assistant",
                    "mode": payload.mode,
                    "skill_trace": skills,
                    "hint_level": hint_context.hint_level if hint_context is not None else None,
                    "learner_profile_id": session.learner_profile_id,
                },
            )
            await self._record_skill_usage(
                skill_name=skills[0],
                surface=payload.mode,
                outcome_status="completed",
                session=session,
                latency_ms=reply.latency_ms,
                input_summary=payload.content,
                output_summary=assistant_message.content,
                resolution=skill_resolution,
                metadata={
                    "user_message_id": user_message.id,
                    "assistant_message_id": assistant_message.id,
                    "response_shape_valid": reply.response_shape_valid,
                    "retry_count": reply.retry_count,
                    "provider": reply.provider,
                    "model": reply.model,
                },
            )
            if (
                self._reflection_evidence_service is not None
                and session.learner_goal_id is not None
            ):
                await self._reflection_evidence_service.derive_from_session_turn(
                    learner_profile_id=session.learner_profile_id,
                    learner_goal_id=session.learner_goal_id,
                    session_id=session.id,
                    turn_metrics=turn_metrics.model_dump(),
                    learner_message=user_message,
                )
            if (
                self._rollout_observation_scheduler is not None
                and session.learner_goal_id is not None
                and payload.mode in {"chat", "hint"}
            ):
                await self._rollout_observation_scheduler.schedule_active(
                    learner_goal_id=session.learner_goal_id,
                    surface=payload.mode,
                    trigger_source="session_turn_completed",
                    source_ref=assistant_message.id,
                )
            if commit:
                await self._db_session.commit()
        except Exception:
            await self._db_session.rollback()
            raise

        return MessageResponse(
            session_id=session.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            assistant_message=assistant_message.content,
            assistant_payload=reply.payload,
            skill_trace=skills,
            turn_metrics=turn_metrics,
        )

    async def _resolve_skill_for_runtime(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str,
    ) -> SkillResolution | None:
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )

    async def _record_skill_usage(
        self,
        *,
        skill_name: str,
        surface: str,
        outcome_status: str,
        session: LearningSession,
        latency_ms: int | None,
        input_summary: str | None,
        output_summary: str | None = None,
        error_code: str | None = None,
        resolution: SkillResolution | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self._skill_usage_service is None:
            return
        await self._skill_usage_service.record_usage(
            skill_name=skill_name,
            surface=surface,
            outcome_status=outcome_status,
            learner_profile_id=session.learner_profile_id,
            learner_goal_id=session.learner_goal_id,
            session_id=session.id,
            daily_task_id=session.daily_task_id,
            topic_key=session.subject,
            trigger_source="session_message",
            latency_ms=latency_ms,
            input_summary=input_summary,
            output_summary=output_summary,
            error_code=error_code,
            resolution=resolution,
            metadata=metadata,
        )

    async def _materialize_chat_turn_isolated(
        self,
        *,
        session: LearningSession,
        learner_message: str,
        assistant_message: str,
        source_message_id: str,
        assistant_message_id: str,
        mode: str | None,
        memory_events: list[MemoryEvent],
    ) -> None:
        if self._long_term_memory_materialization_service is None:
            return
        try:
            begin_nested = getattr(self._db_session, "begin_nested", None)
            if begin_nested is None:
                await self._long_term_memory_materialization_service.materialize_from_chat_turn(
                    session_id=session.id,
                    learner_profile_id=session.learner_profile_id,
                    learner_goal_id=session.learner_goal_id,
                    learner_message=learner_message,
                    assistant_message=assistant_message,
                    source_message_id=source_message_id,
                    mode=mode,
                    subject=session.subject,
                    session_title=session.title,
                    memory_events=memory_events,
                    persist_embeddings=True,
                )
            else:
                async with begin_nested():
                    await self._long_term_memory_materialization_service.materialize_from_chat_turn(
                        session_id=session.id,
                        learner_profile_id=session.learner_profile_id,
                        learner_goal_id=session.learner_goal_id,
                        learner_message=learner_message,
                        assistant_message=assistant_message,
                        source_message_id=source_message_id,
                        mode=mode,
                        subject=session.subject,
                        session_title=session.title,
                        memory_events=memory_events,
                        persist_embeddings=True,
                    )
        except Exception as exc:
            observe_long_term_memory_materialization(
                source_type="chat_turn",
                status="failed",
                reason_code=type(exc).__name__,
            )
            replay = await self._schedule_chat_materialization_replay(
                session=session,
                source_message_id=source_message_id,
                assistant_message_id=assistant_message_id,
            )
            event_data = {
                "source_type": "chat_turn",
                "session_id": session.id,
                "learner_profile_id": session.learner_profile_id,
                "learner_goal_id": session.learner_goal_id,
                "source_message_id": source_message_id,
                "assistant_message_id": assistant_message_id,
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
            event_data.update(replay.audit_payload())
            await self._audit_service.record_durable(
                event_type="long_term_memory.materialization.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data=event_data,
            )

    async def _schedule_chat_materialization_replay(
        self,
        *,
        session: LearningSession,
        source_message_id: str,
        assistant_message_id: str,
    ) -> LongTermMemoryReplayScheduleResult:
        if self._long_term_memory_replay_scheduler is None:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:chat_turn:{session.id}:{source_message_id}:{assistant_message_id}",
                due_at=None,
                skip_reason="replay_scheduler_unconfigured",
            )
        try:
            return await self._long_term_memory_replay_scheduler.schedule_chat_turn(
                learner_goal_id=session.learner_goal_id,
                session_id=session.id,
                user_message_id=source_message_id,
                assistant_message_id=assistant_message_id,
            )
        except Exception as replay_exc:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:chat_turn:{session.id}:{source_message_id}:{assistant_message_id}",
                due_at=None,
                skip_reason="replay_enqueue_failed",
                error_code=type(replay_exc).__name__,
                error=str(replay_exc),
            )

    @staticmethod
    def _build_session_summary(*, session_title: str | None, subject: str | None, payload: MessageRequest) -> str:
        topic = subject or session_title or "current topic"
        mode = payload.mode or "chat"
        learner_focus = payload.content[:80].strip()
        return f"Working on {topic}: learner asked about {learner_focus} ({mode})."

    @staticmethod
    def _build_learner_profile(
        *,
        session_title: str | None,
        subject: str | None,
        payload: MessageRequest,
        history: list[SessionMessage],
        memory_contexts: list[str],
        long_term_context: list[str],
        strategy_card=None,
        rollout_overlay_payload: dict[str, object] | None = None,
        skill_directives: list[str] | None = None,
    ) -> SessionLearnerProfile:
        learner_turns = [item for item in history if item.role == "user"][-3:]
        hint_turns = [item for item in learner_turns if item.mode == "hint"]
        long_term_hint_turns = [
            item for item in long_term_context if "(hint)" in item.casefold() or "hint" in item.casefold()
        ]
        response_preference = (
            "guided"
            if len(hint_turns) > len(learner_turns) / 2 or len(long_term_hint_turns) > len(long_term_context) / 2
            else "explanatory"
        )
        if strategy_card is not None:
            if strategy_card.primary_instruction_mode == "guided":
                response_preference = "guided"
            elif strategy_card.primary_instruction_mode == "explanatory":
                response_preference = "explanatory"
        if rollout_overlay_payload is not None and rollout_overlay_payload.get("response_preference") in {"guided", "explanatory"}:
            response_preference = str(rollout_overlay_payload["response_preference"])
        known_context = []
        if subject:
            known_context.append(f"Session subject: {subject}")
        if session_title:
            known_context.append(f"Session title: {session_title}")
        known_context.extend(memory_contexts[:2])
        known_context.extend(long_term_context[:1])
        recent_struggles = memory_contexts[:3]
        if not recent_struggles:
            recent_struggles = long_term_context[:3]
        if not recent_struggles:
            recent_struggles = [payload.content[:120].strip()]

        return SessionLearnerProfile(
            current_topic=subject or session_title or "current learning topic",
            response_preference=response_preference,
            recent_struggles=recent_struggles,
            known_context=known_context[:3],
            long_term_context=long_term_context[:4],
            teaching_goal=(
                str(rollout_overlay_payload["teaching_goal"])
                if rollout_overlay_payload is not None and rollout_overlay_payload.get("teaching_goal")
                else (
                    "unblock next step"
                    if payload.mode == "hint" or (strategy_card is not None and strategy_card.primary_instruction_mode == "guided")
                    else "explain and clarify"
                )
            ),
            skill_directives=list(skill_directives or []),
        )

    @staticmethod
    def _build_cross_session_context(*, past_sessions: list[LearningSession]) -> list[str]:
        context: list[str] = []
        for session in past_sessions[:5]:
            if session.summary is None:
                continue
            topic = session.subject or session.title or "previous topic"
            context.append(f"Earlier session on {topic}: {session.summary}")
        return context

    async def _build_hint_context(
        self,
        *,
        session_id: str,
        learner_goal_id: str | None,
        payload: MessageRequest,
        history: list[SessionMessage],
    ) -> HintContext | None:
        if payload.mode != "hint":
            return None

        prior_hint_count = len([item for item in history if item.role == "assistant" and item.mode == "hint"])
        reference_answer = None
        if payload.related_quiz_id is not None:
            stored = await self._quiz_repository.get_quiz_with_questions(
                session_id=session_id,
                quiz_id=payload.related_quiz_id,
            )
            if payload.question_prompt is None:
                if len(stored.questions) != 1:
                    raise ValidationError("question_prompt is required when the referenced quiz has multiple questions.")
                question = stored.questions[0]
            else:
                question = next(
                    (item for item in stored.questions if item.prompt == payload.question_prompt),
                    None,
                )
                if question is None:
                    raise ValidationError("question_prompt was not found in the referenced quiz.")
            reference_answer = question.answer
            question_prompt = question.prompt
        else:
            question_prompt = payload.question_prompt

        if payload.learner_answer is not None and question_prompt is None:
            raise ValidationError("question_prompt is required when learner_answer is provided.")

        mistake_analysis = self._analyze_hint_mistakes(
            learner_message=payload.content,
            learner_answer=payload.learner_answer,
            reference_answer=reference_answer,
        )
        hint_level = self._determine_hint_level(
            prior_hint_count=prior_hint_count,
            learner_answer=payload.learner_answer,
            has_reference_answer=reference_answer is not None,
            has_mistake_analysis=bool(mistake_analysis),
            hint_level_preference=await self._hint_level_preference(learner_goal_id=learner_goal_id),
        )
        return HintContext(
            hint_level=hint_level,
            question_prompt=question_prompt,
            learner_answer=payload.learner_answer,
            reference_answer=reference_answer,
            prior_hint_count=prior_hint_count,
            mistake_analysis=mistake_analysis,
        )

    @staticmethod
    def _determine_hint_level(
        *,
        prior_hint_count: int,
        learner_answer: str | None,
        has_reference_answer: bool,
        has_mistake_analysis: bool,
        hint_level_preference: str | None,
    ) -> str:
        target_order = {"conceptual": 0, "scaffolded": 1, "targeted": 2}
        if has_reference_answer and learner_answer is not None and has_mistake_analysis:
            computed = "targeted"
        elif prior_hint_count >= 1 or learner_answer is not None:
            computed = "scaffolded"
        else:
            computed = "conceptual"
        if hint_level_preference in target_order and target_order[hint_level_preference] > target_order[computed]:
            return str(hint_level_preference)
        return computed

    async def _hint_level_preference(self, *, learner_goal_id: str | None) -> str | None:
        if learner_goal_id is None or self._rollout_resolver is None:
            return None
        overlay = await self._rollout_resolver.get_active_overlay(
            learner_goal_id=learner_goal_id,
            surface="hint",
            include_staged=True,
        )
        if overlay is None:
            return None
        preference = overlay.payload.get("hint_level_preference")
        return str(preference) if preference in {"conceptual", "scaffolded", "targeted"} else None

    @staticmethod
    def _analyze_hint_mistakes(
        *,
        learner_message: str,
        learner_answer: str | None,
        reference_answer: str | None,
    ) -> list[str]:
        if learner_answer is None:
            return []

        normalized_answer = learner_answer.casefold()
        issues: list[str] = []
        if reference_answer is not None and reference_answer.casefold() not in normalized_answer:
            issues.append("Learner answer does not align with the expected solution yet.")
        if "because" not in normalized_answer and "therefore" not in normalized_answer:
            issues.append("Learner answer does not yet explain the reasoning steps.")
        if len(normalized_answer.split()) <= 3:
            issues.append("Learner answer is still very short and may be guessing.")
        if "answer" in learner_message.casefold() and "not sure" in normalized_answer:
            issues.append("Learner explicitly signals uncertainty and needs a smaller next step.")
        return issues[:3]
