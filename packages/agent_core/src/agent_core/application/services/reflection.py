from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryReplayScheduleResult,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.reflective_memory import ReflectiveMemoryService
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_governance import ReflectionGovernanceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.domain.entities.autonomy import GoalAutonomyState, LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.planning import DailyTask, StudyPlan, WorkflowRun
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.errors import NotFoundError
from agent_core.domain.schemas.reflection import (
    ReflectionActionResponse,
    ReflectionListResponse,
    ReflectionRecordDetailResponse,
    ReflectionRecordListItemResponse,
)
from agent_core.domain.schemas.reflection_v2 import ReflectionReviewQueueItemResponse, ReflectionReviewQueueResponse
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    GoalAutonomyStateRepository,
    LearnerGoalRepository,
    LearnerTopicMasteryRepository,
    ReflectionActionRepository,
    ReflectionRecordRepository,
    SessionRepository,
    StudyPlanRepository,
    TaskAttemptRepository,
    WorkflowRunRepository,
)
from agent_core.infrastructure.llm.types import LLMProvider
from agent_core.infrastructure.observability.metrics import (
    observe_long_term_memory_materialization,
    observe_reflection_session_signal_coverage,
    observe_reflection_verdict,
)


@dataclass(frozen=True)
class ReflectionTriggerRequest:
    learner_profile_id: str
    learner_goal_id: str
    scope: str
    target_type: str
    target_id: str
    trigger_source: str
    reflection_depth: int
    daily_task_id: str | None = None
    workflow_run_id: str | None = None
    study_plan_id: str | None = None
    source_attempt_id: str | None = None


class ReflectionService:
    def __init__(
        self,
        *,
        reflection_record_repository: ReflectionRecordRepository,
        reflection_action_repository: ReflectionActionRepository,
        goal_repository: LearnerGoalRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
        study_plan_repository: StudyPlanRepository,
        task_attempt_repository: TaskAttemptRepository | None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None,
        session_repository: SessionRepository | None,
        memory_service: MemoryService,
        autonomy_job_service: AutonomyJobService,
        evidence_service: ReflectionEvidenceService | None = None,
        outcome_service: ReflectionOutcomeService | None = None,
        governance_service: ReflectionGovernanceService | None = None,
        strategy_card_service: StrategyCardService | None = None,
        reflective_memory_service: ReflectiveMemoryService | None = None,
        proposal_service: ReflectionProposalService | None = None,
        replay_service: ReflectionReplayService | None = None,
        long_term_memory_materialization_service: LongTermMemoryMaterializationService | None = None,
        audit_service: AuditService,
        llm_provider: LLMProvider,
        db_session: AsyncSession | None = None,
        reflection_max_depth: int = 2,
    ) -> None:
        self._reflection_record_repository = reflection_record_repository
        self._reflection_action_repository = reflection_action_repository
        self._goal_repository = goal_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._study_plan_repository = study_plan_repository
        self._task_attempt_repository = task_attempt_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._session_repository = session_repository
        self._memory_service = memory_service
        self._long_term_memory_materialization_service = long_term_memory_materialization_service
        self._autonomy_job_service = autonomy_job_service
        self._long_term_memory_replay_scheduler = LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=autonomy_job_service
        )
        self._evidence_service = evidence_service
        self._outcome_service = outcome_service
        self._governance_service = governance_service
        self._strategy_card_service = strategy_card_service
        self._reflective_memory_service = reflective_memory_service
        self._proposal_service = proposal_service
        self._replay_service = replay_service
        self._audit_service = audit_service
        self._llm_provider = llm_provider
        self._db_session = db_session
        self._reflection_max_depth = reflection_max_depth

    async def trigger_reflection(self, request: ReflectionTriggerRequest) -> ReflectionRecord | None:
        if request.reflection_depth > self._reflection_max_depth:
            await self._audit_service.record(
                event_type="reflection.trigger.skipped",
                resource_type=request.target_type,
                resource_id=request.target_id,
                actor="system",
                event_data={
                    "target_id": request.target_id,
                    "target_type": request.target_type,
                    "trigger_source": request.trigger_source,
                    "reflection_depth": request.reflection_depth,
                    "reason_code": "max_depth_reached",
                },
            )
            return None
        existing = await self._reflection_record_repository.get_by_dedupe_key(
            self._build_dedupe_key(request)
        )
        if existing is not None:
            return existing
        return await self._create_and_process(request)

    async def list_goal_reflections(
        self,
        *,
        goal_id: str,
        scopes: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ReflectionListResponse:
        items = await self._reflection_record_repository.list_by_goal(
            goal_id,
            scopes=scopes,
            statuses=statuses,
            limit=limit,
            offset=offset,
        )
        total = await self._reflection_record_repository.count_by_goal(goal_id, scopes=scopes, statuses=statuses)
        return ReflectionListResponse(
            items=[self._record_list_item(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_task_reflections(
        self,
        *,
        task_id: str,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ReflectionListResponse:
        items = await self._reflection_record_repository.list_by_task(
            task_id,
            statuses=statuses,
            limit=limit,
            offset=offset,
        )
        total = await self._reflection_record_repository.count_by_task(task_id, statuses=statuses)
        return ReflectionListResponse(
            items=[self._record_list_item(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_reflection(self, reflection_id: str) -> ReflectionRecordDetailResponse:
        record = await self._reflection_record_repository.get_by_id(reflection_id)
        if record is None:
            raise NotFoundError(f"Reflection record '{reflection_id}' was not found.")
        actions = await self._reflection_action_repository.list_by_reflection(reflection_id)
        return self._record_detail_item(record, actions=actions)

    async def get_record(self, reflection_id: str) -> ReflectionRecord:
        record = await self._reflection_record_repository.get_by_id(reflection_id)
        if record is None:
            raise NotFoundError(f"Reflection record '{reflection_id}' was not found.")
        return record

    async def apply_outcome_feedback(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation | None,
    ) -> ReflectionRecord:
        if evaluation is None:
            return reflection
        effective = evaluation.evaluation_status == "effective"
        ineffective = evaluation.evaluation_status == "ineffective"
        if not effective and not ineffective:
            return reflection
        updated = reflection.with_aggregation_update(
            duplicate_count=reflection.duplicate_count,
            priority_score=min(
                1.0,
                reflection.priority_score + (0.1 if effective else 0.15),
            ),
            last_duplicate_at=reflection.last_duplicate_at,
            cooldown_until=reflection.cooldown_until,
        )
        if ineffective and updated.status != "needs_review":
            updated = updated.with_status("needs_review")
        await self._reflection_record_repository.update(updated)
        actions = await self._reflection_action_repository.list_by_reflection(updated.id)
        if effective and self._strategy_card_service is not None:
            await self._strategy_card_service.refresh_from_evaluations(
                learner_goal_id=updated.learner_goal_id,
                reflections=[updated],
                effective=True,
            )
        if self._reflective_memory_service is not None:
            await self._reflective_memory_service.promote_or_refresh_candidate(
                reflection=updated,
                actions=actions,
                effective=effective,
            )
        await self._memory_service.bridge_reflection_outcome(
            reflection=updated,
            evaluation=evaluation,
        )
        if self._long_term_memory_materialization_service is not None:
            await self._materialize_reflection_outcome_isolated(
                reflection=updated,
                evaluation=evaluation,
            )
        if effective and self._proposal_service is not None and self._replay_service is not None:
            proposals = await self._proposal_service.list_by_reflection(updated.id)
            for proposal in proposals:
                evaluation_result = await self._replay_service.evaluate(
                    proposal=proposal,
                    baseline_policy_snapshot={},
                    candidate_policy_snapshot=dict(proposal.structured_patch_payload),
                )
                await self._proposal_service.review(
                    proposal_id=proposal.id,
                    status=proposal.status,
                    evaluation_status=evaluation_result.evaluation_status,
                    evaluation_summary=f"replay:{evaluation_result.score_delta}",
                )
            if updated.duplicate_count >= 1 and updated.priority_score >= 0.7:
                await self._proposal_service.create_skill_packages_from_reflection(reflection=updated)
        await self._audit_service.record(
            event_type="reflection.outcome.feedback.applied",
            resource_type="reflection_record",
            resource_id=updated.id,
            actor="system",
            event_data={
                "reflection_record_id": updated.id,
                "evaluation_status": evaluation.evaluation_status,
                "priority_score": updated.priority_score,
                "status": updated.status,
            },
        )
        return updated

    async def _materialize_reflection_outcome_isolated(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> None:
        if self._long_term_memory_materialization_service is None:
            return
        try:
            begin_nested = getattr(self._db_session, "begin_nested", None) if self._db_session is not None else None
            if begin_nested is None:
                await self._long_term_memory_materialization_service.materialize_from_reflection_outcome(
                    reflection=reflection,
                    evaluation=evaluation,
                    persist_embeddings=True,
                )
            else:
                async with begin_nested():
                    await self._long_term_memory_materialization_service.materialize_from_reflection_outcome(
                        reflection=reflection,
                        evaluation=evaluation,
                        persist_embeddings=True,
                    )
        except Exception as exc:
            observe_long_term_memory_materialization(
                source_type="reflection_outcome",
                status="failed",
                reason_code=type(exc).__name__,
            )
            replay = await self._schedule_reflection_materialization_replay(
                reflection=reflection,
                evaluation=evaluation,
            )
            event_data = {
                "source_type": "reflection_outcome",
                "learner_profile_id": reflection.learner_profile_id,
                "learner_goal_id": reflection.learner_goal_id,
                "reflection_id": reflection.id,
                "evaluation_id": evaluation.id,
                "daily_task_id": reflection.daily_task_id,
                "workflow_run_id": reflection.workflow_run_id,
                "evaluation_status": evaluation.evaluation_status,
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
            event_data.update(replay.audit_payload())
            await self._audit_service.record_durable(
                event_type="long_term_memory.materialization.failed",
                resource_type="reflection_record",
                resource_id=reflection.id,
                actor="system",
                event_data=event_data,
            )

    async def _schedule_reflection_materialization_replay(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> LongTermMemoryReplayScheduleResult:
        try:
            return await self._long_term_memory_replay_scheduler.schedule_reflection_outcome(
                learner_goal_id=reflection.learner_goal_id,
                reflection_id=reflection.id,
                evaluation_id=evaluation.id,
            )
        except Exception as replay_exc:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:reflection_outcome:{reflection.id}:{evaluation.id}",
                due_at=None,
                skip_reason="replay_enqueue_failed",
                error_code=type(replay_exc).__name__,
                error=str(replay_exc),
            )

    async def list_review_queue(
        self,
        *,
        statuses: set[str] | None = None,
        priority_min: float = 0.0,
        limit: int = 20,
        offset: int = 0,
    ) -> ReflectionReviewQueueResponse:
        records = await self._reflection_record_repository.list_review_queue(
            statuses=statuses,
            priority_min=priority_min,
            limit=limit,
            offset=offset,
        )
        total = await self._reflection_record_repository.count_review_queue(
            statuses=statuses,
            priority_min=priority_min,
        )
        items = [
            ReflectionReviewQueueItemResponse(
                reflection_id=item.id,
                learner_goal_id=item.learner_goal_id,
                learner_profile_id=item.learner_profile_id,
                status=item.status,
                scope=item.scope,
                trigger_source=item.trigger_source,
                primary_root_cause=item.primary_root_cause,
                severity=item.severity,
                confidence_score=item.confidence_score,
                priority_score=item.priority_score,
                duplicate_count=item.duplicate_count,
                summary=item.summary,
                created_at=item.created_at,
                last_duplicate_at=item.last_duplicate_at,
            )
            for item in records
        ]
        return ReflectionReviewQueueResponse(items=items, total=total, limit=limit, offset=offset)

    async def _create_and_process(self, request: ReflectionTriggerRequest) -> ReflectionRecord:
        evidence_payload = await self._build_evidence_payload(request)
        verdict = self._build_verdict(
            request=request,
            evidence_payload=evidence_payload,
        )
        evidence_payload["verdict"] = verdict
        primary_root_cause = str(verdict["primary_verdict"])
        secondary_root_causes = list(verdict["secondary_verdicts"])
        severity = str(verdict["severity"])
        confidence_score = float(verdict["verdict_confidence"])
        aggregation_key = self._build_aggregation_key(request=request, evidence_payload=evidence_payload, primary_root_cause=primary_root_cause)
        existing_aggregate = await self._reflection_record_repository.get_latest_by_aggregation_key(aggregation_key)
        if self._aggregate_is_open(existing_aggregate):
            aggregated = await self._update_aggregate_record(
                existing=existing_aggregate,
                request=request,
                evidence_payload=evidence_payload,
            )
            return aggregated
        priority_score = self._priority_score(
            severity=severity,
            confidence_score=confidence_score,
            evidence_payload=evidence_payload,
            duplicate_count=0,
            ineffective_history=False,
            unresolved_operator=severity == "high",
        )
        record = ReflectionRecord.build(
            learner_profile_id=request.learner_profile_id,
            learner_goal_id=request.learner_goal_id,
            daily_task_id=request.daily_task_id,
            workflow_run_id=request.workflow_run_id,
            study_plan_id=request.study_plan_id,
            scope=request.scope,
            target_type=request.target_type,
            target_id=request.target_id,
            trigger_source=request.trigger_source,
            reflection_depth=request.reflection_depth,
            dedupe_key=self._build_dedupe_key(request),
            aggregation_key=aggregation_key,
            duplicate_count=0,
            priority_score=priority_score,
            last_duplicate_at=None,
            cooldown_until=self._cooldown_until(request.scope, request.target_type),
            primary_root_cause=primary_root_cause,
            secondary_root_causes=secondary_root_causes,
            severity=severity,
            confidence_score=confidence_score,
            summary=self._fallback_summary(request.scope, primary_root_cause, evidence_payload),
            evidence_summary=self._fallback_evidence_summary(request.trigger_source, evidence_payload),
            recommended_next_step=self._fallback_next_step(primary_root_cause),
            evidence_payload=evidence_payload,
        )
        record = await self._reflection_record_repository.create(record)
        await self._audit_service.record(
            event_type="reflection.record.created",
            resource_type="reflection_record",
            resource_id=record.id,
            actor="system",
            event_data={
                "reflection_record_id": record.id,
                "learner_goal_id": record.learner_goal_id,
                "daily_task_id": record.daily_task_id,
                "workflow_run_id": record.workflow_run_id,
                "scope": record.scope,
                "trigger_source": record.trigger_source,
                "primary_root_cause": record.primary_root_cause,
            },
        )
        actions = await self._propose_actions(record)
        for action in actions:
            await self._reflection_action_repository.create(action)
            await self._audit_service.record(
                event_type="reflection.action.proposed",
                resource_type="reflection_action",
                resource_id=action.id,
                actor="system",
                event_data={
                    "reflection_record_id": record.id,
                    "reflection_action_id": action.id,
                    "action_type": action.action_type,
                    "risk_level": action.risk_level,
                    "approval_required": action.approval_required,
                },
            )

        llm_provider = None
        llm_model = None
        llm_latency_ms = None
        try:
            llm_summary = await self._llm_provider.generate_reflection_summary(
                scope=record.scope,
                trigger_source=record.trigger_source,
                primary_root_cause=record.primary_root_cause,
                severity=record.severity,
                verdict_payload=verdict,
                evidence_payload=record.evidence_payload,
                proposed_actions=[{"action_type": item.action_type, "payload": item.payload} for item in actions],
            )
            record = record.with_status(
                record.status,
                summary=llm_summary.summary,
                evidence_summary=llm_summary.evidence_summary,
                recommended_next_step=llm_summary.recommended_next_step,
                llm_provider=llm_summary.provider,
                llm_model=llm_summary.model,
                llm_latency_ms=llm_summary.latency_ms,
            )
            llm_provider = llm_summary.provider
            llm_model = llm_summary.model
            llm_latency_ms = llm_summary.latency_ms
            await self._audit_service.record(
                event_type="llm.reflection.completed",
                resource_type="reflection_record",
                resource_id=record.id,
                actor="system",
                event_data={
                    "reflection_record_id": record.id,
                    "provider": llm_summary.provider,
                    "model": llm_summary.model,
                    "latency_ms": llm_summary.latency_ms,
                    "retry_count": llm_summary.retry_count,
                    "response_shape_valid": llm_summary.response_shape_valid,
                },
            )
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="llm.reflection.failed",
                resource_type="reflection_record",
                resource_id=record.id,
                actor="system",
                event_data={
                    "reflection_record_id": record.id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
        await self._audit_service.record(
            event_type="reflection.verdict.generated",
            resource_type="reflection_record",
            resource_id=record.id,
            actor="system",
            event_data={
                "reflection_record_id": record.id,
                "verdict_code": primary_root_cause,
                "verdict_confidence": confidence_score,
                "secondary_verdicts": secondary_root_causes,
            },
        )
        observe_reflection_verdict(verdict_code=primary_root_cause, severity=severity)

        final_status = "completed"
        if any(item.approval_required for item in actions):
            final_status = "needs_review"
        executed_any = False
        for action in actions:
            updated_action = await self._execute_action(
                record=record,
                action=action,
            )
            if updated_action.status == "executed":
                executed_any = True
            if updated_action.status == "blocked":
                final_status = "needs_review"

        if executed_any and final_status != "needs_review":
            final_status = "actioned"
        record = record.with_status(
            final_status,
            llm_provider=llm_provider,
            llm_model=llm_model,
            llm_latency_ms=llm_latency_ms,
            processed=True,
        )
        await self._reflection_record_repository.update(record)
        topic_key = str((record.evidence_payload.get("task") or {}).get("topic_focus") or "") or None
        if self._outcome_service is not None:
            await self._outcome_service.start_tracking(
                reflection=record,
                topic_key=topic_key,
                baseline_snapshot={
                    "mastery": record.evidence_payload.get("mastery", {}),
                    "recent_attempts": record.evidence_payload.get("topic_attempts", []),
                },
            )
        if record.status in {"actioned", "completed"}:
            if self._strategy_card_service is not None:
                await self._strategy_card_service.refresh_from_reflections(
                    learner_goal_id=record.learner_goal_id,
                    reflections=[record],
                )
            if self._reflective_memory_service is not None:
                await self._reflective_memory_service.create_candidate(
                    reflection=record,
                    actions=await self._reflection_action_repository.list_by_reflection(record.id),
                )
            if self._proposal_service is not None:
                await self._proposal_service.create_from_reflection(reflection=record)
        await self._audit_service.record(
            event_type="reflection.record.completed",
            resource_type="reflection_record",
            resource_id=record.id,
            actor="system",
            event_data={
                "reflection_record_id": record.id,
                "status": record.status,
                "primary_root_cause": record.primary_root_cause,
            },
        )
        return record

    async def _update_aggregate_record(
        self,
        *,
        existing: ReflectionRecord,
        request: ReflectionTriggerRequest,
        evidence_payload: dict[str, Any],
    ) -> ReflectionRecord:
        occurrences = list((existing.evidence_payload.get("aggregated_occurrences") or []))
        occurrences.append(
            {
                "trigger_source": request.trigger_source,
                "target_id": request.target_id,
                "daily_task_id": request.daily_task_id,
                "workflow_run_id": request.workflow_run_id,
                "observed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        merged_payload = dict(existing.evidence_payload)
        merged_payload["aggregated_occurrences"] = occurrences[-10:]
        duplicate_count = existing.duplicate_count + 1
        updated = ReflectionRecord(
            **{
                **existing.__dict__,
                "duplicate_count": duplicate_count,
                "priority_score": self._priority_score(
                    severity=existing.severity,
                    confidence_score=existing.confidence_score,
                    evidence_payload=merged_payload,
                    duplicate_count=duplicate_count,
                    ineffective_history=existing.status == "needs_review",
                    unresolved_operator=existing.status == "needs_review",
                ),
                "last_duplicate_at": datetime.now(timezone.utc),
                "cooldown_until": self._cooldown_until(existing.scope, existing.target_type),
                "evidence_payload": merged_payload,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        await self._reflection_record_repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.record.aggregated",
            resource_type="reflection_record",
            resource_id=updated.id,
            actor="system",
            event_data={
                "reflection_record_id": updated.id,
                "duplicate_count": updated.duplicate_count,
                "priority_score": updated.priority_score,
                "aggregation_key": updated.aggregation_key,
            },
        )
        return updated

    async def _build_evidence_payload(self, request: ReflectionTriggerRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        task = await self._daily_task_repository.get_by_id(request.daily_task_id) if request.daily_task_id else None
        workflow = await self._workflow_run_repository.get_by_id(request.workflow_run_id) if request.workflow_run_id else None
        plan = await self._study_plan_repository.get_by_id(request.study_plan_id) if request.study_plan_id else None
        attempts = await self._recent_attempts(request.learner_goal_id)
        topic_attempts = await self._topic_attempts(request.learner_goal_id, task.topic_focus if task is not None else None)
        mastery = await self._mastery(request.learner_goal_id, task.topic_focus if task is not None else None)
        goal_state = await self._goal_state(request.learner_goal_id)
        memory_corpus = await self._memory_corpus(request.learner_profile_id, request.learner_goal_id)
        session_signals = await self._session_signals(task)
        derived_signals = (
            await self._evidence_service.derive_from_workflow(
                learner_profile_id=request.learner_profile_id,
                learner_goal_id=request.learner_goal_id,
                workflow_run=workflow,
            )
            if self._evidence_service is not None and workflow is not None and workflow.status == "failed"
            else []
        )
        payload["task"] = self._task_payload(task)
        payload["workflow"] = self._workflow_payload(workflow)
        payload["plan"] = self._plan_payload(plan)
        payload["recent_attempts"] = [self._attempt_payload(item) for item in attempts]
        payload["topic_attempts"] = [self._attempt_payload(item) for item in topic_attempts]
        payload["mastery"] = self._mastery_payload(mastery)
        payload["goal_state"] = self._goal_state_payload(goal_state)
        payload["memory_corpus"] = memory_corpus
        payload["session_signals"] = session_signals
        payload["derived_signals"] = [self._signal_payload(item) for item in derived_signals]
        return payload

    def _classify(
        self,
        *,
        request: ReflectionTriggerRequest,
        evidence_payload: dict[str, Any],
    ) -> tuple[str, list[str], str, float]:
        verdict = self._build_verdict(request=request, evidence_payload=evidence_payload)
        return (
            str(verdict["primary_verdict"]),
            list(verdict["secondary_verdicts"]),
            str(verdict["severity"]),
            float(verdict["verdict_confidence"]),
        )

    def _build_verdict(
        self,
        *,
        request: ReflectionTriggerRequest,
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        task = evidence_payload.get("task") or {}
        workflow = evidence_payload.get("workflow") or {}
        mastery = evidence_payload.get("mastery") or {}
        topic_attempts = evidence_payload.get("topic_attempts") or []
        memory_items = list((evidence_payload.get("memory_corpus") or {}).get("items") or [])
        session_signals = dict(evidence_payload.get("session_signals") or {})
        derived_signals = list(evidence_payload.get("derived_signals") or [])
        task_status = str(task.get("status") or "")
        task_type = str(task.get("task_type") or "")
        difficulty = str(task.get("difficulty") or "")
        mastery_score = float(mastery.get("mastery_score") or 0.0)
        if workflow.get("status") == "failed" or workflow.get("error_code"):
            return {
                "primary_verdict": "workflow_issue",
                "secondary_verdicts": [],
                "severity": "high",
                "verdict_confidence": 0.95,
                "evidence_breakdown": {"workflow_issue": 0.95},
                "memory_implications": [{"action": "observe", "memory_type": "knowledge", "topic_key": "workflow"}],
                "strategy_implications": {"replan_bias": "conservative"},
            }
        signal_codes = {str(item.get("signal_code") or "") for item in derived_signals}
        scores: dict[str, float] = {
            "knowledge_gap": 0.2,
            "difficulty_mismatch": 0.0,
            "review_gap": 0.0,
            "sequencing_issue": 0.0,
            "engagement_constraint": 0.0,
            "assessment_regression": 0.0,
        }
        if task_status == "skipped":
            scores["engagement_constraint"] += 0.72
        if task_type == "assessment" and mastery_score < 0.6:
            scores["assessment_regression"] += 0.74
            scores["knowledge_gap"] += 0.08
        if task_status == "failed" and task_type == "review":
            scores["review_gap"] += 0.76
        if task_status == "failed" and difficulty == "hard" and 0.45 <= mastery_score < 0.7:
            scores["difficulty_mismatch"] += 0.72
            scores["knowledge_gap"] += 0.04
        if self._is_sequencing_issue(topic_attempts=topic_attempts):
            scores["sequencing_issue"] += 0.74
            scores["knowledge_gap"] += 0.05
        if task_status == "failed":
            scores["knowledge_gap"] += 0.45
        if mastery_score < 0.6:
            scores["knowledge_gap"] += 0.1
        if int(session_signals.get("hint_turn_count") or 0) >= 2:
            scores["engagement_constraint"] += 0.08
        if int(session_signals.get("direct_answer_request_count") or 0) > 0:
            scores["engagement_constraint"] += 0.05
        if int(session_signals.get("confusion_keyword_count") or 0) >= 2:
            scores["knowledge_gap"] += 0.05
        if "assessment_regression" in signal_codes:
            scores["assessment_regression"] += 0.08
        if "repeated_skip_pattern" in signal_codes or "high_hint_dependency" in signal_codes:
            scores["engagement_constraint"] += 0.06
        if "topic_failure_cluster" in signal_codes or "repeat_confusion" in signal_codes:
            scores["knowledge_gap"] += 0.06
        for item in memory_items:
            memory_type = str(item.get("memory_type") or "")
            recommended_action = str(item.get("recommended_action") or "")
            quality_score = float(item.get("quality_score") or 0.0)
            if memory_type == "knowledge":
                if recommended_action in {"reinforce", "validate"}:
                    scores["knowledge_gap"] += 0.04 + 0.03 * quality_score
                if recommended_action == "refresh":
                    scores["review_gap"] += 0.05
            if memory_type == "behavior" and str(item.get("promotion_readiness") or "") == "ready":
                scores["engagement_constraint"] += 0.04
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        primary_verdict, primary_score = ordered[0]
        secondary_verdicts = [
            code for code, score in ordered[1:] if score >= 0.45 and primary_score - score <= 0.12
        ]
        severity = "high" if primary_score >= 0.8 else "medium" if primary_score >= 0.65 else "low"
        return {
            "primary_verdict": primary_verdict,
            "secondary_verdicts": secondary_verdicts,
            "severity": severity,
            "verdict_confidence": self._clamp_confidence(primary_score),
            "evidence_breakdown": {code: round(score, 4) for code, score in ordered},
            "memory_implications": self._memory_implications_for_verdict(primary_verdict, evidence_payload=evidence_payload),
            "strategy_implications": self._strategy_implications_for_verdict(primary_verdict),
        }

    async def _propose_actions(self, record: ReflectionRecord) -> list[ReflectionAction]:
        cause = record.primary_root_cause
        if cause == "workflow_issue":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="high",
                    approval_required=True,
                    payload={"reason": "workflow_issue", "mode": "partial"},
                )
            ]
        if cause == "review_gap":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_review_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "review_gap"},
                )
            ]
        if cause == "assessment_regression":
            mode = "full" if float((record.evidence_payload.get("mastery") or {}).get("mastery_score") or 0.0) < 0.45 else "partial"
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "assessment_regression", "mode": mode},
                )
            ]
        if cause == "knowledge_gap":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "knowledge_gap", "mode": "partial"},
                )
            ]
        if cause == "difficulty_mismatch":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "difficulty_mismatch", "mode": "partial"},
                )
            ]
        if cause == "sequencing_issue":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "sequencing_issue", "mode": "full"},
                )
            ]
        if cause == "engagement_constraint":
            return [
                ReflectionAction.build(
                    reflection_record_id=record.id,
                    action_type="enqueue_replan_job",
                    risk_level="low",
                    approval_required=False,
                    payload={"reason": "engagement_constraint", "mode": "partial"},
                )
            ]
        return []

    async def _execute_action(self, *, record: ReflectionRecord, action: ReflectionAction) -> ReflectionAction:
        if action.approval_required or action.risk_level == "high":
            blocked = action.with_status(
                "blocked",
                execution_result={"reason_code": "approval_required"},
            )
            await self._reflection_action_repository.update(blocked)
            await self._audit_service.record(
                event_type="reflection.action.blocked",
                resource_type="reflection_action",
                resource_id=blocked.id,
                actor="system",
                event_data={
                    "reflection_record_id": record.id,
                    "reflection_action_id": blocked.id,
                    "action_type": blocked.action_type,
                    "reason_code": "approval_required",
                },
            )
            return blocked

        due_at = datetime.now(timezone.utc)
        topic_focus = str((record.evidence_payload.get("task") or {}).get("topic_focus") or "")
        if action.action_type == "enqueue_review_job":
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=record.learner_goal_id,
                job_type="review_scheduling",
                trigger_source="task_completed",
                due_at=due_at,
                idempotency_key=f"reflection:{record.id}:review",
                payload={
                    "source_task_id": record.daily_task_id or "",
                    "reflection_record_id": record.id,
                    "reflection_depth": record.reflection_depth,
                    "origin": "reflection",
                },
            )
        elif action.action_type == "enqueue_assessment_job":
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=record.learner_goal_id,
                job_type="assessment_generation",
                trigger_source=record.trigger_source,
                due_at=due_at,
                idempotency_key=f"reflection:{record.id}:assessment",
                payload={
                    "topic_focus": topic_focus,
                    "reflection_record_id": record.id,
                    "reflection_depth": record.reflection_depth,
                    "origin": "reflection",
                },
            )
        else:
            mode = str(action.payload.get("mode") or "partial")
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=record.learner_goal_id,
                job_type="replan",
                trigger_source=record.trigger_source,
                due_at=due_at,
                idempotency_key=f"reflection:{record.id}:replan:{mode}",
                payload={
                    "mode": mode,
                    "source_task_id": record.daily_task_id or "",
                    "topic_focus": topic_focus,
                    "reflection_record_id": record.id,
                    "reflection_depth": record.reflection_depth,
                    "origin": "reflection",
                },
            )
        executed = action.with_status(
            "executed",
            execution_result={"autonomy_job_id": job.id if job is not None else None},
            executed=True,
        )
        await self._reflection_action_repository.update(executed)
        await self._audit_service.record(
            event_type="reflection.action.executed",
            resource_type="reflection_action",
            resource_id=executed.id,
            actor="system",
            event_data={
                "reflection_record_id": record.id,
                "reflection_action_id": executed.id,
                "action_type": executed.action_type,
                "autonomy_job_id": job.id if job is not None else None,
            },
        )
        return executed

    def _build_dedupe_key(self, request: ReflectionTriggerRequest) -> str:
        if request.scope == "goal" and request.source_attempt_id is not None:
            return f"goal:{request.learner_goal_id}:{request.trigger_source}:{request.source_attempt_id}"
        return f"{request.scope}:{request.target_type}:{request.target_id}:{request.trigger_source}:{request.reflection_depth}"

    async def _recent_attempts(self, learner_goal_id: str) -> list[TaskAttempt]:
        if self._task_attempt_repository is None:
            return []
        return await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=5)

    async def _topic_attempts(self, learner_goal_id: str, topic_focus: str | None) -> list[TaskAttempt]:
        if self._task_attempt_repository is None or not topic_focus:
            return []
        attempts = await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=10)
        return [item for item in attempts if item.topic_focus == topic_focus][:5]

    async def _mastery(self, learner_goal_id: str, topic_focus: str | None) -> LearnerTopicMastery | None:
        if self._learner_topic_mastery_repository is None or not topic_focus:
            return None
        return await self._learner_topic_mastery_repository.get_by_goal_and_topic(learner_goal_id, topic_focus)

    async def _goal_state(self, learner_goal_id: str) -> GoalAutonomyState | None:
        if self._goal_autonomy_state_repository is None:
            return None
        return await self._goal_autonomy_state_repository.get_by_goal(learner_goal_id)

    async def _memory_corpus(self, learner_profile_id: str, learner_goal_id: str) -> dict[str, object]:
        interpretation_result = await self._memory_service.build_interpretation(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            limit_per_type=4,
        )
        interpretation = {
            "facts": [item.__dict__ for item in interpretation_result.facts],
            "behavior_patterns": [item.__dict__ for item in interpretation_result.behavior_patterns],
            "contested_items": [item.__dict__ for item in interpretation_result.contested_items],
            "recommended_constraints": interpretation_result.recommended_constraints,
            "conflict_count": interpretation_result.conflict_count,
        }
        corpus = await self._memory_service.build_reflection_corpus(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            limit_per_type=2,
        )
        items = [
            {
                "memory_type": item.memory_type,
                "memory_id": item.memory_id,
                "memory_key": item.memory_key,
                "summary": item.summary,
                "recommended_action": item.recommended_action,
                "reflection_priority_score": item.reflection_priority_score,
                "quality_score": item.quality_score,
                "promotion_readiness": item.promotion_readiness,
                "semantic_category": item.semantic_category,
                "validation_status": item.validation_status,
                "contested": item.contested,
            }
            for item in corpus.items
        ]
        return {"items": items, "summary": corpus.summary.__dict__, "interpretation": interpretation}

    async def _session_signals(self, task: DailyTask | None) -> dict[str, object]:
        if task is None or task.execution_session_id is None or self._evidence_service is None:
            observe_reflection_session_signal_coverage(covered=False)
            return {
                "hint_turn_count": 0,
                "struggle_event_count": 0,
                "progress_event_count": 0,
                "confusion_keyword_count": 0,
                "direct_answer_request_count": 0,
                "short_retry_count": 0,
                "recent_signal_codes": [],
            }
        signals = await self._evidence_service.aggregate_session_signals(session_id=task.execution_session_id)
        covered = any(
            int(signals.get(key) or 0) > 0
            for key in (
                "hint_turn_count",
                "struggle_event_count",
                "progress_event_count",
                "confusion_keyword_count",
                "direct_answer_request_count",
                "short_retry_count",
            )
        ) or bool(signals.get("recent_signal_codes"))
        observe_reflection_session_signal_coverage(covered=covered)
        return signals

    @staticmethod
    def _task_payload(task: DailyTask | None) -> dict[str, object]:
        if task is None:
            return {}
        return {
            "id": task.id,
            "status": task.status,
            "task_type": task.task_type,
            "topic_focus": task.topic_focus,
            "difficulty": task.difficulty,
            "result_note": task.result_note,
            "execution_session_id": task.execution_session_id,
            "last_workflow_run_id": task.last_workflow_run_id,
        }

    @staticmethod
    def _workflow_payload(workflow: WorkflowRun | None) -> dict[str, object]:
        if workflow is None:
            return {}
        return {
            "id": workflow.id,
            "status": workflow.status,
            "workflow_type": workflow.workflow_type,
            "error_code": workflow.error_code,
            "result_resource_ids": list(workflow.result_resource_ids),
        }

    @staticmethod
    def _plan_payload(plan: StudyPlan | None) -> dict[str, object]:
        if plan is None:
            return {}
        return {
            "id": plan.id,
            "version": plan.version,
            "trigger_source": plan.trigger_source,
            "status": plan.status,
        }

    @staticmethod
    def _attempt_payload(attempt: TaskAttempt) -> dict[str, object]:
        return {
            "id": attempt.id,
            "topic_focus": attempt.topic_focus,
            "task_type": attempt.task_type,
            "outcome_status": attempt.outcome_status,
            "score": attempt.score,
            "result_note": attempt.result_note,
            "created_at": attempt.created_at.isoformat(),
        }

    @staticmethod
    def _mastery_payload(mastery: LearnerTopicMastery | None) -> dict[str, object]:
        if mastery is None:
            return {}
        return {
            "topic_key": mastery.topic_key,
            "mastery_score": mastery.mastery_score,
            "confidence": mastery.confidence,
            "evidence_count": mastery.evidence_count,
            "last_attempt_status": mastery.last_attempt_status,
        }

    @staticmethod
    def _goal_state_payload(state: GoalAutonomyState | None) -> dict[str, object]:
        if state is None:
            return {}
        return {
            "phase": state.phase,
            "current_plan_id": state.current_plan_id,
            "next_due_at": state.next_due_at.isoformat() if state.next_due_at is not None else None,
            "last_transition_reason": state.last_transition_reason,
        }

    @staticmethod
    def _fallback_summary(scope: str, primary_root_cause: str, evidence_payload: dict[str, Any]) -> str:
        topic = str((evidence_payload.get("task") or {}).get("topic_focus") or "current topic")
        return f"{scope} reflection identified {primary_root_cause} around {topic}."

    @staticmethod
    def _fallback_evidence_summary(trigger_source: str, evidence_payload: dict[str, Any]) -> str:
        return f"Triggered by {trigger_source}; evidence bundle keys: {', '.join(sorted(evidence_payload.keys()))}."

    @staticmethod
    def _fallback_next_step(primary_root_cause: str) -> str:
        return f"Proceed with the governed follow-up for {primary_root_cause}."

    @staticmethod
    def _build_aggregation_key(
        *,
        request: ReflectionTriggerRequest,
        evidence_payload: dict[str, Any],
        primary_root_cause: str,
    ) -> str:
        topic_key = str((evidence_payload.get("task") or {}).get("topic_focus") or "general")
        workflow_type = str((evidence_payload.get("workflow") or {}).get("workflow_type") or "workflow")
        error_code = str((evidence_payload.get("workflow") or {}).get("error_code") or "none")
        if request.target_type == "workflow_run":
            return f"workflow:{request.learner_goal_id}:{workflow_type}:{error_code}"
        if request.scope == "goal":
            return f"goal:{request.learner_goal_id}:{topic_key}:{primary_root_cause}"
        return f"task:{request.learner_goal_id}:{topic_key}:{primary_root_cause}"

    @staticmethod
    def _priority_score(
        *,
        severity: str,
        confidence_score: float,
        evidence_payload: dict[str, Any],
        duplicate_count: int,
        ineffective_history: bool,
        unresolved_operator: bool,
    ) -> float:
        severity_weight = {"low": 0.3, "medium": 0.6, "high": 0.85}[severity]
        signal_bonus = min(len(evidence_payload.get("derived_signals", [])) * 0.04, 0.12)
        topic_attempts = evidence_payload.get("topic_attempts", [])
        recurrence_bonus = min(len(topic_attempts) * 0.03, 0.12)
        duplicate_bonus = min(duplicate_count * 0.05, 0.2)
        ineffective_bonus = 0.1 if ineffective_history else 0.0
        unresolved_bonus = 0.08 if unresolved_operator else 0.0
        return min(
            1.0,
            severity_weight
            + 0.2 * confidence_score
            + signal_bonus
            + recurrence_bonus
            + duplicate_bonus
            + ineffective_bonus
            + unresolved_bonus,
        )

    @staticmethod
    def _aggregate_is_open(existing: ReflectionRecord | None) -> bool:
        if existing is None or existing.cooldown_until is None:
            return False
        cooldown_until = existing.cooldown_until
        if cooldown_until.tzinfo is None:
            return cooldown_until > datetime.utcnow()
        return cooldown_until > datetime.now(timezone.utc)

    @staticmethod
    def _cooldown_until(scope: str, target_type: str) -> datetime:
        now = datetime.now(timezone.utc)
        if target_type == "workflow_run":
            return now + timedelta(hours=24)
        if scope == "goal":
            return now + timedelta(hours=72)
        return now + timedelta(hours=24)

    @staticmethod
    def _clamp_confidence(score: float) -> float:
        return max(0.0, min(score, 1.0))

    @staticmethod
    def _strategy_implications_for_verdict(primary_verdict: str) -> dict[str, str]:
        mapping = {
            "knowledge_gap": {"primary_instruction_mode": "guided", "review_bias": "intensive"},
            "difficulty_mismatch": {"difficulty_bias": "supportive"},
            "review_gap": {"review_bias": "intensive"},
            "sequencing_issue": {"replan_bias": "aggressive", "primary_instruction_mode": "guided"},
            "engagement_constraint": {"primary_instruction_mode": "guided", "difficulty_bias": "supportive"},
            "assessment_regression": {"assessment_bias": "early", "replan_bias": "aggressive"},
            "workflow_issue": {"replan_bias": "conservative"},
        }
        return mapping.get(primary_verdict, {})

    @staticmethod
    def _memory_implications_for_verdict(primary_verdict: str, *, evidence_payload: dict[str, Any]) -> list[dict[str, str]]:
        topic_key = str((evidence_payload.get("task") or {}).get("topic_focus") or "current_topic")
        if primary_verdict == "knowledge_gap":
            return [{"action": "reinforce", "memory_type": "knowledge", "topic_key": topic_key}]
        if primary_verdict in {"difficulty_mismatch", "review_gap"}:
            return [{"action": "refresh", "memory_type": "knowledge", "topic_key": topic_key}]
        if primary_verdict == "assessment_regression":
            return [{"action": "validate", "memory_type": "knowledge", "topic_key": topic_key}]
        if primary_verdict == "engagement_constraint":
            return [{"action": "reinforce", "memory_type": "behavior", "topic_key": topic_key}]
        return [{"action": "observe", "memory_type": "knowledge", "topic_key": topic_key}]

    @staticmethod
    def _record_verdict_payload(record: ReflectionRecord) -> dict[str, Any]:
        verdict = dict((record.evidence_payload or {}).get("verdict") or {})
        if verdict:
            return verdict
        return {
            "primary_verdict": record.primary_root_cause,
            "secondary_verdicts": list(record.secondary_root_causes),
            "verdict_confidence": record.confidence_score,
            "evidence_breakdown": {record.primary_root_cause: record.confidence_score},
            "memory_implications": [],
            "strategy_implications": {},
        }

    def _record_list_item(self, record: ReflectionRecord) -> ReflectionRecordListItemResponse:
        verdict = self._record_verdict_payload(record)
        return ReflectionRecordListItemResponse.model_validate(
            {
                **record.__dict__,
                "verdict_code": verdict.get("primary_verdict", record.primary_root_cause),
                "verdict_confidence": verdict.get("verdict_confidence", record.confidence_score),
            }
        )

    def _record_detail_item(
        self,
        record: ReflectionRecord,
        *,
        actions: list[ReflectionAction],
    ) -> ReflectionRecordDetailResponse:
        verdict = self._record_verdict_payload(record)
        return ReflectionRecordDetailResponse.model_validate(
            {
                **record.__dict__,
                "verdict_code": verdict.get("primary_verdict", record.primary_root_cause),
                "verdict_confidence": verdict.get("verdict_confidence", record.confidence_score),
                "evidence_breakdown": verdict.get("evidence_breakdown", {}),
                "memory_implications": verdict.get("memory_implications", []),
                "strategy_implications": verdict.get("strategy_implications", {}),
                "session_signal_summary": dict((record.evidence_payload or {}).get("session_signals") or {}),
                "actions": [ReflectionActionResponse.model_validate(item) for item in actions],
            }
        )

    @staticmethod
    def _signal_payload(signal) -> dict[str, object]:
        return {
            "id": signal.id,
            "signal_code": signal.signal_code,
            "source_type": signal.source_type,
            "topic_key": signal.topic_key,
            "severity_score": signal.severity_score,
            "confidence_score": signal.confidence_score,
            "payload": signal.payload,
        }

    @staticmethod
    def _is_sequencing_issue(*, topic_attempts: list[dict[str, object]] | list[TaskAttempt]) -> bool:
        recent = [
            item.outcome_status if isinstance(item, TaskAttempt) else str(item.get("outcome_status") or "")
            for item in topic_attempts[:3]
        ]
        return len([item for item in recent if item in {"failed", "skipped"}]) >= 2
