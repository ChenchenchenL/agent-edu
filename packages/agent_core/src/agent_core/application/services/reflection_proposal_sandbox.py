from __future__ import annotations

from dataclasses import replace

from agent_core.application.services.audit import AuditService
from agent_core.application.services.chat import ChatService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.tool_plan_sequence_governance import (
    build_tool_plan_sequence_contract,
    summarize_tool_plan_preview,
)
from agent_core.application.services.tool_plan_runtime import (
    ToolPlanExecutionContext,
    ToolPlanRuntimeExecutor,
)
from agent_core.application.services.plan_template_validation import PlanTemplateValidator
from agent_core.application.services.plan_template_selector import PlanTemplateSelector
from agent_core.application.tools.registry import InternalToolRegistry
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalSandboxRun,
    proposal_policy_keys,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    ReflectionProposalSandboxRunRepository,
    SessionMessageRepository,
    SessionRepository,
    TaskAttemptRepository,
    WorkflowRunRepository,
)
from agent_core.infrastructure.observability.metrics import observe_high_risk_auto_sandbox


class ReflectionProposalSandboxService:
    def __init__(
        self,
        *,
        sandbox_run_repository: ReflectionProposalSandboxRunRepository,
        proposal_service: ReflectionProposalService,
        replay_service: ReflectionReplayService,
        audit_service: AuditService,
        strategy_card_service: StrategyCardService | None = None,
        session_repository: SessionRepository | None = None,
        message_repository: SessionMessageRepository | None = None,
        daily_task_repository: DailyTaskRepository | None = None,
        task_attempt_repository: TaskAttemptRepository | None = None,
        workflow_run_repository: WorkflowRunRepository | None = None,
        chat_service: ChatService | None = None,
        internal_tool_registry: InternalToolRegistry | None = None,
        tool_plan_runtime_executor: ToolPlanRuntimeExecutor | None = None,
    ) -> None:
        self._sandbox_run_repository = sandbox_run_repository
        self._proposal_service = proposal_service
        self._replay_service = replay_service
        self._audit_service = audit_service
        self._strategy_card_service = strategy_card_service
        self._session_repository = session_repository
        self._message_repository = message_repository
        self._daily_task_repository = daily_task_repository
        self._task_attempt_repository = task_attempt_repository
        self._workflow_run_repository = workflow_run_repository
        self._chat_service = chat_service
        self._internal_tool_registry = internal_tool_registry
        self._tool_plan_runtime_executor = tool_plan_runtime_executor

    async def list_runs(self, proposal_id: str) -> list[ReflectionProposalSandboxRun]:
        return await self._sandbox_run_repository.list_by_proposal(proposal_id)

    async def get_run(self, sandbox_run_id: str) -> ReflectionProposalSandboxRun:
        sandbox_run = await self._sandbox_run_repository.get_by_id(sandbox_run_id)
        if sandbox_run is None:
            raise NotFoundError(f"Reflection proposal sandbox run '{sandbox_run_id}' was not found.")
        return sandbox_run

    async def execute(self, *, proposal_id: str) -> ReflectionProposalSandboxRun:
        proposal = await self._proposal_service.get(proposal_id)
        if proposal.risk_level == "high":
            # 1. evidence snapshot validation
            evidence = proposal.evidence_snapshot or {}
            has_sufficient_evidence = False
            if len(evidence) >= 2:
                metric_keys = {"fallback_burst_count", "router_mismatch_count", "sequence_mismatch_count", "mismatch_count", "contested_count", "severity_score"}
                if any(k in evidence for k in metric_keys) or "usage_event_ids" in evidence or "details" in evidence:
                    has_sufficient_evidence = True
            if not has_sufficient_evidence:
                raise ValidationError("High-risk proposals require higher-quality evidence snapshot containing specific metrics or event details.")
            
            # 2. summary detail validation
            summary = proposal.change_summary or ""
            if len(summary) < 30:
                raise ValidationError("High-risk proposals require a detailed change summary (at least 30 characters).")

        baseline_snapshot = await self._build_baseline_snapshot(proposal)
        candidate_snapshot = self._build_candidate_snapshot(proposal, baseline_snapshot=baseline_snapshot)
        sample_source_type, sample_count = await self._sample_metadata(proposal)
        sandbox_run = ReflectionProposalSandboxRun.build(
            proposal_id=proposal.id,
            learner_goal_id=proposal.learner_goal_id,
            sample_source_type=sample_source_type,
            sample_count=sample_count,
            provider=self._provider_name(),
            model=self._model_name(),
            evaluator_type="archived_replay_live_llm",
            baseline_snapshot=baseline_snapshot,
            candidate_snapshot=candidate_snapshot,
        )
        await self._sandbox_run_repository.create(sandbox_run)
        if proposal.status != "sandbox_queued":
            await self._proposal_service.mark_sandbox_queued(
                proposal_id=proposal.id,
                sandbox_run_id=sandbox_run.id,
            )
        await self._proposal_service.mark_sandbox_started(proposal_id=proposal.id, sandbox_run_id=sandbox_run.id)
        started = sandbox_run.with_status("running")
        await self._sandbox_run_repository.update(started)
        await self._audit_service.record(
            event_type="reflection.proposal.sandbox.started",
            resource_type="reflection_proposal_sandbox_run",
            resource_id=started.id,
            actor="system",
            event_data={"proposal_id": proposal.id, "sandbox_run_id": started.id},
        )
        # Phase 6: emit counter for high-risk proposals entering auto-sandbox
        if proposal.risk_level == "high":
            observe_high_risk_auto_sandbox(proposal_type=proposal.proposal_type)
        try:
            tool_previews: list[dict[str, object]] = []
            tool_plan_contract_summary: dict[str, object] | None = None
            tool_plan_preview_summary: dict[str, object] | None = None
            template_validation_summary: dict[str, object] | None = None
            if proposal.proposal_type == "skill_package" and proposal.target_scope in {"review_scheduling", "assessment_generation", "replan"}:
                raw_tool_plan = [dict(item) for item in proposal.structured_patch_payload.get("tool_plan") or []]
                validator = PlanTemplateValidator()
                selector = PlanTemplateSelector()
                template_candidates = selector.build_candidates_from_legacy_tool_plan(
                    surface=proposal.target_scope,
                    tool_plan=raw_tool_plan,
                )
                template_rejections: list[list[str]] = []
                template_validated = False
                for candidate in template_candidates:
                    result = validator.validate_template(template=candidate, surface=proposal.target_scope)
                    if result.valid:
                        template_validated = True
                    else:
                        template_rejections.append(result.rejection_reason_codes)
                template_validation_summary = {
                    "validated": template_validated,
                    "candidate_count": len(template_candidates),
                    "rejections": template_rejections,
                }
                contract = build_tool_plan_sequence_contract(
                    surface=proposal.target_scope,
                    tool_plan=raw_tool_plan,
                )
                if contract is not None:
                    tool_plan_contract_summary = {
                        "surface": contract.surface,
                        "expected_sequence": list(contract.expected_sequence),
                        "expected_step_count": contract.expected_step_count,
                        "is_multi_step": contract.is_multi_step,
                        "requires_repair_task_id": contract.requires_repair_task_id,
                        "requires_created_review_task_ids": contract.requires_created_review_task_ids,
                    }
                tool_previews = await self.run_tool_plan_preview(proposal)
                if contract is not None:
                    tool_plan_preview_summary = summarize_tool_plan_preview(
                        contract=contract,
                        tool_previews=tool_previews,
                    )
            evaluation = await self._replay_service.evaluate(
                proposal=proposal,
                baseline_policy_snapshot=baseline_snapshot,
                candidate_policy_snapshot=candidate_snapshot,
                evaluator_type="archived_replay_live_llm",
                sandbox_run_id=started.id,
                sandbox_context={
                    "tool_plan_contract_summary": dict(tool_plan_contract_summary or {}),
                    "tool_plan_preview_summary": dict(tool_plan_preview_summary or {}),
                    "template_validation_summary": dict(template_validation_summary or {}),
                },
            )
            summary = {
                "proposal_type": proposal.proposal_type,
                "target_scope": proposal.target_scope,
                "sample_count": sample_count,
                "sample_source_type": sample_source_type,
                "evaluation_status": evaluation.evaluation_status,
                "score_delta": evaluation.score_delta,
                "insufficient_samples": sample_count < 2,
                "tool_previews": tool_previews,
                "tool_plan_sequence": [item["tool_name"] for item in tool_previews],
                "tool_plan_step_count": len(tool_previews),
                "tool_plan_contract_summary": dict(tool_plan_contract_summary or {}),
                "tool_plan_preview_summary": dict(tool_plan_preview_summary or {}),
                "template_validation_summary": dict(template_validation_summary or {}),
            }
            if sample_count < 2 and evaluation.evaluation_status == "effective":
                evaluation = replace(evaluation, evaluation_status="inconclusive")
                summary["evaluation_status"] = "inconclusive"
            completed = started.with_status(
                "completed",
                result_summary=summary,
                score_delta=evaluation.score_delta,
            )
            await self._sandbox_run_repository.update(completed)
            await self._proposal_service.mark_sandbox_completed(
                proposal_id=proposal.id,
                sandbox_run_id=completed.id,
                evaluation_status=summary["evaluation_status"],
                evaluation_summary=f"sandbox:{evaluation.score_delta:.2f}",
            )
            await self._audit_service.record(
                event_type="reflection.proposal.sandbox.completed",
                resource_type="reflection_proposal_sandbox_run",
                resource_id=completed.id,
                actor="system",
                event_data={
                    "proposal_id": proposal.id,
                    "sandbox_run_id": completed.id,
                    "evaluation_status": summary["evaluation_status"],
                    "score_delta": evaluation.score_delta,
                },
            )
            return completed
        except Exception as exc:
            failed = started.with_status("failed", error_code=type(exc).__name__)
            await self._sandbox_run_repository.update(failed)
            await self._proposal_service.mark_sandbox_failed(
                proposal_id=proposal.id,
                sandbox_run_id=failed.id,
                reason_code=type(exc).__name__,
                reason_note=str(exc),
            )
            await self._audit_service.record_durable(
                event_type="reflection.proposal.sandbox.failed",
                resource_type="reflection_proposal_sandbox_run",
                resource_id=failed.id,
                actor="system",
                event_data={
                    "proposal_id": proposal.id,
                    "sandbox_run_id": failed.id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise

    async def _build_baseline_snapshot(self, proposal: ReflectionProposal) -> dict[str, object]:
        strategy_summary = None
        if self._strategy_card_service is not None:
            strategy_card = await self._strategy_card_service.get_active(proposal.learner_goal_id)
            strategy_summary = StrategyCardService.build_strategy_summary(strategy_card)
        if proposal.proposal_type == "prompt_optimization":
            return {
                "response_preference_bias": (strategy_summary or {}).get("primary_instruction_mode", "mixed"),
                "hint_level_preference": "conceptual",
                "teaching_goal_override": "advance understanding",
                "strategy_summary": strategy_summary,
                "target_scope": proposal.target_scope,
            }
        if proposal.proposal_type == "workflow_optimization":
            return {
                "review_interval_policy": "normal" if (strategy_summary or {}).get("review_bias") != "intensive" else "denser",
                "assessment_threshold_policy": "standard" if (strategy_summary or {}).get("assessment_bias") != "early" else "earlier",
                "replan_mode_policy": "normal" if (strategy_summary or {}).get("replan_bias") != "aggressive" else "more_aggressive",
                "strategy_summary": strategy_summary,
                "target_scope": proposal.target_scope,
            }
        if proposal.proposal_type == "skill_package":
            return {
                "surface": proposal.target_scope,
                "match_rules": {},
                "runtime_directives": {},
                "tool_plan": [],
                "strategy_summary": strategy_summary,
            }
        if proposal.proposal_type == "skill_patch_request":
            return {
                "surface": proposal.target_scope,
                "artifact_id": proposal.structured_patch_payload.get("artifact_id"),
                "skill_name": proposal.structured_patch_payload.get("skill_name"),
                "skill_version": proposal.structured_patch_payload.get("skill_version"),
                "strategy_summary": strategy_summary,
            }
        if proposal.proposal_type == "routing_policy":
            return {
                "routing_rules": {},
                "fallback_chain": ["static_fallback"],
                "trust_policy": "standard",
                "ranking_policy": "confidence_first",
                "strategy_summary": strategy_summary,
                "target_scope": proposal.target_scope,
            }
        if proposal.proposal_type == "template_policy":
            return {
                "template_id": "default_tutor",
                "sequence_contract": "1.0",
                "template_rules": {},
                "strategy_summary": strategy_summary,
                "target_scope": proposal.target_scope,
            }
        raise ValidationError("Unsupported reflection proposal type.")

    def _build_candidate_snapshot(
        self,
        proposal: ReflectionProposal,
        *,
        baseline_snapshot: dict[str, object],
    ) -> dict[str, object]:
        allowed_keys = proposal_policy_keys(proposal.proposal_type)
        patch_keys = set(proposal.structured_patch_payload.keys())
        if not patch_keys.issubset(allowed_keys):
            raise ValidationError("Unsupported proposal patch keys.")
        candidate = dict(baseline_snapshot)
        candidate.update(proposal.structured_patch_payload)
        return candidate

    async def _sample_metadata(self, proposal: ReflectionProposal) -> tuple[str, int]:
        if proposal.proposal_type == "prompt_optimization":
            if self._session_repository is None or self._message_repository is None:
                return "session_messages", 0
            sessions = await self._session_repository.list_by_goal(proposal.learner_goal_id, limit=5)
            sample_count = 0
            for session in sessions[:5]:
                history = await self._message_repository.list_history(session_id=session.id, limit=6, before_id=None)
                sample_count += sum(1 for item in history if isinstance(item, SessionMessage) and item.role == "user")
            return "session_messages", min(sample_count, 5)
        if proposal.proposal_type == "workflow_optimization":
            if self._task_attempt_repository is None or self._workflow_run_repository is None:
                return "mixed", 0
            attempts = await self._task_attempt_repository.list_recent_by_goal(proposal.learner_goal_id, limit=5)
            workflow_runs = await self._workflow_run_repository.list_by_goal(proposal.learner_goal_id)
            workflow_sample_count = len([item for item in workflow_runs if item.workflow_type in {"review_scheduling", "assessment_generation", "plan_extension", "plan_generation"}][:5])
            return "mixed", min(len(attempts) + workflow_sample_count, 5)
        if proposal.proposal_type == "skill_package":
            if proposal.target_scope in {"chat", "hint", "quiz", "plan_generation"}:
                if self._session_repository is None or self._message_repository is None:
                    return "mixed", 0
                sessions = await self._session_repository.list_by_goal(proposal.learner_goal_id, limit=5)
                sample_count = 0
                for session in sessions[:5]:
                    history = await self._message_repository.list_history(session_id=session.id, limit=6, before_id=None)
                    sample_count += sum(1 for item in history if isinstance(item, SessionMessage) and item.role == "user")
                return "mixed", min(sample_count, 5)
            if self._task_attempt_repository is None:
                return "mixed", 0
            attempts = await self._task_attempt_repository.list_recent_by_goal(proposal.learner_goal_id, limit=5)
            return "mixed", min(len(attempts), 5)
        if proposal.proposal_type == "skill_patch_request":
            usage_event_ids = proposal.structured_patch_payload.get("usage_event_ids") or []
            return "mixed", min(len(usage_event_ids), 5)
        return "mixed", 0

    async def run_tool_plan_preview(self, proposal: ReflectionProposal) -> list[dict[str, object]]:
        if self._tool_plan_runtime_executor is None:
            return []
        report = await self._tool_plan_runtime_executor.execute(
            surface=proposal.target_scope,
            tool_plan=[dict(item) for item in proposal.structured_patch_payload.get("tool_plan") or []],
            context=ToolPlanExecutionContext(
                surface=proposal.target_scope,
                learner_goal_id=proposal.learner_goal_id,
                resource_id=proposal.id,
                actor="system",
                source_task_id=self._preview_source_task_id(proposal),
                topic_focus=self._preview_topic_focus(proposal),
            ),
            dry_run=True,
        )
        return [
            {
                "step_id": step.step_id,
                "tool_name": step.tool_name,
                "preview": step.result_payload or {},
            }
            for step in report.steps
        ]

    @staticmethod
    def _preview_source_task_id(proposal: ReflectionProposal) -> str | None:
        task_payload = dict((proposal.evidence_snapshot or {}).get("task") or {})
        for key in ("source_task_id", "daily_task_id", "task_id"):
            value = task_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    @staticmethod
    def _preview_topic_focus(proposal: ReflectionProposal) -> str | None:
        task_payload = dict((proposal.evidence_snapshot or {}).get("task") or {})
        value = task_payload.get("topic_focus") or proposal.structured_patch_payload.get("topic_focus")
        if isinstance(value, str) and value.strip():
            return value
        return None

    def _provider_name(self) -> str | None:
        provider = getattr(getattr(self._chat_service, "_llm_provider", None), "provider_name", None)
        return str(provider) if provider is not None else None

    def _model_name(self) -> str | None:
        model = getattr(getattr(self._chat_service, "_llm_provider", None), "model_name", None)
        return str(model) if model is not None else None
