from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.application.services.goal_skill_binding_resolver import (
    ActiveGoalSkillBinding,
    GoalSkillBindingResolver,
)
from agent_core.application.services.skill.usage import SkillUsageService
from agent_core.domain.entities.skill import SkillExecutionPlan


@dataclass(frozen=True)
class DynamicRuntimeSourceSummary:
    artifact_source: str
    directives_source: str
    tool_plan_source: str


@dataclass(frozen=True)
class RuntimeSkillExecutionPlan:
    plan: SkillExecutionPlan
    contract_summary: dict[str, Any]
    source_summary: DynamicRuntimeSourceSummary

    @property
    def resolution(self):
        return self.plan.resolution

    @property
    def execution_kind(self) -> str:
        return self.plan.execution_kind

    @property
    def runtime_directives(self) -> dict[str, Any]:
        return self.plan.runtime_directives

    @property
    def tool_plan(self) -> list[dict[str, Any]]:
        return self.plan.tool_plan

    @property
    def binding_metadata(self) -> dict[str, Any]:
        return self.plan.binding_metadata

    @property
    def implementation_binding(self) -> str:
        return self.plan.implementation_binding

    @property
    def artifact_id(self) -> str | None:
        return self.plan.artifact_id

    @property
    def artifact_status(self) -> str | None:
        return self.plan.artifact_status


class DynamicRuntimeRegistryService:
    def __init__(
        self,
        *,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None,
        skill_usage_service: SkillUsageService | None,
    ) -> None:
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._skill_usage_service = skill_usage_service

    async def resolve_runtime_plan(
        self,
        *,
        learner_goal_id: str | None,
        skill_name: str,
        surface: str,
        resource_id: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> RuntimeSkillExecutionPlan | None:
        if self._skill_usage_service is None:
            return None
        binding = await self._resolve_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )
        plan = await self._skill_usage_service.resolve_execution_plan(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            skill_binding=binding,
        )
        return self.build_runtime_plan(plan=plan, binding=binding)

    @classmethod
    def build_runtime_plan(
        cls,
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
    ) -> RuntimeSkillExecutionPlan:
        return RuntimeSkillExecutionPlan(
            plan=plan,
            contract_summary=cls._contract_summary(plan=plan, binding=binding),
            source_summary=cls._source_summary(plan=plan, binding=binding),
        )

    @staticmethod
    def runtime_metadata_for_usage(
        runtime_plan: RuntimeSkillExecutionPlan | None,
        *,
        base_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        metadata = dict(base_metadata or {})
        if runtime_plan is None:
            return metadata
        metadata.update(runtime_plan.binding_metadata)
        metadata.update(runtime_plan.contract_summary)
        metadata["source_summary"] = {
            "artifact_source": runtime_plan.source_summary.artifact_source,
            "directives_source": runtime_plan.source_summary.directives_source,
            "tool_plan_source": runtime_plan.source_summary.tool_plan_source,
        }
        return metadata

    @staticmethod
    def usage_metadata_for_plan(
        *,
        execution_plan: SkillExecutionPlan | None,
        runtime_plan: RuntimeSkillExecutionPlan | None,
        base_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if runtime_plan is not None:
            return DynamicRuntimeRegistryService.runtime_metadata_for_usage(
                runtime_plan,
                base_metadata=base_metadata,
            )
        metadata = dict(base_metadata or {})
        if execution_plan is None:
            return metadata
        metadata.update(execution_plan.binding_metadata)
        metadata["implementation_binding"] = execution_plan.implementation_binding
        metadata["execution_kind"] = execution_plan.execution_kind
        return metadata

    async def _resolve_binding(
        self,
        *,
        learner_goal_id: str | None,
        surface: str,
        topic_key: str | None,
        task_type: str | None,
        trigger_source: str | None,
        include_staged: bool,
    ) -> ActiveGoalSkillBinding | None:
        if self._goal_skill_binding_resolver is None or learner_goal_id is None:
            return None
        return await self._goal_skill_binding_resolver.get_active_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    @staticmethod
    def _contract_summary(
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
    ) -> dict[str, Any]:
        rollout = plan.binding_metadata.get("skill_package_rollout")
        rollout_id = None
        binding_id = None
        if isinstance(rollout, dict):
            rollout_id = rollout.get("rollout_id")
            binding_id = rollout.get("binding_id")
        return {
            "implementation_binding": plan.implementation_binding,
            "execution_kind": plan.execution_kind,
            "artifact_id": plan.artifact_id,
            "artifact_status": plan.artifact_status,
            "binding_id": binding_id or (binding.binding_id if binding is not None else None),
            "rollout_id": rollout_id or (binding.rollout_id if binding is not None else None),
            "tool_plan_enabled": bool(plan.tool_plan),
            "dynamic_registry_version": "v1",
        }

    @staticmethod
    def _source_summary(
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
    ) -> DynamicRuntimeSourceSummary:
        has_artifact = plan.artifact_id is not None
        has_binding = binding is not None
        artifact_source = "binding_overlay" if has_binding else "artifact"
        if not has_artifact:
            artifact_source = "static_fallback"
        directives_source = "binding_overlay" if has_binding and binding.runtime_directives else "artifact"
        if not plan.runtime_directives:
            directives_source = "none"
        tool_plan_source = "binding_overlay" if has_binding and binding.tool_plan else "artifact"
        if not plan.tool_plan:
            tool_plan_source = "none"
        return DynamicRuntimeSourceSummary(
            artifact_source=artifact_source,
            directives_source=directives_source,
            tool_plan_source=tool_plan_source,
        )
