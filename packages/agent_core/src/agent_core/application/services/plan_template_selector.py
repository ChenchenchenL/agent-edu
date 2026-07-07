"""Plan template selector service.

This module selects a compliant plan template from artifact-provided
candidates, validates it against surface policy, and fills runtime variables.
It cannot invent new plans — it only selects from pre-approved templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.application.services.plan_templates import PlanTemplate, build_plan_template_from_legacy_tool_plan
from agent_core.application.services.plan_template_validation import PlanTemplateValidator, TemplateValidationResult
from agent_core.application.services.surface_policies import get_surface_policy


@dataclass(frozen=True)
class PlanTemplateSelectionRequest:
    surface: str
    candidate_templates: list[PlanTemplate]
    runtime_variables: dict[str, Any]
    resource_id: str = ""


@dataclass(frozen=True)
class PlanTemplateSelectionResult:
    selected_template: PlanTemplate | None
    expanded_tool_plan: list[dict[str, Any]]
    rejected_templates: list[tuple[str, list[str]]]
    validation_result: TemplateValidationResult | None
    capability_sequence: tuple[str, ...]
    template_source: str
    policy_validated: bool


class PlanTemplateSelector:
    def __init__(self, *, validator: PlanTemplateValidator | None = None) -> None:
        self._validator = validator or PlanTemplateValidator()

    def select_template(self, request: PlanTemplateSelectionRequest) -> PlanTemplateSelectionResult:
        policy = get_surface_policy(request.surface)
        rejected: list[tuple[str, list[str]]] = []

        if not request.candidate_templates:
            return PlanTemplateSelectionResult(
                selected_template=None,
                expanded_tool_plan=[],
                rejected_templates=rejected,
                validation_result=None,
                capability_sequence=(),
                template_source="none",
                policy_validated=False,
            )

        for candidate in request.candidate_templates:
            result = self._validator.validate_template(template=candidate, surface=request.surface)
            if result.valid:
                missing_vars = candidate.variable_contract.required_variables - set(request.runtime_variables.keys())
                if missing_vars:
                    rejected.append((candidate.template_id, [f"missing_required_variables:{','.join(sorted(missing_vars))}"]))
                    continue
                expanded = candidate.to_legacy_tool_plan()
                return PlanTemplateSelectionResult(
                    selected_template=candidate,
                    expanded_tool_plan=expanded,
                    rejected_templates=rejected,
                    validation_result=result,
                    capability_sequence=candidate.capability_sequence,
                    template_source=candidate.template_source,
                    policy_validated=True,
                )
            rejected.append((candidate.template_id, result.rejection_reason_codes))

        return PlanTemplateSelectionResult(
            selected_template=None,
            expanded_tool_plan=[],
            rejected_templates=rejected,
            validation_result=None,
            capability_sequence=(),
            template_source="none",
            policy_validated=False,
        )

    def build_candidates_from_legacy_tool_plan(
        self,
        *,
        surface: str,
        tool_plan: list[dict[str, Any]],
        source_artifact_id: str | None = None,
    ) -> list[PlanTemplate]:
        if not tool_plan:
            return []
        template = build_plan_template_from_legacy_tool_plan(
            template_id=f"legacy_{surface}_{source_artifact_id or 'unknown'}",
            surface=surface,
            tool_plan=tool_plan,
            source_artifact_id=source_artifact_id,
        )
        return [template]

    def build_candidates_from_artifact_templates(
        self,
        *,
        plan_templates: list[dict[str, Any]],
        surface: str,
    ) -> list[PlanTemplate]:
        candidates: list[PlanTemplate] = []
        for template_data in plan_templates:
            if not isinstance(template_data, dict):
                continue
            steps_data = template_data.get("steps") or []
            if not isinstance(steps_data, list):
                continue
            from agent_core.application.services.plan_templates import (
                PlanTemplateOutputReferenceContract,
                PlanTemplateStep,
                PlanTemplateVariableContract,
            )
            steps: list[PlanTemplateStep] = []
            capability_ids: list[str] = []
            for index, item in enumerate(steps_data):
                if not isinstance(item, dict):
                    continue
                step = PlanTemplateStep(
                    step_id=str(item.get("step_id") or "").strip() or f"step_{index + 1}",
                    capability_id=str(item.get("capability_id") or item.get("tool_name") or "").strip(),
                    payload_template=dict(item.get("payload_template") or {}),
                )
                steps.append(step)
                capability_ids.append(step.capability_id)

            template = PlanTemplate(
                template_id=str(template_data.get("template_id") or f"tpl_{len(candidates)}"),
                surface=surface,
                capability_sequence=tuple(capability_ids),
                steps=tuple(steps),
                variable_contract=PlanTemplateVariableContract(
                    required_variables=frozenset(template_data.get("required_variables") or []),
                    optional_variables=frozenset(template_data.get("optional_variables") or []),
                ),
                output_reference_contract=PlanTemplateOutputReferenceContract(
                    allowed_references=frozenset(),
                ),
                version=str(template_data.get("version") or "1.0"),
                template_source=str(template_data.get("template_source") or "artifact"),
                requires_privileged_capability=bool(template_data.get("requires_privileged_capability", False)),
                source_artifact_id=template_data.get("source_artifact_id"),
            )
            candidates.append(template)
        return candidates
