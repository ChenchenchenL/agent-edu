from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.domain.entities.reflection_closure import GoalSkillBinding
from agent_core.infrastructure.db.repositories import GoalSkillBindingRepository


@dataclass(frozen=True)
class ActiveGoalSkillBinding:
    binding_id: str
    proposal_id: str
    rollout_id: str
    learner_goal_id: str
    surface: str
    status: str
    priority_score: float
    match_rules: dict[str, Any]
    runtime_directives: dict[str, Any]
    tool_plan: list[dict[str, Any]]

    def usage_metadata(self, *, skill_name: str) -> dict[str, Any]:
        return {
            "skill_package_rollout": {
                "proposal_id": self.proposal_id,
                "rollout_id": self.rollout_id,
                "binding_id": self.binding_id,
                "skill_name": skill_name,
                "surface": self.surface,
                "binding_status": self.status,
            }
        }

    def with_usage_metadata(
        self,
        metadata: dict[str, object] | None,
        *,
        skill_name: str,
    ) -> dict[str, object]:
        return {
            **dict(metadata or {}),
            **self.usage_metadata(skill_name=skill_name),
        }


class GoalSkillBindingResolver:
    def __init__(self, *, repository: GoalSkillBindingRepository) -> None:
        self._repository = repository

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
        binding = await self._repository.get_active_by_goal_and_surface(learner_goal_id, surface)
        if binding is None:
            return None
        if binding.status == "staged" and not include_staged:
            return None
        if not self._matches(
            binding,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            goal_active_root_causes=goal_active_root_causes,
        ):
            return None
        return self._to_active(binding)

    @staticmethod
    def _matches(
        binding: GoalSkillBinding,
        *,
        topic_key: str | None,
        task_type: str | None,
        trigger_source: str | None,
        goal_active_root_causes: set[str] | None,
    ) -> bool:
        rules = binding.match_rules
        required_root_causes = {str(item) for item in rules.get("required_root_causes", []) if str(item)}
        if (
            required_root_causes
            and goal_active_root_causes is not None
            and not required_root_causes.intersection(goal_active_root_causes)
        ):
            return False
        topic_keys = {str(item) for item in rules.get("topic_keys", []) if str(item)}
        if topic_keys and (topic_key is None or topic_key not in topic_keys):
            return False
        task_types = {str(item) for item in rules.get("task_types", []) if str(item)}
        if task_types and (task_type is None or task_type not in task_types):
            return False
        trigger_sources = {str(item) for item in rules.get("trigger_sources", []) if str(item)}
        if trigger_sources and (trigger_source is None or trigger_source not in trigger_sources):
            return False
        return True

    @staticmethod
    def _to_active(binding: GoalSkillBinding) -> ActiveGoalSkillBinding:
        return ActiveGoalSkillBinding(
            binding_id=binding.id,
            proposal_id=binding.proposal_id,
            rollout_id=binding.rollout_id,
            learner_goal_id=binding.learner_goal_id,
            surface=binding.surface,
            status=binding.status,
            priority_score=binding.priority_score,
            match_rules=dict(binding.match_rules),
            runtime_directives=dict(binding.runtime_directives),
            tool_plan=[dict(item) for item in binding.tool_plan],
        )
