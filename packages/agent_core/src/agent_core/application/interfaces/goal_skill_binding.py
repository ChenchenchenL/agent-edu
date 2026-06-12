"""Goal skill binding resolver interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding


class GoalSkillBindingResolverProtocol(Protocol):
    """Contract for resolving active goal skill bindings."""

    async def get_active_binding(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        goal_active_root_causes: set[str] | None = None,
        include_staged: bool = False,
    ) -> ActiveGoalSkillBinding | None:
        """Resolve the active goal-bound skill binding."""
