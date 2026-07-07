"""Plan template contracts for the policy-driven template system.

This module defines PlanTemplate as the unit of execution planning. Templates
are provided by skill artifacts and selected by the runtime. Each template
declares its capability sequence, steps, variable contracts, output reference
contracts, and source metadata.

The runtime never generates plans — it only selects and fills templates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_STEP_REFERENCE_RE = re.compile(r"^\$steps\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_]+)(?:\[(\d+)\])?$")

TEMPLATE_SOURCE_ARTIFACT = "artifact"
TEMPLATE_SOURCE_BUILTIN = "builtin"
TEMPLATE_SOURCES = {"artifact", "builtin"}


@dataclass(frozen=True)
class PlanTemplateStep:
    step_id: str
    capability_id: str
    payload_template: dict[str, Any]

    def to_legacy_step(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool_name": self.capability_id,
            "payload_template": dict(self.payload_template),
        }


@dataclass(frozen=True)
class PlanTemplateVariableContract:
    required_variables: frozenset[str]
    optional_variables: frozenset[str]

    @property
    def all_variables(self) -> frozenset[str]:
        return self.required_variables | self.optional_variables


@dataclass(frozen=True)
class PlanTemplateOutputReferenceContract:
    allowed_references: frozenset[tuple[str, str, int | None]]

    def allows_reference(self, step_id: str, field_name: str, index: int | None = None) -> bool:
        return (step_id, field_name, index) in self.allowed_references


@dataclass(frozen=True)
class PlanTemplate:
    template_id: str
    surface: str
    capability_sequence: tuple[str, ...]
    steps: tuple[PlanTemplateStep, ...]
    variable_contract: PlanTemplateVariableContract
    output_reference_contract: PlanTemplateOutputReferenceContract
    version: str = "1.0"
    template_source: str = TEMPLATE_SOURCE_ARTIFACT
    requires_privileged_capability: bool = False
    source_artifact_id: str | None = None

    def to_legacy_tool_plan(self) -> list[dict[str, Any]]:
        return [step.to_legacy_step() for step in self.steps]

    @staticmethod
    def parse_step_reference(value: str) -> tuple[str, str, int | None] | None:
        matched = _STEP_REFERENCE_RE.match(value)
        if matched is None:
            return None
        step_id, field_name, index_value = matched.groups()
        return step_id, field_name, int(index_value) if index_value is not None else None


def build_plan_template_from_legacy_tool_plan(
    *,
    template_id: str,
    surface: str,
    tool_plan: list[dict[str, Any]],
    source_artifact_id: str | None = None,
    version: str = "1.0",
) -> PlanTemplate:
    steps: list[PlanTemplateStep] = []
    capability_ids: list[str] = []
    required_vars: set[str] = set()
    optional_vars: set[str] = set()
    allowed_refs: set[tuple[str, str, int | None]] = set()

    all_context_variables = {"$learner_goal_id", "$source_task_id", "$topic_focus", "$study_plan_id", "$workflow_run_id"}

    for index, item in enumerate(tool_plan):
        step_id = str(item.get("step_id") or "").strip() or f"step_{index + 1}"
        capability_id = str(item.get("tool_name") or "").strip()
        payload_template = dict(item.get("payload_template") or {})
        steps.append(PlanTemplateStep(step_id=step_id, capability_id=capability_id, payload_template=payload_template))
        capability_ids.append(capability_id)

        for value in payload_template.values():
            if not isinstance(value, str) or not value.startswith("$"):
                continue
            if value in all_context_variables:
                required_vars.add(value)
                continue
            ref = PlanTemplate.parse_step_reference(value)
            if ref is not None:
                allowed_refs.add(ref)

    return PlanTemplate(
        template_id=template_id,
        surface=surface,
        capability_sequence=tuple(capability_ids),
        steps=tuple(steps),
        variable_contract=PlanTemplateVariableContract(
            required_variables=frozenset(required_vars),
            optional_variables=frozenset(optional_vars),
        ),
        output_reference_contract=PlanTemplateOutputReferenceContract(
            allowed_references=frozenset(allowed_refs),
        ),
        version=version,
        template_source=TEMPLATE_SOURCE_ARTIFACT,
        source_artifact_id=source_artifact_id,
    )
