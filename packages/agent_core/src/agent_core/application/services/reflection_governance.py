from datetime import datetime, timezone
from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionReviewDecision
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    ReflectionActionRepository,
    ReflectionRecordRepository,
    ReflectionReviewDecisionRepository,
)


class ReflectionGovernanceService:
    def __init__(
        self,
        *,
        reflection_record_repository: ReflectionRecordRepository,
        reflection_action_repository: ReflectionActionRepository,
        review_decision_repository: ReflectionReviewDecisionRepository,
        audit_service: AuditService,
        autonomy_job_service: AutonomyJobService | None = None,
    ) -> None:
        self._reflection_record_repository = reflection_record_repository
        self._reflection_action_repository = reflection_action_repository
        self._review_decision_repository = review_decision_repository
        self._audit_service = audit_service
        self._autonomy_job_service = autonomy_job_service

    async def list_review_decisions(self, reflection_id: str) -> list[ReflectionReviewDecision]:
        return await self._review_decision_repository.list_by_reflection(reflection_id)

    async def review(self, *, reflection_id: str, operator_id: str, reason_code: str, reason_note: str | None) -> ReflectionReviewDecision:
        reflection = await self._require_reflection(reflection_id)
        decision = ReflectionReviewDecision.build(
            reflection_record_id=reflection.id,
            decision_type="reviewed",
            previous_status=reflection.status,
            new_status=reflection.status,
            previous_root_cause=reflection.primary_root_cause,
            new_root_cause=reflection.primary_root_cause,
            previous_action_payload=None,
            new_action_payload=None,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
        )
        await self._review_decision_repository.create(decision)
        await self._audit_service.record(
            event_type="reflection.reviewed",
            resource_type="reflection_record",
            resource_id=reflection.id,
            actor=operator_id,
            event_data={"operator_id": operator_id, "reason_code": reason_code},
        )
        return decision

    async def resolve(self, *, reflection_id: str, operator_id: str, new_status: str, reason_code: str, reason_note: str | None) -> ReflectionReviewDecision:
        reflection = await self._require_reflection(reflection_id)
        updated = reflection.with_status(new_status, processed=True)
        await self._reflection_record_repository.update(updated)
        decision = ReflectionReviewDecision.build(
            reflection_record_id=reflection.id,
            decision_type="resolved",
            previous_status=reflection.status,
            new_status=new_status,
            previous_root_cause=reflection.primary_root_cause,
            new_root_cause=reflection.primary_root_cause,
            previous_action_payload=None,
            new_action_payload=None,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
        )
        await self._review_decision_repository.create(decision)
        await self._audit_service.record(
            event_type="reflection.resolved",
            resource_type="reflection_record",
            resource_id=reflection.id,
            actor=operator_id,
            event_data={"operator_id": operator_id, "new_status": new_status, "reason_code": reason_code},
        )
        return decision

    async def override_root_cause(
        self,
        *,
        reflection_id: str,
        operator_id: str,
        new_root_cause: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionReviewDecision:
        reflection = await self._require_reflection(reflection_id)
        if new_root_cause == reflection.primary_root_cause:
            raise ValidationError("new_root_cause must differ from current root cause.")
        updated = ReflectionRecord(
            **{
                **reflection.__dict__,
                "primary_root_cause": new_root_cause,
            }
        )
        await self._reflection_record_repository.update(updated)
        decision = ReflectionReviewDecision.build(
            reflection_record_id=reflection.id,
            decision_type="override_root_cause",
            previous_status=reflection.status,
            new_status=reflection.status,
            previous_root_cause=reflection.primary_root_cause,
            new_root_cause=new_root_cause,
            previous_action_payload=None,
            new_action_payload=None,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
        )
        await self._review_decision_repository.create(decision)
        await self._audit_service.record(
            event_type="reflection.root_cause.overridden",
            resource_type="reflection_record",
            resource_id=reflection.id,
            actor=operator_id,
            event_data={"operator_id": operator_id, "new_root_cause": new_root_cause, "reason_code": reason_code},
        )
        return decision

    async def override_action(
        self,
        *,
        reflection_id: str,
        operator_id: str,
        action_type: str,
        payload: dict,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionReviewDecision:
        reflection = await self._require_reflection(reflection_id)
        actions = await self._reflection_action_repository.list_by_reflection(reflection_id)
        if not actions:
            raise NotFoundError(f"Reflection action for '{reflection_id}' was not found.")
        target = actions[0]
        updated_action = ReflectionAction(
            **{
                **target.__dict__,
                "action_type": action_type,
                "payload": dict(payload),
                "status": "proposed",
                "execution_result": {},
            }
        )
        await self._reflection_action_repository.update(updated_action)
        decision = ReflectionReviewDecision.build(
            reflection_record_id=reflection.id,
            decision_type="override_action",
            previous_status=reflection.status,
            new_status=reflection.status,
            previous_root_cause=reflection.primary_root_cause,
            new_root_cause=reflection.primary_root_cause,
            previous_action_payload=target.payload,
            new_action_payload=payload,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
        )
        await self._review_decision_repository.create(decision)
        await self._audit_service.record(
            event_type="reflection.action.overridden",
            resource_type="reflection_action",
            resource_id=target.id,
            actor=operator_id,
            event_data={"operator_id": operator_id, "action_type": action_type, "reason_code": reason_code},
        )
        return decision

    async def _require_reflection(self, reflection_id: str) -> ReflectionRecord:
        reflection = await self._reflection_record_repository.get_by_id(reflection_id)
        if reflection is None:
            raise NotFoundError(f"Reflection record '{reflection_id}' was not found.")
        return reflection

    async def activate_action(
        self,
        *,
        reflection_id: str,
        action_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None = None,
    ) -> ReflectionAction:
        reflection = await self._require_reflection(reflection_id)
        action = await self._reflection_action_repository.get_by_id(action_id)
        if action is None or action.reflection_record_id != reflection_id:
            raise NotFoundError(f"Action '{action_id}' was not found for reflection '{reflection_id}'.")

        if action.status != "blocked":
            raise ValidationError(f"Action status must be 'blocked' to activate manually, currently: '{action.status}'.")

        if action.action_type == "enqueue_sandbox_admission_review":
            raise ValidationError("This action type can only be reviewed by an operator and does not support manual execution.")

        if self._autonomy_job_service is None:
            raise ValidationError("Autonomy job service is not configured.")

        due_at = datetime.now(timezone.utc)
        job = None
        if action.action_type == "enqueue_replan_job":
            mode = str(action.payload.get("mode") or "partial")
            topic_focus = str((reflection.evidence_payload.get("task") or {}).get("topic_focus") or "")
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=reflection.learner_goal_id,
                job_type="replan",
                trigger_source=reflection.trigger_source,
                due_at=due_at,
                idempotency_key=f"reflection:{reflection.id}:replan:{mode}:activated",
                payload={
                    "mode": mode,
                    "source_task_id": reflection.daily_task_id or "",
                    "topic_focus": topic_focus,
                    "reflection_record_id": reflection.id,
                    "reflection_depth": reflection.reflection_depth,
                    "origin": "reflection_governance",
                },
            )
        elif action.action_type == "enqueue_memory_governance_review":
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=reflection.learner_goal_id,
                job_type="reflection_skill_evolution_curator",
                trigger_source=reflection.trigger_source,
                due_at=due_at,
                idempotency_key=f"reflection:{reflection.id}:{action.action_type}:activated",
                payload={
                    "action_type": action.action_type,
                    "reflection_record_id": reflection.id,
                    "origin": "reflection_governance",
                },
            )
        elif action.action_type in (
            "enqueue_router_review",
            "enqueue_template_review",
            "update_strategy_card_candidate",
            "enqueue_skill_curator_review",
        ):
            job = await self._autonomy_job_service.create_job(
                learner_goal_id=reflection.learner_goal_id,
                job_type="reflection_skill_evolution_curator",
                trigger_source=reflection.trigger_source,
                due_at=due_at,
                idempotency_key=f"reflection:{reflection.id}:{action.action_type}:activated",
                payload={
                    "action_type": action.action_type,
                    "reflection_record_id": reflection.id,
                    "origin": "reflection_governance",
                },
            )

        executed = action.with_status(
            "executed",
            execution_result={"autonomy_job_id": job.id if job is not None else None},
            executed=True,
        )
        await self._reflection_action_repository.update(executed)

        await self._audit_service.record(
            event_type="reflection.action.activated",
            resource_type="reflection_action",
            resource_id=executed.id,
            actor=operator_id,
            event_data={
                "reflection_record_id": reflection.id,
                "reflection_action_id": executed.id,
                "action_type": executed.action_type,
                "autonomy_job_id": job.id if job is not None else None,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

        # Check if all actions are resolved now
        all_actions = await self._reflection_action_repository.list_by_reflection(reflection.id)
        all_resolved = True
        for act in all_actions:
            status = "executed" if act.id == action.id else act.status
            if status in ("proposed", "blocked"):
                all_resolved = False
                break

        if all_resolved:
            updated_reflection = reflection.with_status("actioned", processed=True)
            await self._reflection_record_repository.update(updated_reflection)

        return executed
