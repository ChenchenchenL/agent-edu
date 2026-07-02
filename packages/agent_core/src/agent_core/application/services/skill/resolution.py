"""Runtime skill resolution service.

This module provides runtime skill resolution based on artifact state,
learner goals, task context, and compatibility contracts. It constructs
SkillResolution and SkillExecutionPlan objects without modifying artifact
lifecycle state or writing usage events.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.repositories import SkillArtifactRepository
from agent_core.infrastructure.observability.metrics import observe_skill_resolution


class SkillResolver:
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

    async def resolve(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        audit: bool = True,
    ) -> SkillResolution:
        if not self._skill_registry.has_skill(skill_name):
            raise ValidationError(f"Skill '{skill_name}' is not enabled.")
        default_binding = self._skill_registry.default_handler_for_skill(skill_name)
        suppressed = await self._artifact_repository.get_suppressed_by_name_scope(name=skill_name, scope=surface)
        if suppressed is not None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=suppressed.id,
                skill_version=suppressed.version,
                artifact_status=suppressed.status,
                resolver_status="blocked",
                selection_reason="suppressed_artifact",
                implementation_binding=str(suppressed.compatibility_contract.get("implementation_binding") or default_binding),
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.blocked",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        artifact = await self._artifact_repository.get_selectable_by_name_scope(name=skill_name, scope=surface)
        if artifact is None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=None,
                skill_version=None,
                artifact_status=None,
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
                implementation_binding=default_binding,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.missing_artifact",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        implementation_binding = str(artifact.compatibility_contract.get("implementation_binding") or "")
        surfaces = artifact.compatibility_contract.get("surfaces")
        if (
            artifact.compatibility_contract.get("dynamic_execution") is not False
            or not implementation_binding
            or not self._skill_registry.has_runtime_handler(implementation_binding)
            or not self._skill_registry.supports_runtime_handler(implementation_binding, surface=surface)
            or not isinstance(surfaces, list)
            or surfaces != [surface]
        ):
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=artifact.id,
                skill_version=artifact.version,
                artifact_status=artifact.status,
                resolver_status="incompatible",
                selection_reason="contract_incompatible",
                implementation_binding=implementation_binding or default_binding,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.incompatible",
                    resource_id=resource_id,
                )
            observe_skill_resolution(
                surface=surface,
                resolver_status=resolution.resolver_status,
                selection_reason=resolution.selection_reason,
            )
            return resolution
        resolution = SkillResolution.build(
            skill_name=skill_name,
            surface=surface,
            artifact_id=artifact.id,
            skill_version=artifact.version,
            artifact_status=artifact.status,
            resolver_status="resolved",
            selection_reason="production_default",
            implementation_binding=implementation_binding,
        )
        observe_skill_resolution(
            surface=surface,
            resolver_status=resolution.resolver_status,
            selection_reason=resolution.selection_reason,
        )
        return resolution

    async def build_execution_plan(
        self,
        *,
        resolution: SkillResolution,
        skill_binding: ActiveGoalSkillBinding | None = None,
    ) -> SkillExecutionPlan:
        if resolution.resolver_status in {"blocked", "incompatible"}:
            raise ValidationError(f"Skill resolution is {resolution.resolver_status}.")
        base_runtime_directives: dict[str, Any] = {}
        base_tool_plan: list[dict[str, Any]] = []
        if resolution.artifact_id is not None:
            artifact = await self._artifact_repository.get_by_id(resolution.artifact_id)
            if artifact is None:
                raise ValidationError("Resolved skill artifact is missing.")
            base_runtime_directives = dict(artifact.runtime_directives)
            base_tool_plan = [dict(item) for item in artifact.tool_plan]
        binding_runtime_directives = (
            dict(skill_binding.runtime_directives)
            if skill_binding is not None
            else {}
        )
        effective_tool_plan = (
            [dict(item) for item in skill_binding.tool_plan]
            if skill_binding is not None and skill_binding.tool_plan
            else base_tool_plan
        )
        binding_metadata = (
            skill_binding.usage_metadata(skill_name=resolution.skill_name)
            if skill_binding is not None
            else {}
        )
        return SkillExecutionPlan(
            resolution=resolution,
            execution_kind=self._skill_registry.runtime_handler_execution_kind(resolution.implementation_binding),
            runtime_directives={
                **base_runtime_directives,
                **binding_runtime_directives,
            },
            tool_plan=effective_tool_plan,
            binding_metadata=binding_metadata,
        )

    async def _audit_resolution(
        self,
        resolution: SkillResolution,
        *,
        event_type: str,
        resource_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill",
            resource_id=resource_id or resolution.artifact_id,
            actor="system",
            event_data={
                "skill_name": resolution.skill_name,
                "surface": resolution.surface,
                "artifact_id": resolution.artifact_id,
                "skill_version": resolution.skill_version,
                "artifact_status": resolution.artifact_status,
                "resolver_status": resolution.resolver_status,
                "selection_reason": resolution.selection_reason,
                "implementation_binding": resolution.implementation_binding,
            },
        )
