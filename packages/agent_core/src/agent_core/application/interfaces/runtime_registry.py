"""Dynamic runtime registry interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.dynamic_runtime_registry import RuntimeSkillExecutionPlan


class DynamicRuntimeRegistryProtocol(Protocol):
    """Contract for dynamic runtime execution plan resolution."""

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
        """Resolve a runtime execution plan for a surface."""
