from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import SkillArtifactRepository, SkillUsageEventRepository


class SkillCatalogService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
        skill_registry: SkillRegistry,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service
        self._skill_registry = skill_registry

    async def list_artifacts(
        self,
        *,
        status: str | None = None,
        name: str | None = None,
        limit: int = 50,
    ) -> list[SkillArtifact]:
        return await self._artifact_repository.list_artifacts(
            status=status,
            name=name,
            limit=self._bounded_limit(limit),
        )

    async def get_artifact(self, artifact_id: str) -> SkillArtifact:
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        return artifact

    async def resolve_active_artifact(self, *, skill_name: str, surface: str, resource_id: str | None = None) -> SkillArtifact | None:
        if not self._skill_registry.has_skill(skill_name):
            raise ValidationError(f"Skill '{skill_name}' is not enabled.")
        artifact = await self._artifact_repository.get_active_by_name(skill_name)
        if artifact is None:
            await self._audit_service.record(
                event_type="skill.artifact.missing",
                resource_type="skill",
                resource_id=resource_id,
                actor="system",
                event_data={
                    "skill_name": skill_name,
                    "surface": surface,
                },
            )
        return artifact

    @staticmethod
    def _bounded_limit(limit: int) -> int:
        return max(1, min(limit, 200))


class SkillUsageService:
    def __init__(
        self,
        *,
        usage_repository: SkillUsageEventRepository,
        catalog_service: SkillCatalogService,
        audit_service: AuditService,
        db_session: AsyncSession | None = None,
    ) -> None:
        self._usage_repository = usage_repository
        self._catalog_service = catalog_service
        self._audit_service = audit_service
        self._db_session = db_session

    async def record_usage(
        self,
        *,
        skill_name: str,
        surface: str,
        outcome_status: str,
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
        output_summary: str | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillUsageEvent | None:
        artifact = await self._catalog_service.resolve_active_artifact(
            skill_name=skill_name,
            surface=surface,
            resource_id=session_id or daily_task_id or workflow_run_id,
        )
        event = SkillUsageEvent.build(
            skill_artifact_id=artifact.id if artifact is not None else None,
            skill_name=skill_name,
            skill_version=artifact.version if artifact is not None else None,
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
            output_summary=self._truncate(output_summary),
            error_code=error_code,
            metadata=metadata,
        )
        try:
            begin_nested = getattr(self._db_session, "begin_nested", None) if self._db_session is not None else None
            if begin_nested is None:
                await self._persist_usage_event(event)
            else:
                async with begin_nested():
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
                    "surface": event.surface,
                    "outcome_status": event.outcome_status,
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
        await self._audit_service.record(
            event_type="skill.usage.recorded",
            resource_type="skill",
            resource_id=event.skill_artifact_id,
            actor="system",
            event_data={
                "usage_event_id": event.id,
                "skill_name": event.skill_name,
                "skill_version": event.skill_version,
                "surface": event.surface,
                "outcome_status": event.outcome_status,
                "learner_profile_id": event.learner_profile_id,
                "learner_goal_id": event.learner_goal_id,
                "session_id": event.session_id,
                "daily_task_id": event.daily_task_id,
                "workflow_run_id": event.workflow_run_id,
            },
        )

    async def list_usage_by_artifact(self, artifact_id: str, *, limit: int = 50) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_by_artifact(artifact_id, limit=SkillCatalogService._bounded_limit(limit))

    async def list_usage(
        self,
        *,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        surface: str | None = None,
        limit: int = 50,
    ) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_events(
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            surface=surface,
            limit=SkillCatalogService._bounded_limit(limit),
        )

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if len(stripped) <= 500:
            return stripped
        return stripped[:497] + "..."
