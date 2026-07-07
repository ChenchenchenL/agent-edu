"""Tool capability contracts for the policy-driven template system.

This module defines ToolCapability as the fundamental unit of tool abstraction.
Each capability declares its tool_name, input/output schemas, allowed output
references, audit category, and privilege profile. This replaces the bare
tool_name strings in the legacy tool_plan_contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OutputFieldSchema:
    field_name: str
    field_type: str
    indexable: bool = False
    description: str = ""


@dataclass(frozen=True)
class ToolCapability:
    capability_id: str
    tool_name: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    allowed_output_references: frozenset[tuple[str, int | None]]
    audit_category: str
    privilege_profile: str
    supports_dry_run: bool = True

    def allows_output_reference(self, field_name: str, index: int | None = None) -> bool:
        return (field_name, index) in self.allowed_output_references


_BUILTIN_CAPABILITIES: dict[str, ToolCapability] = {}


def _register_builtin(capability: ToolCapability) -> ToolCapability:
    _BUILTIN_CAPABILITIES[capability.capability_id] = capability
    return capability


REVIEW_SCHEDULING_CAPABILITY = _register_builtin(
    ToolCapability(
        capability_id="review_scheduling",
        tool_name="review_scheduling",
        input_schema={
            "type": "object",
            "properties": {
                "source_task_id": {"type": "string"},
            },
            "required": ["source_task_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "created_task_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        allowed_output_references=frozenset(),
        audit_category="internal_tool",
        privilege_profile="standard",
    )
)

ASSESSMENT_GENERATION_CAPABILITY = _register_builtin(
    ToolCapability(
        capability_id="assessment_generation",
        tool_name="assessment_generation",
        input_schema={
            "type": "object",
            "properties": {
                "learner_goal_id": {"type": "string"},
                "topic_focus": {"type": "string"},
            },
            "required": ["learner_goal_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "assessment_id": {"type": "string"},
                "question_count": {"type": "integer"},
            },
        },
        allowed_output_references=frozenset(),
        audit_category="internal_tool",
        privilege_profile="standard",
    )
)

PARTIAL_REPLAN_CAPABILITY = _register_builtin(
    ToolCapability(
        capability_id="partial_replan",
        tool_name="partial_replan",
        input_schema={
            "type": "object",
            "properties": {
                "source_task_id": {"type": "string"},
            },
            "required": ["source_task_id"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "created_task_ids": {"type": "array", "items": {"type": "string"}},
            },
        },
        allowed_output_references=frozenset({("created_task_ids", 0)}),
        audit_category="internal_tool",
        privilege_profile="standard",
    )
)

BUILTIN_CAPABILITIES: dict[str, ToolCapability] = dict(_BUILTIN_CAPABILITIES)

CAPABILITY_BY_TOOL_NAME: dict[str, ToolCapability] = {
    cap.tool_name: cap for cap in _BUILTIN_CAPABILITIES.values()
}


def get_capability(capability_id: str) -> ToolCapability | None:
    return _BUILTIN_CAPABILITIES.get(capability_id)


def get_capability_by_tool_name(tool_name: str) -> ToolCapability | None:
    return CAPABILITY_BY_TOOL_NAME.get(tool_name)


def list_capabilities() -> list[ToolCapability]:
    return list(_BUILTIN_CAPABILITIES.values())
