"""Dynamic runtime registry interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.dynamic_runtime_registry import RuntimeSkillExecutionPlan
from agent_core.application.services.skill.capability import (
    CapabilityRequest,
    RuntimeCapabilityExecutionPlan,
)


class DynamicRuntimeRegistryProtocol(Protocol):
    """Contract for dynamic runtime execution plan resolution."""

    async def resolve_capability_request(
        self,
        request: CapabilityRequest,
        resource_id: str,
    ) -> RuntimeCapabilityExecutionPlan | None:
        """Resolve a capability-driven runtime execution plan.

        This is the primary entry point.  Legacy ``resolve_runtime_plan``
        is a compatibility bridge that delegates here.
        """
        ...

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
        """Compatibility bridge -- prefer ``resolve_capability_request``."""
        ...
