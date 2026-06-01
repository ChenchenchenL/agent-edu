from __future__ import annotations

from agent_core.application.services.audit import AuditService
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
    ) -> None:
        self._reflection_record_repository = reflection_record_repository
        self._reflection_action_repository = reflection_action_repository
        self._review_decision_repository = review_decision_repository
        self._audit_service = audit_service

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
            actor="operator",
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
            actor="operator",
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
            actor="operator",
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
            actor="operator",
            event_data={"operator_id": operator_id, "action_type": action_type, "reason_code": reason_code},
        )
        return decision

    async def _require_reflection(self, reflection_id: str) -> ReflectionRecord:
        reflection = await self._reflection_record_repository.get_by_id(reflection_id)
        if reflection is None:
            raise NotFoundError(f"Reflection record '{reflection_id}' was not found.")
        return reflection
