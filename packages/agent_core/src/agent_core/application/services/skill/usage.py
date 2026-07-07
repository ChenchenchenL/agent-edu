"""Skill usage recording and querying service.

This module handles skill usage event recording, querying, and metadata
sanitization. Usage events are persisted even on failure paths to support
curator and readiness evidence. The service does not make lifecycle
decisions.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.skill.resolution import SkillResolver
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution, SkillUsageEvent
from agent_core.domain.errors import ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import SkillUsageEventRepository
from agent_core.infrastructure.observability.metrics import observe_skill_usage_event


class SkillUsageService:
    def __init__(
        self,
        *,
        usage_repository: SkillUsageEventRepository,
        skill_resolver: SkillResolver,
        audit_service: AuditService,
    ) -> None:
        self._usage_repository = usage_repository
        self._skill_resolver = skill_resolver
        self._audit_service = audit_service

    async def resolve_for_runtime(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
    ) -> SkillResolution:
        resolution = await self._skill_resolver.resolve(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )
        if resolution.resolver_status in {"blocked", "incompatible"}:
            raise ValidationError(f"Skill resolution is {resolution.resolver_status}.")
        return resolution

    async def resolve_execution_plan(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        skill_binding: ActiveGoalSkillBinding | None = None,
    ) -> SkillExecutionPlan:
        resolution = await self.resolve_for_runtime(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )
        return await self._skill_resolver.build_execution_plan(
            resolution=resolution,
            skill_binding=skill_binding,
        )

    async def build_execution_plan_from_resolution(
        self,
        *,
        resolution: SkillResolution,
        skill_binding: ActiveGoalSkillBinding | None = None,
        tool_plan_override: list[dict[str, Any]] | None = None,
    ) -> SkillExecutionPlan:
        """Build an execution plan from an already-governed resolution.

        This avoids a second resolver pass so router-selected baseline or
        governed artifact decisions remain the effective runtime input.
        """
        return await self._skill_resolver.build_execution_plan(
            resolution=resolution,
            skill_binding=skill_binding,
            tool_plan_override=tool_plan_override,
        )

    async def record_usage(
        self,
        *,
        skill_name: str,
        surface: str,
        outcome_status: str,
        resolution: SkillResolution | None = None,
        learner_profile_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        daily_task_id: str | None = None,
        workflow_run_id: str | None = None,
        topic_key: str | None = None,
        trigger_source: str | None = None,
        latency_ms: int | None = None,
        cost_units: float | None = None,
        input_summary: str | None = None,
        input_fingerprint: str | None = None,
        output_summary: str | None = None,
        output_fingerprint: str | None = None,
        error_code: str | None = None,
        outcome_signals: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillUsageEvent | None:
        resolution_error_code: str | None = None
        if resolution is None:
            try:
                resolution = await self._skill_resolver.resolve(
                    skill_name=skill_name,
                    surface=surface,
                    resource_id=session_id or daily_task_id or workflow_run_id,
                )
            except ValidationError:
                resolution = SkillResolution.build(
                    skill_name=skill_name,
                    surface=surface,
                    artifact_id=None,
                    skill_version=None,
                    artifact_status=None,
                    resolver_status="blocked",
                    selection_reason="runtime_resolution_failed",
                    implementation_binding=skill_name,
                )
                resolution_error_code = "SkillResolutionValidationError"
        elif resolution.skill_name != skill_name or resolution.surface != surface:
            raise ValidationError("Skill resolution does not match usage context.")

        # Merge router explainability fields into usage metadata (backward-compatible).
        # These fields are populated when the SkillRouter is wired; otherwise they are None
        # and omitted from the metadata dict to keep the payload minimal.
        explain_extras: dict[str, Any] = {}
        if resolution.winner_candidate is not None:
            explain_extras["winner_candidate"] = resolution.winner_candidate
        if resolution.loser_reason_summary is not None:
            explain_extras["loser_reason_summary"] = resolution.loser_reason_summary
        if resolution.confidence is not None:
            explain_extras["confidence"] = resolution.confidence
        if resolution.fallback_chain is not None:
            explain_extras["fallback_chain"] = resolution.fallback_chain
        if resolution.template_id is not None:
            explain_extras["template_id"] = resolution.template_id
        if explain_extras:
            metadata = {**(metadata or {}), **explain_extras}

        event = SkillUsageEvent.build(
            skill_artifact_id=resolution.artifact_id,
            skill_name=resolution.skill_name,
            skill_version=resolution.skill_version,
            skill_status_at_use=resolution.artifact_status,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            surface=surface,
            topic_key=topic_key,
            trigger_source=trigger_source,
            outcome_status=outcome_status,
            latency_ms=latency_ms,
            cost_units=cost_units,
            input_summary=self._truncate(input_summary),
            input_fingerprint=input_fingerprint or self._fingerprint(input_summary),
            output_summary=self._truncate(output_summary),
            output_fingerprint=output_fingerprint or self._fingerprint(output_summary),
            error_code=error_code or resolution_error_code,
            resolver_status=resolution.resolver_status,
            selection_reason=resolution.selection_reason,
            outcome_signals=outcome_signals,
            metadata=metadata,
        )
        try:
            await self._persist_usage_event(event)
            return event
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="skill.usage.record_failed",
                resource_type="skill",
                resource_id=event.skill_artifact_id,
                actor="system",
                event_data={
                    "skill_name": event.skill_name,
                    "skill_version": event.skill_version,
                    "skill_status_at_use": event.skill_status_at_use,
                    "surface": event.surface,
                    "outcome_status": event.outcome_status,
                    "resolver_status": event.resolver_status,
                    "selection_reason": event.selection_reason,
                    "learner_profile_id": event.learner_profile_id,
                    "learner_goal_id": event.learner_goal_id,
                    "session_id": event.session_id,
                    "daily_task_id": event.daily_task_id,
                    "workflow_run_id": event.workflow_run_id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

    async def _persist_usage_event(self, event: SkillUsageEvent) -> None:
        await self._usage_repository.create(event)
        observe_skill_usage_event(
            surface=event.surface,
            outcome_status=event.outcome_status,
            resolver_status=event.resolver_status,
            selection_reason=event.selection_reason,
        )
        await self._audit_service.record(
            event_type="skill.usage.recorded",
            resource_type="skill",
            resource_id=event.skill_artifact_id,
            actor="system",
            event_data={
                "usage_event_id": event.id,
                "skill_name": event.skill_name,
                "skill_version": event.skill_version,
                "skill_status_at_use": event.skill_status_at_use,
                "surface": event.surface,
                "outcome_status": event.outcome_status,
                "resolver_status": event.resolver_status,
                "selection_reason": event.selection_reason,
                "learner_profile_id": event.learner_profile_id,
                "learner_goal_id": event.learner_goal_id,
                "session_id": event.session_id,
                "daily_task_id": event.daily_task_id,
                "workflow_run_id": event.workflow_run_id,
            },
        )

    async def list_usage_by_artifact(self, artifact_id: str, *, limit: int = 50) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_by_artifact(artifact_id, limit=bounded_limit(limit))

    async def list_usage(
        self,
        *,
        artifact_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        surface: str | None = None,
        outcome_status: str | None = None,
        resolver_status: str | None = None,
        limit: int = 50,
    ) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_events(
            artifact_id=artifact_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            surface=surface,
            outcome_status=outcome_status,
            resolver_status=resolver_status,
            limit=bounded_limit(limit),
        )

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if len(stripped) <= 500:
            return stripped
        return stripped[:497] + "..."

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            return sha256(b"").hexdigest()
        return sha256(normalized.encode("utf-8")).hexdigest()
