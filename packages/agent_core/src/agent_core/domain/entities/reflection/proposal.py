from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

PROPOSAL_TYPES = {
    "prompt_optimization",
    "workflow_optimization",
    "skill_package",
    "skill_patch_request",
    "routing_policy",
    "template_policy",
}
PROPOSAL_TARGET_SCOPES = {"chat", "hint", "quiz", "plan_generation", "review_scheduling", "assessment_generation", "replan"}
PROPOSAL_STATUSES = {
    "proposed",
    "sandbox_queued",
    "sandbox_running",
    "sandbox_completed",
    "approved",
    "rejected",
    "archived",
}
PROPOSAL_EVALUATION_STATUSES = {"pending", "effective", "ineffective", "inconclusive"}
PROPOSAL_RISK_LEVELS = {"low", "medium", "high"}
PROPOSAL_SANDBOX_RUN_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
PROPOSAL_APPROVAL_DECISION_TYPES = {"approved", "rejected"}
PROPOSAL_SAMPLE_SOURCE_TYPES = {"session_messages", "task_attempts", "workflow_runs", "mixed"}
PROPOSAL_EVALUATOR_TYPES = {"rule", "archived_replay_live_llm"}
PROPOSAL_ROLLOUT_SURFACES = {
    "chat",
    "hint",
    "quiz",
    "plan_generation",
    "review_scheduling",
    "assessment_generation",
    "replan",
}
PROPOSAL_ROLLOUT_STATUSES = {"staged", "rolled_out", "rolled_back"}
PROPOSAL_ROLLOUT_DECISION_TYPES = {"activate", "promote", "rollback"}
PROPOSAL_ROLLOUT_RECOMMENDATIONS = {"collecting", "promote", "rollback", "neutral"}
PROMPT_POLICY_KEYS = {
    "response_preference_bias",
    "hint_level_preference",
    "teaching_goal_override",
}
WORKFLOW_POLICY_KEYS = {
    "review_interval_policy",
    "assessment_threshold_policy",
    "replan_mode_policy",
}
SKILL_POLICY_KEYS = {
    "artifact_kind",
    "skill_name",
    "bundle_id",
    "surface",
    "match_rules",
    "runtime_directives",
    "tool_plan",
    "scoring_contract",
}
SKILL_PATCH_REQUEST_POLICY_KEYS = {
    "artifact_id",
    "skill_name",
    "skill_version",
    "scope",
    "surface",
    "recommendation_id",
    "recommendation_reason_code",
    "usage_event_ids",
    "related_artifact_ids",
    "evidence_snapshot",
    "metrics_snapshot",
}
ROUTING_POLICY_KEYS = {
    "routing_rules",
    "fallback_chain",
    "trust_policy",
    "ranking_policy",
    "target_scope",
    "strategy_summary",
}
TEMPLATE_POLICY_KEYS = {
    "template_id",
    "sequence_contract",
    "template_rules",
    "target_scope",
    "strategy_summary",
}
SKILL_BINDING_STATUSES = {"staged", "rolled_out", "rolled_back"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _validate_score(name: str, value: float) -> None:
    if value < 0 or value > 1:
        raise ValidationError(f"{name} must be between 0 and 1.")


@dataclass(frozen=True)
class ReflectionProposal:
    id: str
    reflection_record_id: str
    learner_goal_id: str
    proposal_type: str
    target_scope: str
    status: str
    priority_score: float
    hypothesis: str
    change_summary: str
    structured_patch_payload: dict[str, Any]
    expected_improvement: str
    risk_level: str
    evidence_snapshot: dict[str, Any]
    evaluation_status: str
    evaluation_summary: str | None
    latest_sandbox_run_id: str | None
    approved_at: datetime | None
    approved_by: str | None
    approval_reason_code: str | None
    approval_note: str | None
    proposal_bundle_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        reflection_record_id: str,
        learner_goal_id: str,
        proposal_type: str,
        target_scope: str,
        priority_score: float,
        hypothesis: str,
        change_summary: str,
        structured_patch_payload: dict[str, Any],
        expected_improvement: str,
        risk_level: str,
        evidence_snapshot: dict[str, Any],
        proposal_bundle_id: str | None = None,
    ) -> "ReflectionProposal":
        if proposal_type not in PROPOSAL_TYPES:
            raise ValidationError("Unsupported reflection proposal type.")
        if target_scope not in PROPOSAL_TARGET_SCOPES:
            raise ValidationError("Unsupported reflection proposal target scope.")
        if risk_level not in PROPOSAL_RISK_LEVELS:
            raise ValidationError("Unsupported reflection proposal risk level.")
        _validate_score("priority_score", priority_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            proposal_type=proposal_type,
            target_scope=target_scope,
            status="proposed",
            priority_score=priority_score,
            hypothesis=hypothesis,
            change_summary=change_summary,
            structured_patch_payload=dict(structured_patch_payload),
            expected_improvement=expected_improvement,
            risk_level=risk_level,
            evidence_snapshot=dict(evidence_snapshot),
            evaluation_status="pending",
            evaluation_summary=None,
            latest_sandbox_run_id=None,
            approved_at=None,
            approved_by=None,
            approval_reason_code=None,
            approval_note=None,
            proposal_bundle_id=proposal_bundle_id,
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: str,
        *,
        evaluation_status: str | None = None,
        evaluation_summary: str | None | object = None,
        latest_sandbox_run_id: str | None | object = None,
        approved_at: datetime | None | object = None,
        approved_by: str | None | object = None,
        approval_reason_code: str | None | object = None,
        approval_note: str | None | object = None,
    ) -> "ReflectionProposal":
        if status not in PROPOSAL_STATUSES:
            raise ValidationError("Unsupported reflection proposal status.")
        next_evaluation_status = self.evaluation_status if evaluation_status is None else evaluation_status
        if next_evaluation_status not in PROPOSAL_EVALUATION_STATUSES:
            raise ValidationError("Unsupported reflection proposal evaluation status.")
        if status == "approved" and self.status != "sandbox_completed":
            raise ValidationError("Only sandbox-completed proposals can be approved.")
        if status == "sandbox_running" and self.status not in {"sandbox_queued", "sandbox_running"}:
            raise ValidationError("Sandbox can only run after queueing.")
        if status == "sandbox_completed" and self.status not in {"sandbox_running", "sandbox_completed"}:
            raise ValidationError("Sandbox can only complete from running state.")
        if status == "rejected" and self.status == "archived":
            raise ValidationError("Archived proposals cannot be rejected.")
        return ReflectionProposal(
            id=self.id,
            reflection_record_id=self.reflection_record_id,
            learner_goal_id=self.learner_goal_id,
            proposal_type=self.proposal_type,
            target_scope=self.target_scope,
            status=status,
            priority_score=self.priority_score,
            hypothesis=self.hypothesis,
            change_summary=self.change_summary,
            structured_patch_payload=dict(self.structured_patch_payload),
            expected_improvement=self.expected_improvement,
            risk_level=self.risk_level,
            evidence_snapshot=dict(self.evidence_snapshot),
            evaluation_status=next_evaluation_status,
            evaluation_summary=self.evaluation_summary if evaluation_summary is None else evaluation_summary,
            latest_sandbox_run_id=self.latest_sandbox_run_id if latest_sandbox_run_id is None else latest_sandbox_run_id,
            approved_at=self.approved_at if approved_at is None else approved_at,
            approved_by=self.approved_by if approved_by is None else approved_by,
            approval_reason_code=self.approval_reason_code if approval_reason_code is None else approval_reason_code,
            approval_note=self.approval_note if approval_note is None else approval_note,
            proposal_bundle_id=self.proposal_bundle_id,
            created_at=self.created_at,
            updated_at=_utcnow(),
        )

    def enqueue_sandbox(self, *, sandbox_run_id: str) -> "ReflectionProposal":
        if self.status in {"approved", "rejected", "archived"}:
            raise ValidationError("Only active proposals can be queued for sandbox.")
        return self.with_status(
            "sandbox_queued",
            latest_sandbox_run_id=sandbox_run_id,
            evaluation_status="pending",
            evaluation_summary=None,
        )

    def start_sandbox(self, *, sandbox_run_id: str) -> "ReflectionProposal":
        return self.with_status(
            "sandbox_running",
            latest_sandbox_run_id=sandbox_run_id,
        )

    def complete_sandbox(
        self,
        *,
        sandbox_run_id: str,
        evaluation_status: str,
        evaluation_summary: str,
    ) -> "ReflectionProposal":
        return self.with_status(
            "sandbox_completed",
            latest_sandbox_run_id=sandbox_run_id,
            evaluation_status=evaluation_status,
            evaluation_summary=evaluation_summary,
        )

    def approve(
        self,
        *,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> "ReflectionProposal":
        if self.status != "sandbox_completed":
            raise ValidationError("Only sandbox-completed proposals can be approved.")
        if self.evaluation_status == "ineffective":
            raise ValidationError("Ineffective proposals cannot be approved.")
        return self.with_status(
            "approved",
            approved_at=_utcnow(),
            approved_by=operator_id,
            approval_reason_code=reason_code,
            approval_note=reason_note,
        )

    def reject(
        self,
        *,
        evaluation_status: str | None = None,
        evaluation_summary: str | None = None,
    ) -> "ReflectionProposal":
        return self.with_status(
            "rejected",
            evaluation_status=self.evaluation_status if evaluation_status is None else evaluation_status,
            evaluation_summary=self.evaluation_summary if evaluation_summary is None else evaluation_summary,
        )


@dataclass(frozen=True)
class ReflectionProposalEvaluation:
    id: str
    proposal_id: str
    evaluation_status: str
    comparison_window_size: int
    baseline_policy_snapshot: dict[str, Any]
    candidate_policy_snapshot: dict[str, Any]
    simulated_outcome_summary: dict[str, Any]
    score_delta: float
    evaluator_type: str
    sandbox_run_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        comparison_window_size: int,
        baseline_policy_snapshot: dict[str, Any],
        candidate_policy_snapshot: dict[str, Any],
        evaluator_type: str,
        sandbox_run_id: str | None = None,
    ) -> "ReflectionProposalEvaluation":
        if comparison_window_size < 1:
            raise ValidationError("comparison_window_size must be positive.")
        if evaluator_type not in PROPOSAL_EVALUATOR_TYPES:
            raise ValidationError("Unsupported evaluator_type.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            proposal_id=proposal_id,
            evaluation_status="pending",
            comparison_window_size=comparison_window_size,
            baseline_policy_snapshot=dict(baseline_policy_snapshot),
            candidate_policy_snapshot=dict(candidate_policy_snapshot),
            simulated_outcome_summary={},
            score_delta=0.0,
            evaluator_type=evaluator_type,
            sandbox_run_id=sandbox_run_id,
            created_at=now,
            updated_at=now,
        )

    def with_result(
        self,
        *,
        evaluation_status: str,
        simulated_outcome_summary: dict[str, Any],
        score_delta: float,
        sandbox_run_id: str | None | object = None,
    ) -> "ReflectionProposalEvaluation":
        if evaluation_status not in PROPOSAL_EVALUATION_STATUSES:
            raise ValidationError("Unsupported reflection proposal evaluation status.")
        return ReflectionProposalEvaluation(
            id=self.id,
            proposal_id=self.proposal_id,
            evaluation_status=evaluation_status,
            comparison_window_size=self.comparison_window_size,
            baseline_policy_snapshot=dict(self.baseline_policy_snapshot),
            candidate_policy_snapshot=dict(self.candidate_policy_snapshot),
            simulated_outcome_summary=dict(simulated_outcome_summary),
            score_delta=score_delta,
            evaluator_type=self.evaluator_type,
            sandbox_run_id=self.sandbox_run_id if sandbox_run_id is None else sandbox_run_id,
            created_at=self.created_at,
            updated_at=_utcnow(),
        )


@dataclass(frozen=True)
class ReflectionProposalSandboxRun:
    id: str
    proposal_id: str
    learner_goal_id: str
    status: str
    sample_source_type: str
    sample_count: int
    provider: str | None
    model: str | None
    evaluator_type: str
    baseline_snapshot: dict[str, Any]
    candidate_snapshot: dict[str, Any]
    result_summary: dict[str, Any]
    score_delta: float
    error_code: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        learner_goal_id: str,
        sample_source_type: str,
        sample_count: int,
        provider: str | None,
        model: str | None,
        evaluator_type: str,
        baseline_snapshot: dict[str, Any],
        candidate_snapshot: dict[str, Any],
    ) -> "ReflectionProposalSandboxRun":
        if sample_source_type not in PROPOSAL_SAMPLE_SOURCE_TYPES:
            raise ValidationError("Unsupported proposal sample source type.")
        if evaluator_type not in PROPOSAL_EVALUATOR_TYPES:
            raise ValidationError("Unsupported evaluator_type.")
        if sample_count < 0:
            raise ValidationError("sample_count must be non-negative.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            proposal_id=proposal_id,
            learner_goal_id=learner_goal_id,
            status="queued",
            sample_source_type=sample_source_type,
            sample_count=sample_count,
            provider=provider,
            model=model,
            evaluator_type=evaluator_type,
            baseline_snapshot=dict(baseline_snapshot),
            candidate_snapshot=dict(candidate_snapshot),
            result_summary={},
            score_delta=0.0,
            error_code=None,
            started_at=None,
            completed_at=None,
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: str,
        *,
        result_summary: dict[str, Any] | None = None,
        score_delta: float | None = None,
        error_code: str | None | object = None,
    ) -> "ReflectionProposalSandboxRun":
        if status not in PROPOSAL_SANDBOX_RUN_STATUSES:
            raise ValidationError("Unsupported reflection proposal sandbox run status.")
        now = _utcnow()
        started_at = self.started_at
        completed_at = self.completed_at
        if status == "running" and started_at is None:
            started_at = now
        if status in {"completed", "failed", "cancelled"}:
            completed_at = now
        return ReflectionProposalSandboxRun(
            id=self.id,
            proposal_id=self.proposal_id,
            learner_goal_id=self.learner_goal_id,
            status=status,
            sample_source_type=self.sample_source_type,
            sample_count=self.sample_count,
            provider=self.provider,
            model=self.model,
            evaluator_type=self.evaluator_type,
            baseline_snapshot=dict(self.baseline_snapshot),
            candidate_snapshot=dict(self.candidate_snapshot),
            result_summary=dict(self.result_summary if result_summary is None else result_summary),
            score_delta=self.score_delta if score_delta is None else score_delta,
            error_code=self.error_code if error_code is None else error_code,
            started_at=started_at,
            completed_at=completed_at,
            created_at=self.created_at,
            updated_at=now,
        )


@dataclass(frozen=True)
class ReflectionProposalApprovalDecision:
    id: str
    proposal_id: str
    decision_type: str
    previous_status: str
    new_status: str
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        decision_type: str,
        previous_status: str,
        new_status: str,
        reason_code: str,
        reason_note: str | None,
        operator_id: str,
    ) -> "ReflectionProposalApprovalDecision":
        if decision_type not in PROPOSAL_APPROVAL_DECISION_TYPES:
            raise ValidationError("Unsupported reflection proposal approval decision type.")
        return cls(
            id=str(uuid4()),
            proposal_id=proposal_id,
            decision_type=decision_type,
            previous_status=previous_status,
            new_status=new_status,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
            created_at=_utcnow(),
        )


def proposal_policy_keys(proposal_type: str) -> set[str]:
    if proposal_type == "prompt_optimization":
        return set(PROMPT_POLICY_KEYS)
    if proposal_type == "workflow_optimization":
        return set(WORKFLOW_POLICY_KEYS)
    if proposal_type == "skill_package":
        return set(SKILL_POLICY_KEYS)
    if proposal_type == "skill_patch_request":
        return set(SKILL_PATCH_REQUEST_POLICY_KEYS)
    if proposal_type == "routing_policy":
        return set(ROUTING_POLICY_KEYS)
    if proposal_type == "template_policy":
        return set(TEMPLATE_POLICY_KEYS)
    raise ValidationError("Unsupported reflection proposal type.")


def proposal_rollout_surface(target_scope: str) -> str | None:
    if target_scope in PROPOSAL_ROLLOUT_SURFACES or target_scope == "quiz":
        return target_scope
    return None


@dataclass(frozen=True)
class ReflectionProposalRollout:
    id: str
    proposal_id: str
    learner_goal_id: str
    surface: str
    status: str
    baseline_snapshot: dict[str, Any]
    runtime_overlay_payload: dict[str, Any]
    latest_observation_id: str | None
    staged_plan_id: str | None
    rollback_restored_plan_id: str | None
    activated_by: str
    activated_at: datetime
    promoted_at: datetime | None
    rolled_back_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        learner_goal_id: str,
        surface: str,
        baseline_snapshot: dict[str, Any],
        runtime_overlay_payload: dict[str, Any],
        activated_by: str,
    ) -> "ReflectionProposalRollout":
        if surface not in PROPOSAL_ROLLOUT_SURFACES:
            raise ValidationError("Unsupported reflection proposal rollout surface.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            proposal_id=proposal_id,
            learner_goal_id=learner_goal_id,
            surface=surface,
            status="staged",
            baseline_snapshot=dict(baseline_snapshot),
            runtime_overlay_payload=dict(runtime_overlay_payload),
            latest_observation_id=None,
            staged_plan_id=None,
            rollback_restored_plan_id=None,
            activated_by=activated_by,
            activated_at=now,
            promoted_at=None,
            rolled_back_at=None,
            created_at=now,
            updated_at=now,
        )

    def with_status(
        self,
        status: str,
        *,
        latest_observation_id: str | None | object = None,
        staged_plan_id: str | None | object = None,
        rollback_restored_plan_id: str | None | object = None,
    ) -> "ReflectionProposalRollout":
        if status not in PROPOSAL_ROLLOUT_STATUSES:
            raise ValidationError("Unsupported reflection proposal rollout status.")
        if status == self.status:
            pass
        elif status == "rolled_out" and self.status != "staged":
            raise ValidationError("Only staged rollouts can be promoted.")
        elif status == "rolled_back" and self.status not in {"staged", "rolled_out"}:
            raise ValidationError("Only staged or rolled-out rollouts can be rolled back.")
        now = _utcnow()
        return ReflectionProposalRollout(
            id=self.id,
            proposal_id=self.proposal_id,
            learner_goal_id=self.learner_goal_id,
            surface=self.surface,
            status=status,
            baseline_snapshot=dict(self.baseline_snapshot),
            runtime_overlay_payload=dict(self.runtime_overlay_payload),
            latest_observation_id=self.latest_observation_id if latest_observation_id is None else latest_observation_id,
            staged_plan_id=self.staged_plan_id if staged_plan_id is None else staged_plan_id,
            rollback_restored_plan_id=(
                self.rollback_restored_plan_id
                if rollback_restored_plan_id is None
                else rollback_restored_plan_id
            ),
            activated_by=self.activated_by,
            activated_at=self.activated_at,
            promoted_at=now if status == "rolled_out" else self.promoted_at,
            rolled_back_at=now if status == "rolled_back" else self.rolled_back_at,
            created_at=self.created_at,
            updated_at=now,
        )


@dataclass(frozen=True)
class GoalSkillBinding:
    id: str
    proposal_id: str
    rollout_id: str
    learner_goal_id: str
    surface: str
    status: str
    priority_score: float
    match_rules: dict[str, Any]
    runtime_directives: dict[str, Any]
    tool_plan: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    rolled_back_at: datetime | None

    @classmethod
    def build(
        cls,
        *,
        proposal_id: str,
        rollout_id: str,
        learner_goal_id: str,
        surface: str,
        priority_score: float,
        match_rules: dict[str, Any],
        runtime_directives: dict[str, Any],
        tool_plan: list[dict[str, Any]],
    ) -> "GoalSkillBinding":
        if surface not in PROPOSAL_TARGET_SCOPES:
            raise ValidationError("Unsupported goal skill binding surface.")
        _validate_score("priority_score", priority_score)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            proposal_id=proposal_id,
            rollout_id=rollout_id,
            learner_goal_id=learner_goal_id,
            surface=surface,
            status="staged",
            priority_score=priority_score,
            match_rules=dict(match_rules),
            runtime_directives=dict(runtime_directives),
            tool_plan=[dict(item) for item in tool_plan],
            created_at=now,
            updated_at=now,
            activated_at=now,
            rolled_back_at=None,
        )

    def with_status(self, status: str) -> "GoalSkillBinding":
        if status not in SKILL_BINDING_STATUSES:
            raise ValidationError("Unsupported goal skill binding status.")
        now = _utcnow()
        return GoalSkillBinding(
            id=self.id,
            proposal_id=self.proposal_id,
            rollout_id=self.rollout_id,
            learner_goal_id=self.learner_goal_id,
            surface=self.surface,
            status=status,
            priority_score=self.priority_score,
            match_rules=dict(self.match_rules),
            runtime_directives=dict(self.runtime_directives),
            tool_plan=[dict(item) for item in self.tool_plan],
            created_at=self.created_at,
            updated_at=now,
            activated_at=self.activated_at,
            rolled_back_at=now if status == "rolled_back" else self.rolled_back_at,
        )


@dataclass(frozen=True)
class ReflectionProposalRolloutObservation:
    id: str
    rollout_id: str
    proposal_id: str
    learner_goal_id: str
    surface: str
    recommendation: str
    observed_sample_count: int
    positive_score: float
    negative_score: float
    signal_summary: dict[str, Any]
    reason_codes: list[str]
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        rollout_id: str,
        proposal_id: str,
        learner_goal_id: str,
        surface: str,
        recommendation: str,
        observed_sample_count: int,
        positive_score: float,
        negative_score: float,
        signal_summary: dict[str, Any],
        reason_codes: list[str],
    ) -> "ReflectionProposalRolloutObservation":
        if surface not in PROPOSAL_ROLLOUT_SURFACES:
            raise ValidationError("Unsupported reflection proposal rollout surface.")
        if recommendation not in PROPOSAL_ROLLOUT_RECOMMENDATIONS:
            raise ValidationError("Unsupported reflection proposal rollout recommendation.")
        if observed_sample_count < 0:
            raise ValidationError("observed_sample_count must be non-negative.")
        _validate_score("positive_score", positive_score)
        _validate_score("negative_score", negative_score)
        return cls(
            id=str(uuid4()),
            rollout_id=rollout_id,
            proposal_id=proposal_id,
            learner_goal_id=learner_goal_id,
            surface=surface,
            recommendation=recommendation,
            observed_sample_count=observed_sample_count,
            positive_score=positive_score,
            negative_score=negative_score,
            signal_summary=dict(signal_summary),
            reason_codes=list(reason_codes),
            created_at=_utcnow(),
        )


@dataclass(frozen=True)
class ReflectionProposalRolloutDecision:
    id: str
    rollout_id: str
    proposal_id: str
    decision_type: str
    previous_status: str
    new_status: str
    reason_code: str
    reason_note: str | None
    operator_id: str
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        rollout_id: str,
        proposal_id: str,
        decision_type: str,
        previous_status: str,
        new_status: str,
        reason_code: str,
        reason_note: str | None,
        operator_id: str,
    ) -> "ReflectionProposalRolloutDecision":
        if decision_type not in PROPOSAL_ROLLOUT_DECISION_TYPES:
            raise ValidationError("Unsupported reflection proposal rollout decision type.")
        return cls(
            id=str(uuid4()),
            rollout_id=rollout_id,
            proposal_id=proposal_id,
            decision_type=decision_type,
            previous_status=previous_status,
            new_status=new_status,
            reason_code=reason_code,
            reason_note=reason_note,
            operator_id=operator_id,
            created_at=_utcnow(),
        )
