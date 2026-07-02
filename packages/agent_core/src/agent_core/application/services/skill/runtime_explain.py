"""Runtime binding explain service.

Provides goal/surface scoped runtime binding explanation to operators,
making it clear why a specific artifact, binding, rollout, or static fallback
was chosen for the execution plan, without modifying the governed state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.application.services.skill.runtime_readiness import RuntimeBindingExplainResult

if TYPE_CHECKING:
    from agent_core.application.services.dynamic_runtime_registry import DynamicRuntimeRegistryService


class RuntimeExplainService:
    def __init__(
        self,
        *,
        dynamic_runtime_registry: "DynamicRuntimeRegistryService",
    ) -> None:
        self._dynamic_runtime_registry = dynamic_runtime_registry

    async def explain(
        self,
        *,
        learner_goal_id: str | None,
        skill_name: str,
        surface: str,
        resource_id: str = "explain",
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> RuntimeBindingExplainResult:
        """Explain the runtime binding selection for a given context.
        
        This method is side-effect free and intended for operator probe/explain usage.
        """
        runtime_plan = await self._dynamic_runtime_registry.resolve_runtime_plan(
            learner_goal_id=learner_goal_id,
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

        if runtime_plan is None:
            return RuntimeBindingExplainResult(
                skill_name=skill_name,
                surface=surface,
                source_summary={"error": "DynamicRuntimeRegistry unavailable"},
                resolution_summary={"resolver_status": "error", "selection_reason": "service_unavailable"},
                binding_summary=None,
                rollout_summary=None,
                tool_plan_summary=None,
                blocked_reason_codes=["service_unavailable"],
                fallback_reason_codes=["service_unavailable"],
            )

        # Build summaries
        source_summary = {
            "artifact_source": runtime_plan.source_summary.artifact_source,
            "directives_source": runtime_plan.source_summary.directives_source,
            "tool_plan_source": runtime_plan.source_summary.tool_plan_source,
            "include_staged": include_staged,
        }

        resolution_summary = {
            "resolver_status": runtime_plan.resolution.resolver_status,
            "selection_reason": runtime_plan.resolution.selection_reason,
            "artifact_id": runtime_plan.resolution.artifact_id,
            "artifact_status": runtime_plan.resolution.artifact_status,
            "implementation_binding": runtime_plan.resolution.implementation_binding,
        }

        binding_summary = None
        rollout_summary = None
        binding_id = runtime_plan.contract_summary.get("binding_id")
        rollout_id = runtime_plan.contract_summary.get("rollout_id")
        
        if binding_id:
            binding_summary = {"binding_id": binding_id}
        if rollout_id:
            rollout_summary = {"rollout_id": rollout_id}

        tool_plan_summary = None
        if runtime_plan.tool_plan:
            tool_plan_summary = {
                "enabled": True,
                "steps_count": len(runtime_plan.tool_plan),
                "source": runtime_plan.source_summary.tool_plan_source,
            }

        # Calculate blocked and fallback reasons
        blocked_reason_codes: list[str] = []
        fallback_reason_codes: list[str] = []
        
        status = runtime_plan.resolution.resolver_status
        if status == "blocked":
            blocked_reason_codes.append(runtime_plan.resolution.selection_reason)
        elif status == "incompatible":
            blocked_reason_codes.append("contract_incompatible")
            
        if status == "missing_artifact":
            fallback_reason_codes.append("static_fallback")
        elif status == "resolved" and runtime_plan.source_summary.artifact_source == "static_fallback":
            fallback_reason_codes.append("static_fallback")

        return RuntimeBindingExplainResult(
            skill_name=skill_name,
            surface=surface,
            source_summary=source_summary,
            resolution_summary=resolution_summary,
            binding_summary=binding_summary,
            rollout_summary=rollout_summary,
            tool_plan_summary=tool_plan_summary,
            blocked_reason_codes=blocked_reason_codes,
            fallback_reason_codes=fallback_reason_codes,
        )
