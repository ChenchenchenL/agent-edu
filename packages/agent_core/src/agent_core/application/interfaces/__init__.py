"""Application-layer service interfaces.

These Protocols define the contracts used by service orchestration and
dependency injection without forcing explicit inheritance.
"""

from agent_core.application.interfaces.autonomy_jobs import AutonomyJobServiceProtocol
from agent_core.application.interfaces.chat import ChatServiceProtocol
from agent_core.application.interfaces.goal_skill_binding import GoalSkillBindingResolverProtocol
from agent_core.application.interfaces.memory import MemoryServiceProtocol
from agent_core.application.interfaces.planner import PlannerServiceProtocol
from agent_core.application.interfaces.quiz import QuizServiceProtocol
from agent_core.application.interfaces.reflection import (
    ReflectionEvidenceServiceProtocol,
    ReflectionOutcomeServiceProtocol,
    ReflectionServiceProtocol,
)
from agent_core.application.interfaces.rollouts import (
    RolloutObservationSchedulerProtocol,
    RolloutResolverProtocol,
)
from agent_core.application.interfaces.runtime_registry import DynamicRuntimeRegistryProtocol
from agent_core.application.interfaces.session import SessionServiceProtocol
from agent_core.application.interfaces.tool_plan_runtime import ToolPlanRuntimeExecutorProtocol
from agent_core.application.interfaces.workflow import WorkflowRunServiceProtocol

__all__ = [
    "AutonomyJobServiceProtocol",
    "ChatServiceProtocol",
    "DynamicRuntimeRegistryProtocol",
    "GoalSkillBindingResolverProtocol",
    "MemoryServiceProtocol",
    "PlannerServiceProtocol",
    "QuizServiceProtocol",
    "ReflectionEvidenceServiceProtocol",
    "ReflectionOutcomeServiceProtocol",
    "ReflectionServiceProtocol",
    "RolloutObservationSchedulerProtocol",
    "RolloutResolverProtocol",
    "SessionServiceProtocol",
    "ToolPlanRuntimeExecutorProtocol",
    "WorkflowRunServiceProtocol",
]
