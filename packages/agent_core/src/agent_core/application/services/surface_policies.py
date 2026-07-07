"""Surface policy contracts for the policy-driven template system.

This module defines SurfacePolicy as the governance boundary for each runtime
surface. Each policy declares which capabilities are allowed, the maximum step
count, which runtime variables are permitted, whether prior step outputs can be
read, and which capability combinations are permitted.

This replaces the _SURFACE_ALLOWED_* hardcoded constants in the legacy
tool_plan_contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SurfacePolicy:
    surface: str
    allowed_capability_ids: frozenset[str]
    max_step_count: int
    allowed_template_variables: frozenset[str]
    allows_prior_step_output_reads: bool
    allowed_capability_sequences: frozenset[tuple[str, ...]]
    requires_privileged_capability: bool = False

    def allows_capability(self, capability_id: str) -> bool:
        return capability_id in self.allowed_capability_ids

    def allows_sequence(self, sequence: tuple[str, ...]) -> bool:
        return sequence in self.allowed_capability_sequences

    def allows_variable(self, variable: str) -> bool:
        return variable in self.allowed_template_variables

    def allows_step_count(self, count: int) -> bool:
        return 0 < count <= self.max_step_count


_BUILTIN_POLICIES: dict[str, SurfacePolicy] = {}


def _register_builtin(policy: SurfacePolicy) -> SurfacePolicy:
    _BUILTIN_POLICIES[policy.surface] = policy
    return policy


REVIEW_SCHEDULING_POLICY = _register_builtin(
    SurfacePolicy(
        surface="review_scheduling",
        allowed_capability_ids=frozenset({"review_scheduling"}),
        max_step_count=1,
        allowed_template_variables=frozenset({"$source_task_id"}),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset({("review_scheduling",)}),
    )
)

ASSESSMENT_GENERATION_POLICY = _register_builtin(
    SurfacePolicy(
        surface="assessment_generation",
        allowed_capability_ids=frozenset({"assessment_generation"}),
        max_step_count=1,
        allowed_template_variables=frozenset({"$learner_goal_id", "$topic_focus"}),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset({("assessment_generation",)}),
    )
)

REPLAN_POLICY = _register_builtin(
    SurfacePolicy(
        surface="replan",
        allowed_capability_ids=frozenset({"partial_replan", "review_scheduling"}),
        max_step_count=2,
        allowed_template_variables=frozenset({"$source_task_id"}),
        allows_prior_step_output_reads=True,
        allowed_capability_sequences=frozenset({
            ("partial_replan",),
            ("partial_replan", "review_scheduling"),
        }),
    )
)

CHAT_POLICY = _register_builtin(
    SurfacePolicy(
        surface="chat",
        allowed_capability_ids=frozenset(),
        max_step_count=0,
        allowed_template_variables=frozenset(),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset(),
    )
)

HINT_POLICY = _register_builtin(
    SurfacePolicy(
        surface="hint",
        allowed_capability_ids=frozenset(),
        max_step_count=0,
        allowed_template_variables=frozenset(),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset(),
    )
)

QUIZ_POLICY = _register_builtin(
    SurfacePolicy(
        surface="quiz",
        allowed_capability_ids=frozenset(),
        max_step_count=0,
        allowed_template_variables=frozenset(),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset(),
    )
)

PLAN_GENERATION_POLICY = _register_builtin(
    SurfacePolicy(
        surface="plan_generation",
        allowed_capability_ids=frozenset(),
        max_step_count=0,
        allowed_template_variables=frozenset(),
        allows_prior_step_output_reads=False,
        allowed_capability_sequences=frozenset(),
    )
)

BUILTIN_POLICIES: dict[str, SurfacePolicy] = dict(_BUILTIN_POLICIES)


def get_surface_policy(surface: str) -> SurfacePolicy | None:
    return _BUILTIN_POLICIES.get(surface)


def require_surface_policy(surface: str) -> SurfacePolicy:
    policy = _BUILTIN_POLICIES.get(surface)
    if policy is None:
        from agent_core.domain.errors import ValidationError
        raise ValidationError(f"No surface policy defined for surface '{surface}'.")
    return policy


def list_surface_policies() -> list[SurfacePolicy]:
    return list(_BUILTIN_POLICIES.values())
