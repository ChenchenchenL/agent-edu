from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.tool_plan_contracts import parse_step_reference, validate_tool_plan_contract
from agent_core.application.tools.registry import InternalToolRegistry, ToolExecutionRequest
from agent_core.domain.errors import ValidationError


@dataclass(frozen=True)
class ToolPlanExecutionContext:
    surface: str
    learner_goal_id: str
    resource_id: str
    actor: str
    source_task_id: str | None = None
    topic_focus: str | None = None
    study_plan_id: str | None = None
    workflow_run_id: str | None = None
    scheduled_job_id: str | None = None

    def template_values(self) -> dict[str, object]:
        values: dict[str, object] = {
            "$learner_goal_id": self.learner_goal_id,
        }
        if self.source_task_id is not None:
            values["$source_task_id"] = self.source_task_id
        if self.topic_focus is not None:
            values["$topic_focus"] = self.topic_focus
        if self.study_plan_id is not None:
            values["$study_plan_id"] = self.study_plan_id
        if self.workflow_run_id is not None:
            values["$workflow_run_id"] = self.workflow_run_id
        return values


@dataclass(frozen=True)
class ToolPlanStepDefinition:
    step_id: str
    tool_name: str
    payload_template: dict[str, Any]


@dataclass(frozen=True)
class ToolPlanStepResult:
    step_id: str
    tool_name: str
    resolved_payload: dict[str, Any]
    result_payload: dict[str, Any] | None
    dry_run: bool


@dataclass(frozen=True)
class MultiStepToolPlanExecutionReport:
    surface: str
    steps: list[ToolPlanStepResult]
    dry_run: bool


class ToolPlanRuntimeExecutor:
    def __init__(
        self,
        *,
        internal_tool_registry: InternalToolRegistry | None,
        audit_service: AuditService,
    ) -> None:
        self._internal_tool_registry = internal_tool_registry
        self._audit_service = audit_service

    async def execute(
        self,
        *,
        surface: str,
        tool_plan: list[dict[str, Any]],
        context: ToolPlanExecutionContext,
        dry_run: bool = False,
    ) -> MultiStepToolPlanExecutionReport:
        validate_tool_plan_contract(surface, tool_plan)
        if not tool_plan:
            raise ValidationError("Tool plan execution requires a non-empty tool_plan.")
        step_definitions = self._parse_steps(tool_plan)
        step_outputs: dict[str, dict[str, Any] | None] = {}
        step_results: list[ToolPlanStepResult] = []
        await self._audit_service.record(
            event_type="tool.plan.execution.started",
            resource_type="internal_tool_plan",
            resource_id=context.resource_id,
            actor=context.actor,
            event_data={
                "surface": surface,
                "sequence": [step.tool_name for step in step_definitions],
                "step_count": len(step_definitions),
                "dry_run": dry_run,
            },
        )
        try:
            for step_definition in step_definitions:
                resolved_payload = self._resolve_payload_template(
                    payload_template=step_definition.payload_template,
                    context=context,
                    step_outputs=step_outputs,
                )
                await self._audit_service.record(
                    event_type="tool.plan.step.started",
                    resource_type="internal_tool_plan",
                    resource_id=context.resource_id,
                    actor=context.actor,
                    event_data={
                        "surface": surface,
                        "step_id": step_definition.step_id,
                        "tool_name": step_definition.tool_name,
                        "dry_run": dry_run,
                        "resolved_payload": dict(resolved_payload),
                    },
                )
                try:
                    if dry_run:
                        result_payload = self._preview_result_payload(
                            tool_name=step_definition.tool_name,
                            resolved_payload=resolved_payload,
                        )
                    else:
                        if self._internal_tool_registry is None:
                            raise ValidationError("Tool plan runtime executor is missing an internal tool registry.")
                        result_payload = await self._internal_tool_registry.execute(
                            ToolExecutionRequest(
                                name=step_definition.tool_name,
                                payload=resolved_payload,
                                actor=context.actor,
                                resource_id=context.resource_id,
                                dry_run=False,
                            )
                        )
                except Exception as exc:
                    await self._audit_service.record_durable(
                        event_type="tool.plan.step.failed",
                        resource_type="internal_tool_plan",
                        resource_id=context.resource_id,
                        actor=context.actor,
                        event_data={
                            "surface": surface,
                            "step_id": step_definition.step_id,
                            "tool_name": step_definition.tool_name,
                            "dry_run": dry_run,
                            "resolved_payload": dict(resolved_payload),
                            "error": str(exc),
                            "error_code": type(exc).__name__,
                        },
                    )
                    raise
                step_outputs[step_definition.step_id] = result_payload
                step_result = ToolPlanStepResult(
                    step_id=step_definition.step_id,
                    tool_name=step_definition.tool_name,
                    resolved_payload=resolved_payload,
                    result_payload=result_payload,
                    dry_run=dry_run,
                )
                step_results.append(step_result)
                await self._audit_service.record(
                    event_type="tool.plan.step.completed",
                    resource_type="internal_tool_plan",
                    resource_id=context.resource_id,
                    actor=context.actor,
                    event_data={
                        "surface": surface,
                        "step_id": step_definition.step_id,
                        "tool_name": step_definition.tool_name,
                        "dry_run": dry_run,
                        "resolved_payload": dict(resolved_payload),
                        "result_payload": dict(result_payload or {}),
                    },
                )
            report = MultiStepToolPlanExecutionReport(
                surface=surface,
                steps=step_results,
                dry_run=dry_run,
            )
            await self._audit_service.record(
                event_type="tool.plan.execution.completed",
                resource_type="internal_tool_plan",
                resource_id=context.resource_id,
                actor=context.actor,
                event_data={
                    "surface": surface,
                    "sequence": [step.tool_name for step in step_definitions],
                    "step_count": len(step_definitions),
                    "dry_run": dry_run,
                },
            )
            return report
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="tool.plan.execution.failed",
                resource_type="internal_tool_plan",
                resource_id=context.resource_id,
                actor=context.actor,
                event_data={
                    "surface": surface,
                    "sequence": [step.tool_name for step in step_definitions],
                    "step_count": len(step_definitions),
                    "dry_run": dry_run,
                    "error": str(exc),
                    "error_code": type(exc).__name__,
                },
            )
            raise

    @staticmethod
    def _parse_steps(tool_plan: list[dict[str, Any]]) -> list[ToolPlanStepDefinition]:
        definitions: list[ToolPlanStepDefinition] = []
        for index, item in enumerate(tool_plan):
            step_id = str(item.get("step_id") or "").strip() or f"step_{index + 1}"
            tool_name = str(item.get("tool_name") or "").strip()
            payload_template = item.get("payload_template") or {}
            if not isinstance(payload_template, dict):
                raise ValidationError("Skill package tool_plan payload_template must be an object.")
            definitions.append(
                ToolPlanStepDefinition(
                    step_id=step_id,
                    tool_name=tool_name,
                    payload_template=dict(payload_template),
                )
            )
        return definitions

    @staticmethod
    def _resolve_payload_template(
        *,
        payload_template: dict[str, Any],
        context: ToolPlanExecutionContext,
        step_outputs: dict[str, dict[str, Any] | None],
    ) -> dict[str, Any]:
        resolved_payload: dict[str, Any] = {}
        for key, value in payload_template.items():
            resolved_payload[str(key)] = ToolPlanRuntimeExecutor._resolve_template_value(
                value=value,
                context=context,
                step_outputs=step_outputs,
            )
        return resolved_payload

    @staticmethod
    def _resolve_template_value(
        *,
        value: Any,
        context: ToolPlanExecutionContext,
        step_outputs: dict[str, dict[str, Any] | None],
    ) -> Any:
        if not isinstance(value, str) or not value.startswith("$"):
            return value
        template_values = context.template_values()
        if value in template_values:
            return template_values[value]
        step_reference = parse_step_reference(value)
        if step_reference is None:
            raise ValidationError(f"Tool plan template variable '{value}' is missing from runtime context.")
        return ToolPlanRuntimeExecutor._read_prior_step_output(step_reference=step_reference, step_outputs=step_outputs)

    @staticmethod
    def _preview_result_payload(
        *,
        tool_name: str,
        resolved_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name == "partial_replan":
            source_task_id = str(resolved_payload.get("source_task_id") or "unknown")
            return {
                "dry_run": True,
                "preview_payload": dict(resolved_payload),
                "created_task_ids": [f"preview-repair:{source_task_id}"],
            }
        if tool_name == "review_scheduling":
            source_task_id = str(resolved_payload.get("source_task_id") or "unknown")
            return {
                "dry_run": True,
                "preview_payload": dict(resolved_payload),
                "created_task_ids": [f"preview-review:{source_task_id}"],
            }
        return {"dry_run": True, "preview_payload": dict(resolved_payload)}

    @staticmethod
    def _read_prior_step_output(
        *,
        step_reference: tuple[str, str, int | None],
        step_outputs: dict[str, dict[str, Any] | None],
    ) -> Any:
        step_id, field_name, index_value = step_reference
        if step_id not in step_outputs:
            raise ValidationError(f"Tool plan step reference '{step_id}' is not available.")
        step_payload = step_outputs.get(step_id)
        if not isinstance(step_payload, dict):
            raise ValidationError(f"Tool plan step '{step_id}' does not expose a structured result payload.")
        if field_name not in step_payload:
            raise ValidationError(f"Tool plan step reference '{step_id}.{field_name}' is missing from step output.")
        resolved_value = step_payload[field_name]
        if index_value is None:
            return resolved_value
        if not isinstance(resolved_value, list):
            raise ValidationError(f"Tool plan step reference '{step_id}.{field_name}' is not indexable.")
        if index_value >= len(resolved_value):
            raise ValidationError(f"Tool plan step reference '{step_id}.{field_name}[{index_value}]' is out of range.")
        return resolved_value[index_value]
