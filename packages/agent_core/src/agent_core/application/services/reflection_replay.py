from __future__ import annotations

from agent_core.application.services.audit import AuditService
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
        score_delta = self._score_delta(proposal, baseline_policy_snapshot, candidate_policy_snapshot)
        if score_delta >= 0.1:
            status = "effective"
        elif score_delta <= -0.05:
            status = "ineffective"
        else:
            status = "inconclusive"
        updated = evaluation.with_result(
            evaluation_status=status,
            simulated_outcome_summary={
                "proposal_type": proposal.proposal_type,
                "target_scope": proposal.target_scope,
                "score_delta": score_delta,
            },
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
                delta += 0.08
        if baseline_policy_snapshot == candidate_policy_snapshot:
            delta -= 0.05
        return delta
