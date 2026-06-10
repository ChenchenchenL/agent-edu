from __future__ import annotations

from time import perf_counter

from fastapi import Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, make_asgi_app, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

HTTP_REQUESTS_TOTAL = Counter(
    "agent_edu_http_requests_total",
    "Total number of HTTP requests handled by the API.",
    ["method", "route", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "agent_edu_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
LLM_OPERATIONS_TOTAL = Counter(
    "agent_edu_llm_operations_total",
    "Total number of LLM operations.",
    ["operation", "provider", "status"],
)
LLM_OPERATION_DURATION_SECONDS = Histogram(
    "agent_edu_llm_operation_duration_seconds",
    "LLM operation latency in seconds.",
    ["operation", "provider", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0),
)
EMBEDDING_OPERATIONS_TOTAL = Counter(
    "agent_edu_embedding_operations_total",
    "Total number of embedding-related operations.",
    ["operation", "provider", "status"],
)
EMBEDDING_OPERATION_DURATION_SECONDS = Histogram(
    "agent_edu_embedding_operation_duration_seconds",
    "Embedding operation latency in seconds.",
    ["operation", "provider", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
AUDIT_WRITES_TOTAL = Counter(
    "agent_edu_audit_writes_total",
    "Total number of audit write attempts.",
    ["mode", "status"],
)
AUDIT_WRITE_DURATION_SECONDS = Histogram(
    "agent_edu_audit_write_duration_seconds",
    "Audit write latency in seconds.",
    ["mode", "status"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
WORKFLOW_RUNS_TOTAL = Counter(
    "agent_edu_workflow_runs_total",
    "Total number of workflow runs by type and status.",
    ["workflow_type", "status"],
)
WORKFLOW_RUN_DURATION_SECONDS = Histogram(
    "agent_edu_workflow_run_latency_seconds",
    "Workflow run duration in seconds.",
    ["workflow_type", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
DAILY_TASK_STATUS_TRANSITIONS_TOTAL = Counter(
    "agent_edu_daily_task_status_transitions_total",
    "Total number of daily task status transitions.",
    ["from_status", "to_status", "task_type"],
)
PLAN_GENERATION_FALLBACK_TOTAL = Counter(
    "agent_edu_plan_generation_fallback_total",
    "Total number of plan generation fallback executions.",
)
MEMORY_GOVERNANCE_DECISIONS_TOTAL = Counter(
    "agent_edu_memory_governance_decisions_total",
    "Total number of long-term memory governance decisions.",
    ["memory_type", "decision_type", "trigger_source"],
)
MEMORY_MAINTENANCE_RUN_DURATION_SECONDS = Histogram(
    "agent_edu_memory_maintenance_run_duration_seconds",
    "Long-term memory maintenance run duration in seconds.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
MEMORY_MAINTENANCE_JOB_DURATION_SECONDS = Histogram(
    "agent_edu_memory_maintenance_job_duration_seconds",
    "Long-term memory maintenance job duration in seconds.",
    ["job_type", "status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
MEMORY_CANDIDATE_BACKLOG_GAUGE = Gauge(
    "agent_edu_memory_candidate_backlog",
    "Current long-term memory candidate backlog.",
    ["memory_type"],
)
MEMORY_CONFLICT_EVENTS_TOTAL = Counter(
    "agent_edu_memory_conflict_events_total",
    "Total number of long-term memory conflict events.",
    ["conflict_type", "event", "status"],
)
MEMORY_OPEN_CONFLICTS_GAUGE = Gauge(
    "agent_edu_memory_open_conflicts",
    "Current open long-term memory conflicts.",
    ["conflict_type"],
)
LONG_TERM_MEMORY_MATERIALIZATION_ATTEMPTS_TOTAL = Counter(
    "agent_edu_long_term_memory_materialization_total",
    "Total number of long-term memory materialization attempts.",
    ["source_type", "status", "reason_code"],
)
MEMORY_EVIDENCE_UPSERTS_TOTAL = Counter(
    "agent_edu_memory_evidence_upserts_total",
    "Total number of memory evidence link upserts.",
    ["memory_type", "evidence_source_type", "evidence_role"],
)
MEMORY_REFLECTION_BRIDGE_TOTAL = Counter(
    "agent_edu_memory_reflection_bridge_total",
    "Total number of reflection outcome bridges into long-term memory.",
    ["memory_type", "evaluation_status"],
)
MEMORY_RETRIEVAL_RESULTS_TOTAL = Counter(
    "agent_edu_memory_retrieval_results_total",
    "Total number of retrieved long-term memory results.",
    ["memory_type"],
)
MEMORY_RETRIEVAL_CANDIDATES_TOTAL = Counter(
    "agent_edu_memory_retrieval_candidates_total",
    "Total number of long-term memory retrieval candidates scored.",
    ["memory_type"],
)
MEMORY_QUALITY_TIER_TOTAL = Counter(
    "agent_edu_memory_quality_tier_total",
    "Total number of long-term memory quality assessments by tier.",
    ["memory_type", "quality_tier", "promotion_readiness"],
)
REFLECTION_VERDICTS_TOTAL = Counter(
    "agent_edu_reflection_verdict_total",
    "Total number of reflection verdicts generated.",
    ["verdict_code", "severity"],
)
REFLECTION_SESSION_SIGNAL_COVERAGE_TOTAL = Counter(
    "agent_edu_reflection_session_signal_coverage_total",
    "Total number of reflection session-signal aggregation results.",
    ["coverage"],
)
SKILL_RESOLUTIONS_TOTAL = Counter(
    "agent_edu_skill_resolutions_total",
    "Total number of skill resolver decisions.",
    ["surface", "resolver_status", "selection_reason"],
)
SKILL_USAGE_EVENTS_TOTAL = Counter(
    "agent_edu_skill_usage_events_total",
    "Total number of skill usage events.",
    ["surface", "outcome_status", "resolver_status", "selection_reason"],
)
SKILL_CURATOR_RECOMMENDATIONS_TOTAL = Counter(
    "agent_edu_skill_curator_recommendations_total",
    "Total number of skill curator recommendation lifecycle events.",
    ["recommendation_type", "reason_code", "event"],
)
SKILL_CURATOR_JOB_RUNS_TOTAL = Counter(
    "agent_edu_skill_curator_job_runs_total",
    "Total number of skill curator job executions.",
    ["status"],
)
SKILL_CURATOR_JOB_DURATION_SECONDS = Histogram(
    "agent_edu_skill_curator_job_duration_seconds",
    "Skill curator job duration in seconds.",
    ["status"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)
SKILL_REPLACEMENT_READINESS_TOTAL = Counter(
    "agent_edu_skill_replacement_readiness_total",
    "Total number of replacement readiness evaluations by action and result.",
    ["action", "status"],
)
SKILL_ROLLOUT_AUTO_DECISIONS_TOTAL = Counter(
    "agent_edu_skill_rollout_auto_decisions_total",
    "Total number of skill rollout auto-governance lifecycle events.",
    ["event", "decision", "surface", "reason_code"],
)
SKILL_ARTIFACTS_GAUGE = Gauge(
    "agent_edu_skill_artifacts",
    "Current number of skill artifacts by status.",
    ["status"],
)
SKILL_CURATOR_PENDING_RECOMMENDATIONS_GAUGE = Gauge(
    "agent_edu_skill_curator_pending_recommendations",
    "Current number of pending skill curator recommendations by type.",
    ["recommendation_type"],
)


def build_metrics_app():
    return make_asgi_app()


def build_metrics_response() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def observe_http_request(*, method: str, route: str, status_code: int | str, duration_seconds: float) -> None:
    status_label = str(status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status_code=status_label).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(max(duration_seconds, 0.0))


def observe_llm_operation(
    *,
    operation: str,
    provider: str | None,
    status: str,
    latency_ms: int,
) -> None:
    provider_label = provider or "unknown"
    LLM_OPERATIONS_TOTAL.labels(operation=operation, provider=provider_label, status=status).inc()
    LLM_OPERATION_DURATION_SECONDS.labels(
        operation=operation,
        provider=provider_label,
        status=status,
    ).observe(max(latency_ms, 0) / 1000)


def observe_embedding_operation(
    *,
    operation: str,
    provider: str | None,
    status: str,
    latency_ms: int,
) -> None:
    provider_label = provider or "unknown"
    EMBEDDING_OPERATIONS_TOTAL.labels(operation=operation, provider=provider_label, status=status).inc()
    EMBEDDING_OPERATION_DURATION_SECONDS.labels(
        operation=operation,
        provider=provider_label,
        status=status,
    ).observe(max(latency_ms, 0) / 1000)


def observe_audit_write(*, mode: str, status: str, duration_seconds: float) -> None:
    AUDIT_WRITES_TOTAL.labels(mode=mode, status=status).inc()
    AUDIT_WRITE_DURATION_SECONDS.labels(mode=mode, status=status).observe(max(duration_seconds, 0.0))


def observe_workflow_run(*, workflow_type: str, status: str, run) -> None:
    WORKFLOW_RUNS_TOTAL.labels(workflow_type=workflow_type, status=status).inc()
    if run.started_at is not None and run.finished_at is not None:
        duration_seconds = max((run.finished_at - run.started_at).total_seconds(), 0.0)
        WORKFLOW_RUN_DURATION_SECONDS.labels(workflow_type=workflow_type, status=status).observe(duration_seconds)


def observe_daily_task_status_transition(*, from_status: str, to_status: str, task_type: str) -> None:
    DAILY_TASK_STATUS_TRANSITIONS_TOTAL.labels(
        from_status=from_status,
        to_status=to_status,
        task_type=task_type,
    ).inc()


def observe_plan_generation_fallback() -> None:
    PLAN_GENERATION_FALLBACK_TOTAL.inc()


def observe_memory_governance_decision(*, memory_type: str, decision_type: str, trigger_source: str) -> None:
    MEMORY_GOVERNANCE_DECISIONS_TOTAL.labels(
        memory_type=memory_type,
        decision_type=decision_type,
        trigger_source=trigger_source,
    ).inc()


def observe_memory_maintenance_run(*, duration_seconds: float) -> None:
    MEMORY_MAINTENANCE_RUN_DURATION_SECONDS.observe(max(duration_seconds, 0.0))


def observe_memory_maintenance_job(*, job_type: str, status: str, duration_seconds: float) -> None:
    MEMORY_MAINTENANCE_JOB_DURATION_SECONDS.labels(
        job_type=job_type,
        status=status,
    ).observe(max(duration_seconds, 0.0))


def set_memory_candidate_backlog(*, memory_type: str, count: int) -> None:
    MEMORY_CANDIDATE_BACKLOG_GAUGE.labels(memory_type=memory_type).set(max(count, 0))


def observe_memory_conflict_event(*, conflict_type: str, event: str, status: str) -> None:
    MEMORY_CONFLICT_EVENTS_TOTAL.labels(
        conflict_type=conflict_type,
        event=event,
        status=status,
    ).inc()


def set_memory_open_conflicts(*, conflict_type: str, count: int) -> None:
    MEMORY_OPEN_CONFLICTS_GAUGE.labels(conflict_type=conflict_type).set(max(count, 0))


def observe_long_term_memory_materialization(*, source_type: str, status: str, reason_code: str | None = None) -> None:
    LONG_TERM_MEMORY_MATERIALIZATION_ATTEMPTS_TOTAL.labels(
        source_type=source_type,
        status=status,
        reason_code=reason_code or "none",
    ).inc()


def observe_memory_evidence_upsert(*, memory_type: str, evidence_source_type: str, evidence_role: str) -> None:
    MEMORY_EVIDENCE_UPSERTS_TOTAL.labels(
        memory_type=memory_type,
        evidence_source_type=evidence_source_type,
        evidence_role=evidence_role,
    ).inc()


def observe_memory_reflection_bridge(*, memory_type: str, evaluation_status: str) -> None:
    MEMORY_REFLECTION_BRIDGE_TOTAL.labels(
        memory_type=memory_type,
        evaluation_status=evaluation_status,
    ).inc()


def observe_memory_retrieval(*, memory_type: str, result_count: int, candidate_count: int) -> None:
    if result_count > 0:
        MEMORY_RETRIEVAL_RESULTS_TOTAL.labels(memory_type=memory_type).inc(result_count)
    if candidate_count > 0:
        MEMORY_RETRIEVAL_CANDIDATES_TOTAL.labels(memory_type=memory_type).inc(candidate_count)


def observe_memory_quality_assessment(*, memory_type: str, quality_tier: str, promotion_readiness: str) -> None:
    MEMORY_QUALITY_TIER_TOTAL.labels(
        memory_type=memory_type,
        quality_tier=quality_tier,
        promotion_readiness=promotion_readiness,
    ).inc()


def observe_reflection_verdict(*, verdict_code: str, severity: str) -> None:
    REFLECTION_VERDICTS_TOTAL.labels(verdict_code=verdict_code, severity=severity).inc()


def observe_reflection_session_signal_coverage(*, covered: bool) -> None:
    REFLECTION_SESSION_SIGNAL_COVERAGE_TOTAL.labels(
        coverage="covered" if covered else "empty",
    ).inc()


def observe_skill_resolution(*, surface: str, resolver_status: str, selection_reason: str) -> None:
    SKILL_RESOLUTIONS_TOTAL.labels(
        surface=surface,
        resolver_status=resolver_status,
        selection_reason=selection_reason,
    ).inc()


def observe_skill_usage_event(*, surface: str, outcome_status: str, resolver_status: str, selection_reason: str) -> None:
    SKILL_USAGE_EVENTS_TOTAL.labels(
        surface=surface,
        outcome_status=outcome_status,
        resolver_status=resolver_status,
        selection_reason=selection_reason,
    ).inc()


def observe_skill_curator_recommendation(*, recommendation_type: str, reason_code: str, event: str) -> None:
    SKILL_CURATOR_RECOMMENDATIONS_TOTAL.labels(
        recommendation_type=recommendation_type,
        reason_code=reason_code,
        event=event,
    ).inc()


def observe_skill_curator_job(*, status: str, duration_seconds: float) -> None:
    SKILL_CURATOR_JOB_RUNS_TOTAL.labels(status=status).inc()
    SKILL_CURATOR_JOB_DURATION_SECONDS.labels(status=status).observe(max(duration_seconds, 0.0))


def observe_skill_replacement_readiness(*, action: str, status: str) -> None:
    SKILL_REPLACEMENT_READINESS_TOTAL.labels(action=action, status=status).inc()


def observe_skill_rollout_auto_decision(
    *,
    event: str,
    decision: str,
    surface: str,
    reason_code: str,
) -> None:
    SKILL_ROLLOUT_AUTO_DECISIONS_TOTAL.labels(
        event=event,
        decision=decision,
        surface=surface,
        reason_code=reason_code,
    ).inc()


def set_skill_artifacts_total(*, status: str, count: int) -> None:
    SKILL_ARTIFACTS_GAUGE.labels(status=status).set(max(count, 0))


def set_skill_curator_pending_recommendations(*, recommendation_type: str, count: int) -> None:
    SKILL_CURATOR_PENDING_RECOMMENDATIONS_GAUGE.labels(
        recommendation_type=recommendation_type,
    ).set(max(count, 0))


class PrometheusHttpMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started_at = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_label = getattr(route, "path", request.url.path)
            observe_http_request(
                method=request.method,
                route=route_label,
                status_code=status_code,
                duration_seconds=perf_counter() - started_at,
            )
