from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

import httpx

from agent_core.application.services.audit import AuditService
from agent_core.domain.errors import ValidationError

ToolKind = Literal["internal", "http"]
ToolRiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolExecutionRequest:
    name: str
    payload: dict[str, Any]
    actor: str
    resource_id: str
    dry_run: bool = False


@dataclass(frozen=True)
class ToolExecutionResult:
    payload: dict[str, Any] | None
    status_code: int | None = None
    latency_ms: int | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_level: ToolRiskLevel
    kind: ToolKind = "internal"
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]] | None = None


@dataclass(frozen=True)
class HttpToolSpec(ToolSpec):
    method: Literal["GET", "POST"] = "POST"
    url: str = ""
    timeout_seconds: float = 10.0
    allowed_statuses: tuple[int, ...] = (200,)
    enabled: bool = False

    def __post_init__(self) -> None:
        if self.kind != "http":
            object.__setattr__(self, "kind", "http")
        if not self.url.strip():
            raise ValidationError("HTTP tool spec requires a URL.")
        if self.handler is not None:
            raise ValidationError("HTTP tool spec must not define a handler.")


class InternalToolRegistry:
    def __init__(self, *, audit_service: AuditService, tools: list[ToolSpec] | None = None) -> None:
        self._audit_service = audit_service
        self._tools = {tool.name: tool for tool in (tools or [])}

    def register(self, tool: ToolSpec) -> None:
        self._tools[tool.name] = tool

    async def execute(self, request: ToolExecutionRequest) -> dict[str, Any] | None:
        tool = self._tools.get(request.name)
        if tool is None:
            raise ValidationError(f"Tool '{request.name}' is not registered.")
        await self._audit_service.record(
            event_type="tool.execution.started",
            resource_type="internal_tool",
            resource_id=request.resource_id,
            actor=request.actor,
            event_data={
                "tool_name": tool.name,
                "risk_level": tool.risk_level,
                "tool_kind": tool.kind,
                "endpoint": tool.url if isinstance(tool, HttpToolSpec) else None,
                "dry_run": request.dry_run,
            },
        )
        try:
            result = await self._execute_tool(tool, request.payload, dry_run=request.dry_run)
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="tool.execution.failed",
                resource_type="internal_tool",
                resource_id=request.resource_id,
                actor=request.actor,
                event_data={
                    "tool_name": tool.name,
                    "tool_kind": tool.kind,
                    "endpoint": tool.url if isinstance(tool, HttpToolSpec) else None,
                    "dry_run": request.dry_run,
                    "error": str(exc),
                },
            )
            raise
        await self._audit_service.record(
            event_type="tool.execution.completed",
            resource_type="internal_tool",
            resource_id=request.resource_id,
            actor=request.actor,
            event_data={
                "tool_name": tool.name,
                "tool_kind": tool.kind,
                "endpoint": tool.url if isinstance(tool, HttpToolSpec) else None,
                "dry_run": request.dry_run,
                "status_code": result.status_code,
                "latency_ms": result.latency_ms,
            },
        )
        return result.payload

    async def _execute_tool(self, tool: ToolSpec, payload: dict[str, Any], *, dry_run: bool) -> ToolExecutionResult:
        if isinstance(tool, HttpToolSpec):
            if dry_run:
                return ToolExecutionResult(payload={"dry_run": True, "preview_payload": dict(payload)})
            return await self._execute_http_tool(tool, payload)
        if tool.handler is None:
            raise ValidationError(f"Tool '{tool.name}' is missing a handler.")
        effective_payload = dict(payload)
        if dry_run:
            effective_payload["dry_run"] = True
        return ToolExecutionResult(payload=await tool.handler(effective_payload))

    async def _execute_http_tool(self, tool: HttpToolSpec, payload: dict[str, Any]) -> ToolExecutionResult:
        if not tool.enabled:
            raise ValidationError(f"HTTP tool '{tool.name}' is disabled.")
        async with httpx.AsyncClient(
            timeout=tool.timeout_seconds,
            follow_redirects=False,
            headers={"Content-Type": "application/json"},
        ) as client:
            response = await client.request(tool.method, tool.url, json=dict(payload))
        if response.status_code not in tool.allowed_statuses:
            raise ValidationError(f"HTTP tool '{tool.name}' returned status {response.status_code}.")
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.casefold():
            raise ValidationError(f"HTTP tool '{tool.name}' returned a non-JSON response.")
        try:
            body = response.json()
        except ValueError as exc:
            raise ValidationError(f"HTTP tool '{tool.name}' returned invalid JSON.") from exc
        if body is not None and not isinstance(body, dict):
            raise ValidationError(f"HTTP tool '{tool.name}' must return a JSON object.")
        latency_ms = None
        if hasattr(response, "_elapsed") and response.elapsed is not None:
            latency_ms = int(response.elapsed.total_seconds() * 1000)
        return ToolExecutionResult(payload=body, status_code=response.status_code, latency_ms=latency_ms)
