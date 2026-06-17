"""Tool-plan runtime executor interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.tool_plan_runtime import (
    MultiStepToolPlanExecutionReport,
    ToolPlanExecutionContext,
)


class ToolPlanRuntimeExecutorProtocol(Protocol):
    """Contract for executing a multi-step tool plan."""

    async def execute(
        self,
        *,
        tool_plan: list[dict[str, object]],
        context: ToolPlanExecutionContext,
    ) -> MultiStepToolPlanExecutionReport:
        """Execute a tool plan under the provided context."""
