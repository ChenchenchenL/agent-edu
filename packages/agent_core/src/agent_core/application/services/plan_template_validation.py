"""Unified plan template validator.

This module validates plan templates against surface policies and tool
capability contracts. It is the single validation entry point used by
artifact creation, sandbox preview, runtime execution, and curator
auto-stage paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.application.services.plan_templates import PlanTemplate, PlanTemplateStep
from agent_core.application.services.surface_policies import SurfacePolicy, get_surface_policy
from agent_core.application.services.tool_capabilities import (
    ToolCapability,
    get_capability,
    get_capability_by_tool_name,
)
from agent_core.domain.errors import ValidationError


@dataclass(frozen=True)
class TemplateValidationResult:
    valid: bool
    rejection_reason_codes: list[str]
    validated_template: PlanTemplate | None = None


class PlanTemplateValidator:
    def validate_template(
        self,
        *,
        template: PlanTemplate,
        surface: str | None = None,
    ) -> TemplateValidationResult:
        reasons: list[str] = []
        effective_surface = surface or template.surface

        policy = get_surface_policy(effective_surface)
        if policy is None:
            return TemplateValidationResult(
                valid=False,
                rejection_reason_codes=["unknown_surface"],
            )

        if template.surface != effective_surface:
            reasons.append("surface_mismatch")

        if not template.steps:
            reasons.append("empty_template")
            return TemplateValidationResult(valid=False, rejection_reason_codes=reasons)

        if not policy.allows_step_count(len(template.steps)):
            reasons.append("step_count_exceeds_policy")

        if not policy.allows_sequence(template.capability_sequence):
            reasons.append("unsupported_capability_sequence")

        seen_step_ids: set[str] = set()
        step_capabilities: dict[str, ToolCapability] = {}

        for step in template.steps:
            if step.step_id in seen_step_ids:
                reasons.append(f"duplicate_step_id:{step.step_id}")
            seen_step_ids.add(step.step_id)

            capability = get_capability(step.capability_id)
            if capability is None:
                capability = get_capability_by_tool_name(step.capability_id)
            if capability is None:
                reasons.append(f"unknown_capability:{step.capability_id}")
                continue

            if not policy.allows_capability(capability.capability_id):
                reasons.append(f"capability_not_allowed_on_surface:{capability.capability_id}")

            step_capabilities[step.step_id] = capability

            self._validate_step_variables(
                step=step,
                policy=policy,
                seen_step_ids_before_current=frozenset(seen_step_ids - {step.step_id}),
                step_capabilities=step_capabilities,
                reasons=reasons,
            )

        if template.requires_privileged_capability and not policy.requires_privileged_capability:
            pass

        return TemplateValidationResult(
            valid=len(reasons) == 0,
            rejection_reason_codes=reasons,
            validated_template=template if not reasons else None,
        )

    def validate_template_payload(
        self,
        *,
        template_data: dict[str, Any],
        surface: str,
    ) -> TemplateValidationResult:
        try:
            steps_data = template_data.get("steps") or []
            if not isinstance(steps_data, list):
                return TemplateValidationResult(
                    valid=False,
                    rejection_reason_codes=["invalid_steps_format"],
                )
            steps: list[PlanTemplateStep] = []
            capability_ids: list[str] = []
            for index, item in enumerate(steps_data):
                if not isinstance(item, dict):
                    return TemplateValidationResult(
                        valid=False,
                        rejection_reason_codes=["invalid_step_format"],
                    )
                step = PlanTemplateStep(
                    step_id=str(item.get("step_id") or "").strip() or f"step_{index + 1}",
                    capability_id=str(item.get("capability_id") or item.get("tool_name") or "").strip(),
                    payload_template=dict(item.get("payload_template") or {}),
                )
                steps.append(step)
                capability_ids.append(step.capability_id)

            from agent_core.application.services.plan_templates import (
                PlanTemplateOutputReferenceContract,
                PlanTemplateVariableContract,
            )

            template = PlanTemplate(
                template_id=str(template_data.get("template_id") or f"auto_{surface}"),
                surface=surface,
                capability_sequence=tuple(capability_ids),
                steps=tuple(steps),
                variable_contract=PlanTemplateVariableContract(
                    required_variables=frozenset(),
                    optional_variables=frozenset(),
                ),
                output_reference_contract=PlanTemplateOutputReferenceContract(
                    allowed_references=frozenset(),
                ),
                version=str(template_data.get("version") or "1.0"),
                template_source=str(template_data.get("template_source") or "artifact"),
                requires_privileged_capability=bool(template_data.get("requires_privileged_capability", False)),
                source_artifact_id=template_data.get("source_artifact_id"),
            )
            return self.validate_template(template=template, surface=surface)
        except (TypeError, ValueError) as exc:
            return TemplateValidationResult(
                valid=False,
                rejection_reason_codes=[f"parse_error:{type(exc).__name__}"],
            )

    def _validate_step_variables(
        self,
        *,
        step: PlanTemplateStep,
        policy: SurfacePolicy,
        seen_step_ids_before_current: frozenset[str],
        step_capabilities: dict[str, ToolCapability],
        reasons: list[str],
    ) -> None:
        for key, value in step.payload_template.items():
            if not isinstance(value, str) or not value.startswith("$"):
                continue

            if policy.allows_variable(value):
                continue

            ref = PlanTemplate.parse_step_reference(value)
            if ref is None:
                reasons.append(f"unsupported_variable:{value}")
                continue

            ref_step_id, field_name, index_value = ref

            if not policy.allows_prior_step_output_reads:
                reasons.append("prior_step_output_reads_not_allowed")
                continue

            if ref_step_id not in seen_step_ids_before_current:
                reasons.append(f"forward_reference:{ref_step_id}")
                continue

            ref_capability = step_capabilities.get(ref_step_id)
            if ref_capability is None:
                reasons.append(f"reference_to_unknown_step:{ref_step_id}")
                continue

            if not ref_capability.allows_output_reference(field_name, index_value):
                reasons.append(f"disallowed_output_reference:{ref_step_id}.{field_name}")
