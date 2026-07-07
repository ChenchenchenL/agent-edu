"""Runtime binding explain service.

Provides goal/surface scoped runtime binding explanation to operators,
making it clear why a specific artifact, binding, rollout, or static fallback
was chosen for the execution plan, without modifying the governed state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_core.application.services.skill.capability import CapabilityRequest
from agent_core.application.services.skill.capability_bridge import CapabilityRequestBridge
from agent_core.application.services.skill.capability_catalog import resolve_capability_to_legacy
from agent_core.application.services.skill.runtime_readiness import RuntimeBindingExplainResult

if TYPE_CHECKING:
    from agent_core.application.services.dynamic_runtime_registry import DynamicRuntimeRegistryService


class RuntimeExplainService:
    def __init__(
        self,
        *,
        dynamic_runtime_registry: "DynamicRuntimeRegistryService",
        usage_repository: Any | None = None,
    ) -> None:
        self._dynamic_runtime_registry = dynamic_runtime_registry
        self._usage_repository = usage_repository

    async def explain_router_decision(
        self,
        request: CapabilityRequest,
        resource_id: str = "explain",
    ) -> dict[str, Any]:
        """Explain a full router decision with candidate ranking.

        Shows the capability request, all candidates, winner, loser
        reasons, confidence, and whether baseline fallback was used.
        The ``ranked_candidates`` and ``loser_reason_map`` fields are
        populated from the ``SkillRouterDecision`` so operators can see
        the full comparison that produced the winner.
        """
        runtime_result = await self._dynamic_runtime_registry.resolve_capability_request(
            request,
            resource_id=resource_id,
        )

        bridge_result = resolve_capability_to_legacy(
            request.capability,
            surface=request.surface,
        )

        result: dict[str, Any] = {
            "request": {
                "capability": request.capability,
                "surface": request.surface,
                "learner_goal_id": request.learner_goal_id,
                "topic_key": request.topic_key,
            },
            "bridge": {
                "mapped": bridge_result is not None,
                "legacy_skill_name": bridge_result[0] if bridge_result else None,
            },
        }

        if runtime_result is not None:
            sel = runtime_result.selection
            result["selection"] = {
                "requested_capability": sel.requested_capability,
                "selected_capability": sel.selected_capability,
                "selected_artifact_id": sel.selected_artifact_id,
                "legacy_skill_name": sel.legacy_skill_name,
                "reason_codes": sel.reason_codes,
                "fallback_chain": sel.fallback_chain,
                "confidence": sel.confidence,
                "bridge_version": sel.bridge_version,
                "resolution_mode": sel.resolution_mode,
                "template_id": sel.tool_plan_template_id,
            }

            # Expose full router decision detail for operator drill-down
            # (Phase 2 acceptance: show winner AND primary rejection reasons)
            decision = runtime_result.router_decision
            if decision is not None:
                ranked: list[dict[str, Any]] = []
                for c in decision.ranked_candidates:
                    ranked.append({
                        "candidate_id": c.candidate_id,
                        "source_type": c.source_type,
                        "skill_name": c.skill_name,
                        "artifact_id": c.artifact_id,
                        "artifact_status": c.artifact_status,
                        "total_score": c.total_score,
                        "sub_scores": c.sub_scores,
                        "trust_level": c.trust_level,
                        "failure_rate": c.failure_rate,
                        "rollback_pressure": c.rollback_pressure,
                        "eligible": c.eligible,
                        "ineligible_reason_codes": c.ineligible_reason_codes,
                        "reason_codes": c.reason_codes,
                    })
                result["router_decision"] = {
                    "baseline_used": decision.baseline_used,
                    "confidence": decision.confidence,
                    "routing_mode": decision.routing_mode,
                    "fallback_chain": decision.fallback_chain,
                    "selection_reason_codes": decision.selection_reason_codes,
                    "ranked_candidates": ranked,
                    "loser_reason_map": dict(decision.loser_reason_map),
                    "blocked_candidate_ids": list(decision.blocked_candidate_ids),
                }
            else:
                result["router_decision"] = None
        else:
            result["selection"] = None
            result["router_decision"] = None

        return result

    async def explain_capability(
        self,
        request: CapabilityRequest,
        resource_id: str = "explain",
    ) -> dict[str, Any]:
        """Explain a capability-driven resolution for operator drill-down.

        Returns a dictionary with the input request, bridge mapping,
        the resulting selection, and — when a SkillRouterService is wired —
        the full ``router_decision`` showing ranked candidates and loser
        reasons so operators can audit why a particular artifact won.
        """
        bridge_result = resolve_capability_to_legacy(
            request.capability,
            surface=request.surface,
        )
        bridge_info: dict[str, Any] = {
            "capability": request.capability,
            "surface": request.surface,
            "mapped": bridge_result is not None,
        }
        if bridge_result is not None:
            bridge_info["legacy_skill_name"] = bridge_result[0]
            bridge_info["effective_surface"] = bridge_result[1]

        runtime_result = await self._dynamic_runtime_registry.resolve_capability_request(
            request,
            resource_id=resource_id,
        )

        selection_info: dict[str, Any] = {}
        router_decision_info: dict[str, Any] | None = None

        if runtime_result is not None:
            sel = runtime_result.selection
            selection_info = {
                "requested_capability": sel.requested_capability,
                "selected_capability": sel.selected_capability,
                "selected_artifact_id": sel.selected_artifact_id,
                "legacy_skill_name": sel.legacy_skill_name,
                "reason_codes": sel.reason_codes,
                "fallback_chain": sel.fallback_chain,
                "confidence": sel.confidence,
                "bridge_version": sel.bridge_version,
                "resolution_mode": sel.resolution_mode,
                "template_id": sel.tool_plan_template_id,
            }

            # Phase 2: expose full router decision for operator audit
            decision = runtime_result.router_decision
            if decision is not None:
                ranked: list[dict[str, Any]] = []
                for c in decision.ranked_candidates:
                    ranked.append({
                        "candidate_id": c.candidate_id,
                        "source_type": c.source_type,
                        "skill_name": c.skill_name,
                        "artifact_id": c.artifact_id,
                        "artifact_status": c.artifact_status,
                        "total_score": c.total_score,
                        "sub_scores": c.sub_scores,
                        "trust_level": c.trust_level,
                        "failure_rate": c.failure_rate,
                        "eligible": c.eligible,
                        "ineligible_reason_codes": c.ineligible_reason_codes,
                    })
                router_decision_info = {
                    "baseline_used": decision.baseline_used,
                    "confidence": decision.confidence,
                    "routing_mode": decision.routing_mode,
                    "fallback_chain": decision.fallback_chain,
                    "selection_reason_codes": decision.selection_reason_codes,
                    "ranked_candidates": ranked,
                    "loser_reason_map": dict(decision.loser_reason_map),
                    "blocked_candidate_ids": list(decision.blocked_candidate_ids),
                }

        return {
            "request": {
                "capability": request.capability,
                "surface": request.surface,
                "learner_goal_id": request.learner_goal_id,
                "topic_key": request.topic_key,
                "task_type": request.task_type,
                "trigger_source": request.trigger_source,
                "risk_budget": request.risk_budget,
                "tenant_policy_id": request.tenant_policy_id,
            },
            "bridge": bridge_info,
            "selection": selection_info,
            "router_decision": router_decision_info,
        }

    async def explain(
        self,
        *,
        learner_goal_id: str | None,
        skill_name: str,
        surface: str,
        resource_id: str = "explain",
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> RuntimeBindingExplainResult:
        """Explain the runtime binding selection for a given context.
        
        This method is side-effect free and intended for operator probe/explain usage.
        """
        runtime_plan = await self._dynamic_runtime_registry.resolve_runtime_plan(
            learner_goal_id=learner_goal_id,
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

        if runtime_plan is None:
            return RuntimeBindingExplainResult(
                skill_name=skill_name,
                surface=surface,
                source_summary={"error": "DynamicRuntimeRegistry unavailable"},
                resolution_summary={"resolver_status": "error", "selection_reason": "service_unavailable"},
                binding_summary=None,
                rollout_summary=None,
                tool_plan_summary=None,
                blocked_reason_codes=["service_unavailable"],
                fallback_reason_codes=["service_unavailable"],
            )

        # Build summaries
        source_summary = {
            "artifact_source": runtime_plan.source_summary.artifact_source,
            "directives_source": runtime_plan.source_summary.directives_source,
            "tool_plan_source": runtime_plan.source_summary.tool_plan_source,
            "include_staged": include_staged,
        }

        resolution_summary = {
            "resolver_status": runtime_plan.resolution.resolver_status,
            "selection_reason": runtime_plan.resolution.selection_reason,
            "artifact_id": runtime_plan.resolution.artifact_id,
            "artifact_status": runtime_plan.resolution.artifact_status,
            "implementation_binding": runtime_plan.resolution.implementation_binding,
        }

        binding_summary = None
        rollout_summary = None
        binding_id = runtime_plan.contract_summary.get("binding_id")
        rollout_id = runtime_plan.contract_summary.get("rollout_id")
        
        if binding_id:
            binding_summary = {"binding_id": binding_id}
        if rollout_id:
            rollout_summary = {"rollout_id": rollout_id}

        tool_plan_summary = None
        if runtime_plan.tool_plan:
            tool_plan_summary = {
                "enabled": True,
                "steps_count": len(runtime_plan.tool_plan),
                "source": runtime_plan.source_summary.tool_plan_source,
            }

        # Calculate blocked and fallback reasons
        blocked_reason_codes: list[str] = []
        fallback_reason_codes: list[str] = []
        
        status = runtime_plan.resolution.resolver_status
        if status == "blocked":
            blocked_reason_codes.append(runtime_plan.resolution.selection_reason)
        elif status == "incompatible":
            blocked_reason_codes.append("contract_incompatible")
            
        if status == "missing_artifact":
            fallback_reason_codes.append("static_fallback")
        elif status == "resolved" and runtime_plan.source_summary.artifact_source == "static_fallback":
            fallback_reason_codes.append("static_fallback")

        return RuntimeBindingExplainResult(
            skill_name=skill_name,
            surface=surface,
            source_summary=source_summary,
            resolution_summary=resolution_summary,
            binding_summary=binding_summary,
            rollout_summary=rollout_summary,
            tool_plan_summary=tool_plan_summary,
            blocked_reason_codes=blocked_reason_codes,
            fallback_reason_codes=fallback_reason_codes,
        )

    async def trace_fallback(
        self,
        *,
        skill_name: str,
        surface: str,
        learner_goal_id: str | None = None,
    ) -> dict[str, Any]:
        """Trace fallback history for a skill/surface combination.

        Analyses recent usage events to compute fallback rate, baseline
        reliance rate, and common failure reasons.
        """
        events = await self._usage_repository.list_events(
            skill_name=skill_name,
            surface=surface,
            limit=50,
        )
        total = len(events)
        fallback_entries: list[dict[str, Any]] = []
        fallback_count = 0
        baseline_count = 0
        reason_freq: dict[str, int] = {}

        for event in events:
            meta = event.metadata or {}
            chain = meta.get("fallback_chain") or []
            conf = meta.get("confidence")
            has_fallback = bool(chain) or event.selection_reason in (
                "artifact_missing_static_fallback",
                "suppressed_artifact",
                "runtime_resolution_failed",
            )
            if has_fallback:
                fallback_count += 1
            if event.selection_reason == "artifact_missing_static_fallback":
                baseline_count += 1
            if event.outcome_status in ("failed", "aborted"):
                reason = event.error_code or event.outcome_status
                reason_freq[reason] = reason_freq.get(reason, 0) + 1

            fallback_entries.append({
                "usage_event_id": event.id,
                "fallback_chain": list(chain) if isinstance(chain, list) else [],
                "confidence": conf if isinstance(conf, (int, float)) else None,
                "resolver_status": event.resolver_status,
                "selection_reason": event.selection_reason,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            })

        common_reasons = sorted(
            [{"reason": k, "count": v} for k, v in reason_freq.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        return {
            "skill_name": skill_name,
            "surface": surface,
            "total_events": total,
            "fallback_history": fallback_entries[:20],
            "fallback_rate": round(fallback_count / total, 4) if total > 0 else 0.0,
            "baseline_reliance_rate": round(baseline_count / total, 4) if total > 0 else 0.0,
            "common_failure_reasons": common_reasons,
        }
