"""Legacy tool_plan contract validation.

This module is a **transitional bridge**. Phase 5 introduces a policy-driven
template system (tool_capabilities, surface_policies, plan_templates) that
replaces the hardcoded constants below. The legacy functions remain for
backward compatibility with existing callers but new code should use the
template validator directly.
"""
from __future__ import annotations

import re
from typing import Any

from agent_core.domain.errors import ValidationError


_SURFACE_ALLOWED_TOOL_NAMES: dict[str, set[str]] = {
    "review_scheduling": {"review_scheduling"},
    "assessment_generation": {"assessment_generation"},
    "replan": {"partial_replan", "review_scheduling"},
}

_SURFACE_ALLOWED_TEMPLATE_VARIABLES: dict[str, set[str]] = {
    "review_scheduling": {"$source_task_id"},
    "assessment_generation": {"$learner_goal_id", "$topic_focus"},
    "replan": {"$source_task_id"},
}

_SURFACE_ALLOWED_TOOL_SEQUENCES: dict[str, set[tuple[str, ...]]] = {
    "review_scheduling": {("review_scheduling",)},
    "assessment_generation": {("assessment_generation",)},
    "replan": {
        ("partial_replan",),
        ("partial_replan", "review_scheduling"),
    },
}

_TOOL_ALLOWED_OUTPUT_REFERENCES: dict[str, set[tuple[str, int | None]]] = {
    "partial_replan": {("created_task_ids", 0)},
    "review_scheduling": set(),
    "assessment_generation": set(),
}

_STEP_REFERENCE_RE = re.compile(r"^\$steps\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+)(?:\[(\d+)\])?$")


def allowed_tool_names_for_surface(surface: str) -> set[str]:
    return set(_SURFACE_ALLOWED_TOOL_NAMES.get(surface, set()))


def allowed_template_variables_for_surface(surface: str) -> set[str]:
    return set(_SURFACE_ALLOWED_TEMPLATE_VARIABLES.get(surface, set()))


def allowed_tool_sequences_for_surface(surface: str) -> set[tuple[str, ...]]:
    return set(_SURFACE_ALLOWED_TOOL_SEQUENCES.get(surface, set()))


def allowed_output_references_for_tool(tool_name: str) -> set[tuple[str, int | None]]:
    return set(_TOOL_ALLOWED_OUTPUT_REFERENCES.get(tool_name, set()))


def parse_step_reference(value: str) -> tuple[str, str, int | None] | None:
    matched = _STEP_REFERENCE_RE.match(value)
    if matched is None:
        return None
    step_id, field_name, index_value = matched.groups()
    return step_id, field_name, int(index_value) if index_value is not None else None


def validate_tool_plan_contract(surface: str, tool_plan: list[dict[str, Any]] | None) -> None:
    normalized_tool_plan = list(tool_plan or [])
    if surface == "plan_generation":
        if normalized_tool_plan:
            raise ValidationError("plan_generation does not support runtime tool_plan execution.")
        return
    if not normalized_tool_plan:
        return
    if len(normalized_tool_plan) > 2:
        raise ValidationError(f"{surface} runtime tool_plan supports at most 2 steps.")
    allowed_tool_names = allowed_tool_names_for_surface(surface)
    tool_sequence: list[str] = []
    seen_step_ids: set[str] = set()
    step_tools: dict[str, str] = {}
    allowed_variables = allowed_template_variables_for_surface(surface)
    require_explicit_step_id = len(normalized_tool_plan) > 1

    for index, item in enumerate(normalized_tool_plan):
        if not isinstance(item, dict):
            raise ValidationError("Skill package tool_plan items must be objects.")
        tool_name = str(item.get("tool_name") or "").strip()
        tool_sequence.append(tool_name)
        step_id = str(item.get("step_id") or "").strip()
        if require_explicit_step_id and not step_id:
            raise ValidationError("Multi-step tool_plan requires step_id on every step.")
        effective_step_id = step_id or f"step_{index + 1}"
        if effective_step_id in seen_step_ids:
            raise ValidationError("Skill package tool_plan step_id must be unique.")
        payload_template = item.get("payload_template") or {}
        if not isinstance(payload_template, dict):
            raise ValidationError("Skill package tool_plan payload_template must be an object.")
        if tool_name not in allowed_tool_names:
            raise ValidationError(f"{surface} runtime tool_plan contains an unsupported tool.")
        for value in payload_template.values():
            if not isinstance(value, str) or not value.startswith("$"):
                continue
            if value in allowed_variables:
                continue
            step_reference = parse_step_reference(value)
            if step_reference is None:
                raise ValidationError(f"{surface} runtime tool_plan contains an unsupported template variable.")
            referenced_step_id, field_name, index_value = step_reference
            if referenced_step_id not in seen_step_ids:
                raise ValidationError(f"{surface} runtime tool_plan may only reference prior step outputs.")
            referenced_tool_name = step_tools.get(referenced_step_id)
            if referenced_tool_name is None:
                raise ValidationError(f"{surface} runtime tool_plan references an unknown prior step.")
            if (field_name, index_value) not in allowed_output_references_for_tool(referenced_tool_name):
                raise ValidationError(
                    f"{surface} runtime tool_plan references an unsupported output field from step '{referenced_step_id}'."
                )
        step_tools[effective_step_id] = tool_name
        seen_step_ids.add(effective_step_id)

    if tuple(tool_sequence) not in allowed_tool_sequences_for_surface(surface):
        raise ValidationError(f"{surface} runtime tool_plan contains an unsupported tool sequence.")
