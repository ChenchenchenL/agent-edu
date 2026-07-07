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
EMBEDDING_DIMENSION_MISMATCH_TOTAL = Counter(
    "agent_edu_embedding_dimension_mismatch_total",
    "Total number of dimension mismatches during embedding scoring.",
    ["memory_type", "surface"],
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
MEMORY_PROMOTION_ELIGIBILITY_TOTAL = Counter(
    "agent_edu_memory_promotion_eligibility_total",
    "Total number of long-term memory promotion eligibility evaluations.",
    ["status", "memory_type"],
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
REFLECTION_EVIDENCE_DERIVATION_TOTAL = Counter(
    "agent_edu_reflection_evidence_derivation_total",
    "Total number of reflection evidence derivation attempts.",
    ["source_type", "status"],
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
SKILL_REPLACEMENT_AUTO_EXECUTION_TOTAL = Counter(
    "agent_edu_skill_replacement_auto_execution_total",
    "Total number of skill replacement auto-execution lifecycle events.",
    ["event", "action", "surface", "reason_code"],
)
REFLECTION_SKILL_EVOLUTION_TOTAL = Counter(
    "agent_edu_reflection_skill_evolution_total",
    "Total number of reflection skill evolution curator lifecycle events.",
    ["event", "reason_code"],
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
SKILL_ROUTER_INVOCATIONS_TOTAL = Counter(
    "agent_edu_skill_router_invocations_total",
    "Total number of skill router invocations.",
    ["capability", "surface"],
)
SKILL_ROUTER_CANDIDATES_TOTAL = Counter(
    "agent_edu_skill_router_candidates_total",
    "Total number of router candidates collected by source type.",
    ["source_type", "eligible"],
)
SKILL_ROUTER_WINNER_SOURCE_TOTAL = Counter(
    "agent_edu_skill_router_winner_source_total",
    "Winner source type distribution.",
    ["source_type"],
)
SKILL_ROUTER_FALLBACK_TOTAL = Counter(
    "agent_edu_skill_router_fallback_total",
    "Router fallback events by reason.",
    ["reason"],
)
SKILL_ROUTER_REJECTION_TOTAL = Counter(
    "agent_edu_skill_router_rejection_total",
    "Router candidate rejection reason distribution.",
    ["reason"],
)
SANDBOX_ADMISSION_TOTAL = Counter(
    "agent_edu_sandbox_admission_total",
    "Sandbox admission decisions by status and profile.",
    ["status", "profile"],
)
ACTIVATION_GOVERNANCE_TOTAL = Counter(
    "agent_edu_activation_governance_total",
    "Activation governance decisions by action and status.",
    ["action", "status"],
)
PRIVILEGE_DELTA_REJECTION_TOTAL = Counter(
    "agent_edu_privilege_delta_rejection_total",
    "Privilege delta rejections by action.",
    ["action"],
)
BROADEN_SCOPE_REJECTION_TOTAL = Counter(
    "agent_edu_broaden_scope_rejection_total",
    "Scope broadening rejections.",
    ["action"],
)
CURATOR_EXECUTION_TOTAL = Counter(
    "agent_edu_curator_execution_total",
    "Curator auto-execution events by status and reason.",
    ["event", "reason_code"],
)
PLAN_TEMPLATE_SELECTION_TOTAL = Counter(
    "agent_edu_plan_template_selection_total",
    "Plan template selection events by surface and outcome.",
    ["surface", "outcome", "template_source"],
)
PLAN_TEMPLATE_REJECTION_TOTAL = Counter(
    "agent_edu_plan_template_rejection_total",
    "Plan template rejection events by reason code.",
    ["surface", "reason_code"],
)
PLAN_TEMPLATE_VALIDATION_TOTAL = Counter(
    "agent_edu_plan_template_validation_total",
    "Plan template validation events by surface and result.",
    ["surface", "result"],
)
ROUTING_REGRESSION_TOTAL = Counter(
    "agent_edu_routing_regression_total",
    "Total number of routing regression events detected by curator.",
    ["skill_name", "surface"],
)
LOW_CONFIDENCE_BURST_TOTAL = Counter(
    "agent_edu_low_confidence_burst_total",
    "Total number of low-confidence selection burst events detected by curator.",
    ["skill_name", "surface"],
)
CORPUS_TRIGGER_REFLECTION_TOTAL = Counter(
    "agent_edu_corpus_trigger_reflection_total",
    "Total number of corpus-triggered reflection records created.",
    ["scope", "trigger_source"],
)
HIGH_RISK_AUTO_SANDBOX_TOTAL = Counter(
    "agent_edu_high_risk_auto_sandbox_total",
    "Total number of high-risk proposal auto-sandbox admissions.",
    ["proposal_type"],
)
SKILL_QUALITY_SCORE = Gauge(
    "agent_edu_skill_quality_score",
    "Current quality score of a skill artifact.",
    ["artifact_id", "skill_name", "surface"],
)
SKILL_OUTCOME_COMPLETION_RATE = Gauge(
    "agent_edu_skill_outcome_completion_rate",
    "Completion rate for a skill artifact over the feedback window.",
    ["artifact_id", "surface"],
)
SKILL_OUTCOME_FAILURE_RATE = Gauge(
    "agent_edu_skill_outcome_failure_rate",
    "Failure rate for a skill artifact over the feedback window.",
    ["artifact_id", "surface"],
)
SKILL_OUTCOME_CORRECTION_RATE = Gauge(
    "agent_edu_skill_outcome_correction_rate",
    "Correction rate for a skill artifact over the feedback window.",
    ["artifact_id", "surface"],
)
SKILL_AUTO_SUPPRESS_TOTAL = Counter(
    "agent_edu_skill_auto_suppress_total",
    "Total number of auto-suppress recommendations created by outcome feedback.",
    ["skill_name", "surface"],
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


def observe_memory_retrieval(
    *,
    memory_type: str,
    result_count: int,
    candidate_count: int,
    eligible_candidate_count: int = 0,
) -> None:
    if result_count > 0:
        MEMORY_RETRIEVAL_RESULTS_TOTAL.labels(memory_type=memory_type).inc(result_count)
    if candidate_count > 0:
        MEMORY_RETRIEVAL_CANDIDATES_TOTAL.labels(memory_type=memory_type).inc(candidate_count)
    if eligible_candidate_count > 0:
        MEMORY_RETRIEVAL_CANDIDATES_TOTAL.labels(memory_type=f"{memory_type}_eligible").inc(eligible_candidate_count)


def observe_memory_quality_assessment(*, memory_type: str, quality_tier: str, promotion_readiness: str) -> None:
    MEMORY_QUALITY_TIER_TOTAL.labels(
        memory_type=memory_type,
        quality_tier=quality_tier,
        promotion_readiness=promotion_readiness,
    ).inc()


def observe_memory_promotion_eligibility(*, memory_type: str, status: str) -> None:
    MEMORY_PROMOTION_ELIGIBILITY_TOTAL.labels(
        status=status,
        memory_type=memory_type,
    ).inc()


def observe_reflection_verdict(*, verdict_code: str, severity: str) -> None:
    REFLECTION_VERDICTS_TOTAL.labels(verdict_code=verdict_code, severity=severity).inc()


def observe_reflection_session_signal_coverage(*, covered: bool) -> None:
    REFLECTION_SESSION_SIGNAL_COVERAGE_TOTAL.labels(
        coverage="covered" if covered else "empty",
    ).inc()


def observe_reflection_evidence_derivation(*, source_type: str, status: str) -> None:
    REFLECTION_EVIDENCE_DERIVATION_TOTAL.labels(
        source_type=source_type,
        status=status,
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


def observe_skill_replacement_auto_execution(
    *,
    event: str,
    action: str,
    surface: str,
    reason_code: str,
) -> None:
    SKILL_REPLACEMENT_AUTO_EXECUTION_TOTAL.labels(
        event=event,
        action=action,
        surface=surface,
        reason_code=reason_code,
    ).inc()


def observe_reflection_skill_evolution(*, event: str, reason_code: str) -> None:
    REFLECTION_SKILL_EVOLUTION_TOTAL.labels(
        event=event,
        reason_code=reason_code,
    ).inc()


def observe_embedding_dimension_mismatch(*, memory_type: str, surface: str) -> None:
    EMBEDDING_DIMENSION_MISMATCH_TOTAL.labels(
        memory_type=memory_type,
        surface=surface,
    ).inc()


def observe_skill_router_decision(
    *,
    capability: str,
    surface: str,
    winner_source: str,
    candidate_count: int,
    baseline_used: bool,
    fallback_reasons: list[str] | None = None,
    rejection_reasons: list[str] | None = None,
) -> None:
    SKILL_ROUTER_INVOCATIONS_TOTAL.labels(capability=capability, surface=surface).inc()
    SKILL_ROUTER_WINNER_SOURCE_TOTAL.labels(source_type=winner_source).inc()
    if baseline_used:
        SKILL_ROUTER_FALLBACK_TOTAL.labels(reason="baseline_selected").inc()
    for reason in (fallback_reasons or []):
        SKILL_ROUTER_FALLBACK_TOTAL.labels(reason=reason).inc()
    for reason in (rejection_reasons or []):
        SKILL_ROUTER_REJECTION_TOTAL.labels(reason=reason).inc()


def observe_sandbox_admission(*, status: str, profile: str) -> None:
    SANDBOX_ADMISSION_TOTAL.labels(status=status, profile=profile).inc()


def observe_activation_governance(*, action: str, status: str) -> None:
    ACTIVATION_GOVERNANCE_TOTAL.labels(action=action, status=status).inc()


def observe_privilege_delta_rejection(*, action: str) -> None:
    PRIVILEGE_DELTA_REJECTION_TOTAL.labels(action=action).inc()


def observe_broaden_scope_rejection(*, action: str) -> None:
    BROADEN_SCOPE_REJECTION_TOTAL.labels(action=action).inc()


def observe_curator_execution(*, event: str, reason_code: str) -> None:
    CURATOR_EXECUTION_TOTAL.labels(event=event, reason_code=reason_code).inc()


def observe_plan_template_selection(*, surface: str, outcome: str, template_source: str) -> None:
    PLAN_TEMPLATE_SELECTION_TOTAL.labels(
        surface=surface,
        outcome=outcome,
        template_source=template_source,
    ).inc()


def observe_plan_template_rejection(*, surface: str, reason_code: str) -> None:
    PLAN_TEMPLATE_REJECTION_TOTAL.labels(surface=surface, reason_code=reason_code).inc()


def observe_plan_template_validation(*, surface: str, result: str) -> None:
    PLAN_TEMPLATE_VALIDATION_TOTAL.labels(surface=surface, result=result).inc()


def observe_routing_regression(*, skill_name: str, surface: str) -> None:
    """Increment routing regression counter (curator detects a routing degradation)."""
    ROUTING_REGRESSION_TOTAL.labels(skill_name=skill_name, surface=surface).inc()


def observe_low_confidence_burst(*, skill_name: str, surface: str) -> None:
    """Increment low-confidence burst counter (curator detects repeated sub-threshold confidence)."""
    LOW_CONFIDENCE_BURST_TOTAL.labels(skill_name=skill_name, surface=surface).inc()


def observe_corpus_trigger_reflection(*, scope: str, trigger_source: str) -> None:
    """Increment corpus-triggered reflection counter (reflection created by corpus evidence)."""
    CORPUS_TRIGGER_REFLECTION_TOTAL.labels(scope=scope, trigger_source=trigger_source).inc()


def observe_high_risk_auto_sandbox(*, proposal_type: str) -> None:
    """Increment high-risk auto-sandbox counter (high-risk proposal admitted to sandbox)."""
    HIGH_RISK_AUTO_SANDBOX_TOTAL.labels(proposal_type=proposal_type).inc()


def set_skill_artifacts_total(*, status: str, count: int) -> None:
    SKILL_ARTIFACTS_GAUGE.labels(status=status).set(max(count, 0))


def set_skill_curator_pending_recommendations(*, recommendation_type: str, count: int) -> None:
    SKILL_CURATOR_PENDING_RECOMMENDATIONS_GAUGE.labels(
        recommendation_type=recommendation_type,
    ).set(max(count, 0))


def observe_skill_quality(*, artifact_id: str, skill_name: str, surface: str, score: float) -> None:
    """Set the quality score gauge for a skill artifact."""
    SKILL_QUALITY_SCORE.labels(artifact_id=artifact_id, skill_name=skill_name, surface=surface).set(score)


def observe_skill_outcome_metrics(
    *, artifact_id: str, surface: str, completion_rate: float, failure_rate: float, correction_rate: float,
) -> None:
    """Set outcome metric gauges for a skill artifact."""
    SKILL_OUTCOME_COMPLETION_RATE.labels(artifact_id=artifact_id, surface=surface).set(completion_rate)
    SKILL_OUTCOME_FAILURE_RATE.labels(artifact_id=artifact_id, surface=surface).set(failure_rate)
    SKILL_OUTCOME_CORRECTION_RATE.labels(artifact_id=artifact_id, surface=surface).set(correction_rate)


def observe_skill_auto_suppress(*, skill_name: str, surface: str) -> None:
    """Increment auto-suppress counter when outcome feedback creates a suppress recommendation."""
    SKILL_AUTO_SUPPRESS_TOTAL.labels(skill_name=skill_name, surface=surface).inc()


# --- Phase 8 New Metrics ---

QUIZ_ATTEMPTS_TOTAL = Counter(
    "agent_edu_quiz_attempts_total",
    "Total number of quiz answer attempts.",
    ["topic_key", "is_correct"],
)

GRADING_FAILURES_TOTAL = Counter(
    "agent_edu_grading_failures_total",
    "Total number of grading failures.",
    ["grading_source"],
)

SCHEMA_VALIDATION_FAILURES_TOTAL = Counter(
    "agent_edu_schema_validation_failures_total",
    "Total number of schema validation failures.",
    ["schema_name"],
)

MASTERY_DELTA_DISTRIBUTION = Histogram(
    "agent_edu_mastery_delta_distribution",
    "Distribution of topic mastery score changes.",
    ["topic_key"],
    buckets=(-1.0, -0.5, -0.2, -0.1, 0.0, 0.1, 0.2, 0.5, 1.0),
)

ADAPTIVE_DIFFICULTY_CHANGES_TOTAL = Counter(
    "agent_edu_adaptive_difficulty_changes_total",
    "Total number of adaptive quiz difficulty changes.",
    ["from_difficulty", "to_difficulty"],
)

REPEATED_MISCONCEPTIONS_TOTAL = Counter(
    "agent_edu_repeated_misconceptions_total",
    "Total number of repeated misconceptions observed.",
    ["misconception_code"],
)

ANSWER_ATTEMPT_MATERIALIZATION_FAILURES_TOTAL = Counter(
    "agent_edu_answer_attempt_materialization_failures_total",
    "Total number of answer-attempt memory materialization failures.",
)

SKILL_LEARNING_GAIN_RATE = Gauge(
    "agent_edu_skill_learning_gain_rate",
    "Current learning gain rate per skill.",
    ["skill_name"],
)


def observe_quiz_attempt(*, topic_key: str, is_correct: bool) -> None:
    QUIZ_ATTEMPTS_TOTAL.labels(topic_key=topic_key, is_correct=str(is_correct)).inc()


def observe_grading_failure(*, grading_source: str) -> None:
    GRADING_FAILURES_TOTAL.labels(grading_source=grading_source).inc()


def observe_schema_validation_failure(*, schema_name: str) -> None:
    SCHEMA_VALIDATION_FAILURES_TOTAL.labels(schema_name=schema_name).inc()


def observe_mastery_delta(*, topic_key: str, delta: float) -> None:
    MASTERY_DELTA_DISTRIBUTION.labels(topic_key=topic_key).observe(delta)


def observe_adaptive_difficulty(*, from_difficulty: str, to_difficulty: str) -> None:
    ADAPTIVE_DIFFICULTY_CHANGES_TOTAL.labels(from_difficulty=from_difficulty, to_difficulty=to_difficulty).inc()


def observe_repeated_misconception(*, misconception_code: str) -> None:
    REPEATED_MISCONCEPTIONS_TOTAL.labels(misconception_code=misconception_code).inc()


def observe_answer_attempt_materialization_failure() -> None:
    ANSWER_ATTEMPT_MATERIALIZATION_FAILURES_TOTAL.inc()


def observe_skill_learning_gain(*, skill_name: str, gain_rate: float) -> None:
    SKILL_LEARNING_GAIN_RATE.labels(skill_name=skill_name).set(gain_rate)



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
            if request.url.path.startswith("/api/v1") and not route_label.startswith("/api/v1"):
                route_label = "/api/v1" + route_label
            observe_http_request(
                method=request.method,
                route=route_label,
                status_code=status_code,
                duration_seconds=perf_counter() - started_at,
            )
