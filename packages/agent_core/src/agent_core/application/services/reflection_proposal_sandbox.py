from __future__ import annotations

from dataclasses import replace

from agent_core.application.services.audit import AuditService
from agent_core.application.services.chat import ChatService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.tools.registry import InternalToolRegistry, ToolExecutionRequest
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

    async def list_runs(self, proposal_id: str) -> list[ReflectionProposalSandboxRun]:
        return await self._sandbox_run_repository.list_by_proposal(proposal_id)

    async def get_run(self, sandbox_run_id: str) -> ReflectionProposalSandboxRun:
        sandbox_run = await self._sandbox_run_repository.get_by_id(sandbox_run_id)
        if sandbox_run is None:
            raise NotFoundError(f"Reflection proposal sandbox run '{sandbox_run_id}' was not found.")
        return sandbox_run

    async def execute(self, *, proposal_id: str) -> ReflectionProposalSandboxRun:
        proposal = await self._proposal_service.get(proposal_id)
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
        try:
            tool_previews: list[dict[str, object]] = []
            if proposal.proposal_type == "skill_package" and proposal.target_scope in {"review_scheduling", "assessment_generation", "replan"}:
                tool_previews = await self.run_tool_plan_preview(proposal)
            evaluation = await self._replay_service.evaluate(
                proposal=proposal,
                baseline_policy_snapshot=baseline_snapshot,
                candidate_policy_snapshot=candidate_snapshot,
                evaluator_type="archived_replay_live_llm",
                sandbox_run_id=started.id,
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
        return "mixed", 0

    async def run_tool_plan_preview(self, proposal: ReflectionProposal) -> list[dict[str, object]]:
        if self._internal_tool_registry is None:
            return []
        previews: list[dict[str, object]] = []
        for item in proposal.structured_patch_payload.get("tool_plan") or []:
            tool_name = str(item.get("tool_name") or "")
            payload_template = dict(item.get("payload_template") or {})
            payload = {
                key: proposal.learner_goal_id if str(value) == "$learner_goal_id" else value
                for key, value in payload_template.items()
            }
            preview = await self._internal_tool_registry.execute(
                ToolExecutionRequest(
                    name=tool_name,
                    payload=payload,
                    actor="system",
                    resource_id=proposal.id,
                    dry_run=True,
                )
            )
            previews.append({"tool_name": tool_name, "preview": preview or {}})
        return previews

    def _provider_name(self) -> str | None:
        provider = getattr(getattr(self._chat_service, "_llm_provider", None), "provider_name", None)
        return str(provider) if provider is not None else None

    def _model_name(self) -> str | None:
        model = getattr(getattr(self._chat_service, "_llm_provider", None), "model_name", None)
        return str(model) if model is not None else None
