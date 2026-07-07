from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.application.services.tool_plan_sequence_governance import (
    build_tool_plan_sequence_contract,
    summarize_tool_plan_preview,
)
from agent_core.domain.entities.reflection_closure import ReflectionProposal, ReflectionProposalEvaluation
from agent_core.infrastructure.db.repositories import ReflectionProposalEvaluationRepository


class ReflectionReplayService:
    def __init__(
        self,
        *,
        repository: ReflectionProposalEvaluationRepository,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._audit_service = audit_service

    async def evaluate(
        self,
        *,
        proposal: ReflectionProposal,
        baseline_policy_snapshot: dict[str, object],
        candidate_policy_snapshot: dict[str, object],
        evaluator_type: str = "rule",
        sandbox_run_id: str | None = None,
        sandbox_context: dict[str, object] | None = None,
    ) -> ReflectionProposalEvaluation:
        existing = await self._repository.get_by_proposal(proposal.id)
        evaluation = existing or ReflectionProposalEvaluation.build(
            proposal_id=proposal.id,
            comparison_window_size=3,
            baseline_policy_snapshot=baseline_policy_snapshot,
            candidate_policy_snapshot=candidate_policy_snapshot,
            evaluator_type=evaluator_type,
            sandbox_run_id=sandbox_run_id,
        )
        if existing is None:
            await self._repository.create(evaluation)
        score_delta = self._score_delta(
            proposal,
            baseline_policy_snapshot,
            candidate_policy_snapshot,
            sandbox_context=sandbox_context,
        )
        if score_delta >= 0.1:
            status = "effective"
        elif score_delta <= -0.05:
            status = "ineffective"
        else:
            status = "inconclusive"
        simulated_outcome_summary = {
            "proposal_type": proposal.proposal_type,
            "target_scope": proposal.target_scope,
            "score_delta": score_delta,
        }
        if sandbox_context:
            contract_summary = sandbox_context.get("tool_plan_contract_summary")
            preview_summary = sandbox_context.get("tool_plan_preview_summary")
            if isinstance(contract_summary, dict):
                simulated_outcome_summary["tool_plan_contract_summary"] = dict(contract_summary)
            if isinstance(preview_summary, dict):
                simulated_outcome_summary["tool_plan_preview_summary"] = dict(preview_summary)
        updated = evaluation.with_result(
            evaluation_status=status,
            simulated_outcome_summary=simulated_outcome_summary,
            score_delta=score_delta,
            sandbox_run_id=sandbox_run_id,
        )
        await self._repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.replay.completed",
            resource_type="reflection_proposal_evaluation",
            resource_id=updated.id,
            actor="system",
            event_data={
                "proposal_id": proposal.id,
                "evaluation_status": updated.evaluation_status,
                "score_delta": updated.score_delta,
                "sandbox_run_id": sandbox_run_id,
                "evaluator_type": evaluator_type,
            },
        )
        return updated

    @staticmethod
    def _score_delta(
        proposal: ReflectionProposal,
        baseline_policy_snapshot: dict[str, object],
        candidate_policy_snapshot: dict[str, object],
        *,
        sandbox_context: dict[str, object] | None = None,
    ) -> float:
        delta = 0.0
        if proposal.proposal_type == "prompt_optimization":
            if candidate_policy_snapshot.get("response_preference_bias") == "guided":
                delta += 0.15
        if proposal.proposal_type == "workflow_optimization":
            if candidate_policy_snapshot.get("assessment_threshold_policy") == "earlier":
                delta += 0.1
            if candidate_policy_snapshot.get("replan_mode_policy") == "more_aggressive":
                delta += 0.05
        if proposal.proposal_type == "skill_package":
            runtime_directives = dict(candidate_policy_snapshot.get("runtime_directives") or {})
            tool_plan = list(candidate_policy_snapshot.get("tool_plan") or [])
            if proposal.target_scope in {"chat", "hint"} and runtime_directives.get("response_preference") == "guided":
                delta += 0.1
            if proposal.target_scope == "quiz" and runtime_directives.get("feedback_style") == "guided_correction":
                delta += 0.1
            if proposal.target_scope == "plan_generation" and runtime_directives.get("practice_density") == "high":
                delta += 0.08
            if proposal.target_scope in {"review_scheduling", "assessment_generation", "replan"} and tool_plan:
                delta += ReflectionReplayService._tool_plan_sequence_score_delta(
                    proposal=proposal,
                    candidate_policy_snapshot=candidate_policy_snapshot,
                    sandbox_context=sandbox_context,
                )
        if proposal.proposal_type == "skill_patch_request":
            usage_event_ids = list(candidate_policy_snapshot.get("usage_event_ids") or [])
            metrics_snapshot = dict(candidate_policy_snapshot.get("metrics_snapshot") or {})
            negative_rate = metrics_snapshot.get("negative_usage_rate")
            if len(usage_event_ids) >= 2:
                delta += 0.1
            if isinstance(negative_rate, (int, float)) and float(negative_rate) >= 0.4:
                delta += 0.05
        if proposal.proposal_type == "routing_policy":
            delta += ReflectionReplayService._evaluate_routing_policy_delta(proposal, candidate_policy_snapshot)
        if proposal.proposal_type == "template_policy":
            delta += ReflectionReplayService._evaluate_template_policy_delta(proposal, candidate_policy_snapshot)
        if baseline_policy_snapshot == candidate_policy_snapshot:
            delta -= 0.05
        return delta

    @staticmethod
    def _evaluate_routing_policy_delta(
        proposal: ReflectionProposal,
        candidate_policy_snapshot: dict[str, object],
    ) -> float:
        delta = 0.0
        evidence = proposal.evidence_snapshot or {}
        mismatches = evidence.get("router_mismatch_count") or evidence.get("fallback_burst_count", 0)
        rules = candidate_policy_snapshot.get("routing_rules") or {}
        
        if rules:
            delta += 0.05 * len(rules)
            if mismatches > 0:
                delta += min(0.12, 0.02 * mismatches)
        
        fallback = candidate_policy_snapshot.get("fallback_chain") or []
        if "dynamic_resolver" in fallback:
            delta += 0.05
        if candidate_policy_snapshot.get("ranking_policy") == "confidence_first":
            delta += 0.05
            
        return delta

    @staticmethod
    def _evaluate_template_policy_delta(
        proposal: ReflectionProposal,
        candidate_policy_snapshot: dict[str, object],
    ) -> float:
        delta = 0.0
        evidence = proposal.evidence_snapshot or {}
        mismatches = evidence.get("sequence_mismatch_count") or evidence.get("mismatch_count", 0)
        rules = candidate_policy_snapshot.get("template_rules") or {}
        
        if rules:
            delta += 0.05 * len(rules)
            if mismatches > 0:
                delta += min(0.12, 0.02 * mismatches)
                
        contract_version = candidate_policy_snapshot.get("sequence_contract")
        if contract_version and float(contract_version) >= 1.0:
            delta += 0.05
            
        return delta

    @staticmethod
    def _tool_plan_sequence_score_delta(
        *,
        proposal: ReflectionProposal,
        candidate_policy_snapshot: dict[str, object],
        sandbox_context: dict[str, object] | None,
    ) -> float:
        tool_plan = list(candidate_policy_snapshot.get("tool_plan") or [])
        contract = build_tool_plan_sequence_contract(surface=proposal.target_scope, tool_plan=tool_plan)
        if contract is None:
            return 0.0
        delta = 0.03
        preview_summary = sandbox_context.get("tool_plan_preview_summary") if isinstance(sandbox_context, dict) else None
        if not isinstance(preview_summary, dict):
            return delta
        if not bool(preview_summary.get("preview_available")):
            return delta
        if bool(preview_summary.get("preview_matches_contract")):
            delta += 0.05
            if contract.is_multi_step and not list(preview_summary.get("missing_required_outputs") or []):
                delta += 0.03
            return delta
        return delta - 0.13
