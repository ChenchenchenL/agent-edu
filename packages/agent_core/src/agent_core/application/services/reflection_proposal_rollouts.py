from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.domain.entities.autonomy import GoalAutonomyState
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalRollout,
    ReflectionProposalRolloutDecision,
    ReflectionProposalRolloutObservation,
    proposal_rollout_surface,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    GoalSkillBindingRepository,
    GoalAutonomyStateRepository,
    LearnerGoalRepository,
    ReflectionEvidenceSignalRepository,
    ReflectionProposalRepository,
    ReflectionProposalRolloutDecisionRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    ReflectionRecordRepository,
    SessionMessageRepository,
    SessionRepository,
    StudyPlanRepository,
    TaskAttemptRepository,
    WorkflowRunRepository,
    PlanStageRepository,
)


class ReflectionProposalRolloutService:
    def __init__(
        self,
        *,
        proposal_repository: ReflectionProposalRepository,
        rollout_repository: ReflectionProposalRolloutRepository,
        rollout_observation_repository: ReflectionProposalRolloutObservationRepository,
        rollout_decision_repository: ReflectionProposalRolloutDecisionRepository,
        goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        plan_stage_repository: PlanStageRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None,
        goal_skill_binding_repository: GoalSkillBindingRepository,
        session_repository: SessionRepository,
        message_repository: SessionMessageRepository,
        reflection_record_repository: ReflectionRecordRepository,
        reflection_evidence_repository: ReflectionEvidenceSignalRepository,
        task_attempt_repository: TaskAttemptRepository,
        planner_service: PlannerService,
        workflow_run_service: WorkflowRunService,
        observation_scheduler: ReflectionProposalRolloutObservationScheduler | None,
        audit_service: AuditService,
    ) -> None:
        self._proposal_repository = proposal_repository
        self._rollout_repository = rollout_repository
        self._rollout_observation_repository = rollout_observation_repository
        self._rollout_decision_repository = rollout_decision_repository
        self._goal_repository = goal_repository
        self._study_plan_repository = study_plan_repository
        self._plan_stage_repository = plan_stage_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._goal_skill_binding_repository = goal_skill_binding_repository
        self._session_repository = session_repository
        self._message_repository = message_repository
        self._reflection_record_repository = reflection_record_repository
        self._reflection_evidence_repository = reflection_evidence_repository
        self._task_attempt_repository = task_attempt_repository
        self._planner_service = planner_service
        self._workflow_run_service = workflow_run_service
        self._observation_scheduler = observation_scheduler
        self._audit_service = audit_service

    async def activate(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposalRollout:
        proposal = await self._require_proposal(proposal_id)
        surface = self._eligible_surface(proposal)
        existing_active = await self._rollout_repository.get_active_by_goal_and_surface(
            proposal.learner_goal_id,
            surface,
        )
        if existing_active is not None:
            raise ValidationError("An active rollout already exists for this goal and surface.")
        existing_binding = await self._goal_skill_binding_repository.get_active_by_goal_and_surface(
            proposal.learner_goal_id,
            surface,
        )
        if existing_binding is not None:
            raise ValidationError("An active skill binding already exists for this goal and surface.")
        existing = await self._rollout_repository.get_by_proposal(proposal.id)
        if existing is not None and existing.status != "rolled_back":
            raise ValidationError("A rollout already exists for this proposal.")

        baseline_snapshot = self._baseline_snapshot(proposal)
        runtime_overlay_payload = self._runtime_overlay_payload(proposal)
        rollout = ReflectionProposalRollout.build(
            proposal_id=proposal.id,
            learner_goal_id=proposal.learner_goal_id,
            surface=surface,
            baseline_snapshot=baseline_snapshot,
            runtime_overlay_payload=runtime_overlay_payload,
            activated_by=operator_id,
        )
        await self._rollout_repository.create(rollout)
        if proposal.proposal_type == "skill_package":
            await self._goal_skill_binding_repository.create(
                GoalSkillBinding.build(
                    proposal_id=proposal.id,
                    rollout_id=rollout.id,
                    learner_goal_id=proposal.learner_goal_id,
                    surface=surface,
                    priority_score=proposal.priority_score,
                    match_rules=dict(proposal.structured_patch_payload.get("match_rules") or {}),
                    runtime_directives=dict(proposal.structured_patch_payload.get("runtime_directives") or {}),
                    tool_plan=[dict(item) for item in (proposal.structured_patch_payload.get("tool_plan") or [])],
                )
            )
        await self._rollout_decision_repository.create(
            ReflectionProposalRolloutDecision.build(
                rollout_id=rollout.id,
                proposal_id=proposal.id,
                decision_type="activate",
                previous_status="approved",
                new_status="staged",
                reason_code=reason_code,
                reason_note=reason_note,
                operator_id=operator_id,
            )
        )
        if surface == "plan_generation":
            rollout = await self._materialize_rollout_plan(
                rollout=rollout,
                trigger_source="proposal_rollout_activation",
                use_overlay=True,
                reason_code=reason_code,
            )
        if self._observation_scheduler is not None:
            await self._observation_scheduler.schedule_rollout(
                rollout_id=rollout.id,
                trigger_source="proposal_rollout_activated",
                source_ref=reason_code,
            )
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.activated",
            resource_type="reflection_proposal_rollout",
            resource_id=rollout.id,
            actor=operator_id,
            event_data={
                "proposal_id": proposal.id,
                "rollout_id": rollout.id,
                "surface": rollout.surface,
                "operator_id": operator_id,
                "reason_code": reason_code,
            },
        )
        return rollout

    async def promote(
        self,
        *,
        rollout_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposalRollout:
        rollout = await self.get_rollout(rollout_id)
        updated = rollout.with_status("rolled_out")
        await self._rollout_repository.update(updated)
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is not None:
            await self._goal_skill_binding_repository.update(binding.with_status("rolled_out"))
        await self._rollout_decision_repository.create(
            ReflectionProposalRolloutDecision.build(
                rollout_id=rollout.id,
                proposal_id=rollout.proposal_id,
                decision_type="promote",
                previous_status=rollout.status,
                new_status=updated.status,
                reason_code=reason_code,
                reason_note=reason_note,
                operator_id=operator_id,
            )
        )
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.promoted",
            resource_type="reflection_proposal_rollout",
            resource_id=updated.id,
            actor=operator_id,
            event_data={
                "proposal_id": updated.proposal_id,
                "rollout_id": updated.id,
                "operator_id": operator_id,
                "reason_code": reason_code,
            },
        )
        return updated

    async def rollback(
        self,
        *,
        rollout_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposalRollout:
        rollout = await self.get_rollout(rollout_id)
        updated = rollout.with_status("rolled_back")
        await self._rollout_repository.update(updated)
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is not None:
            await self._goal_skill_binding_repository.update(binding.with_status("rolled_back"))
        if rollout.surface == "plan_generation" and rollout.staged_plan_id is not None:
            updated = await self._materialize_rollout_plan(
                rollout=updated,
                trigger_source="proposal_rollout_rollback",
                use_overlay=False,
                reason_code=reason_code,
            )
        await self._rollout_decision_repository.create(
            ReflectionProposalRolloutDecision.build(
                rollout_id=rollout.id,
                proposal_id=rollout.proposal_id,
                decision_type="rollback",
                previous_status=rollout.status,
                new_status=updated.status,
                reason_code=reason_code,
                reason_note=reason_note,
                operator_id=operator_id,
            )
        )
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.rolled_back",
            resource_type="reflection_proposal_rollout",
            resource_id=updated.id,
            actor=operator_id,
            event_data={
                "proposal_id": updated.proposal_id,
                "rollout_id": updated.id,
                "operator_id": operator_id,
                "reason_code": reason_code,
            },
        )
        return updated

    async def observe(
        self,
        *,
        rollout_id: str,
        trigger_source: str,
    ) -> ReflectionProposalRolloutObservation:
        rollout = await self.get_rollout(rollout_id)
        if rollout.surface in {"chat", "hint"}:
            observation = await self._observe_chat_like(rollout)
        elif rollout.surface == "plan_generation":
            observation = await self._observe_plan_generation(rollout)
        else:
            observation = await self._observe_workflow_surface(rollout)
        await self._rollout_observation_repository.create(observation)
        updated = rollout.with_status(
            rollout.status,
            latest_observation_id=observation.id,
        )
        await self._rollout_repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.observed",
            resource_type="reflection_proposal_rollout_observation",
            resource_id=observation.id,
            actor="system",
            event_data={
                "proposal_id": observation.proposal_id,
                "rollout_id": observation.rollout_id,
                "surface": observation.surface,
                "recommendation": observation.recommendation,
                "trigger_source": trigger_source,
            },
        )
        if observation.recommendation == "rollback":
            await self._audit_service.record(
                event_type="reflection.proposal.rollout.rollback.recommended",
                resource_type="reflection_proposal_rollout",
                resource_id=rollout.id,
                actor="system",
                event_data={
                    "proposal_id": rollout.proposal_id,
                    "rollout_id": rollout.id,
                    "surface": rollout.surface,
                    "latest_observation_id": observation.id,
                },
            )
        return observation

    async def get_rollout(self, rollout_id: str) -> ReflectionProposalRollout:
        rollout = await self._rollout_repository.get_by_id(rollout_id)
        if rollout is None:
            raise NotFoundError(f"Reflection proposal rollout '{rollout_id}' was not found.")
        return rollout

    async def list_rollouts(self, proposal_id: str) -> list[ReflectionProposalRollout]:
        return await self._rollout_repository.list_by_proposal(proposal_id)

    async def list_observations(self, rollout_id: str) -> list[ReflectionProposalRolloutObservation]:
        return await self._rollout_observation_repository.list_by_rollout(rollout_id)

    async def list_decisions(self, rollout_id: str) -> list[ReflectionProposalRolloutDecision]:
        return await self._rollout_decision_repository.list_by_rollout(rollout_id)

    async def record_generated_plan(
        self,
        *,
        rollout_id: str,
        plan_id: str,
    ) -> None:
        rollout = await self.get_rollout(rollout_id)
        updated = rollout.with_status(
            rollout.status,
            staged_plan_id=plan_id,
        )
        await self._rollout_repository.update(updated)

    async def _materialize_rollout_plan(
        self,
        *,
        rollout: ReflectionProposalRollout,
        trigger_source: str,
        use_overlay: bool,
        reason_code: str,
    ) -> ReflectionProposalRollout:
        goal = await self._require_goal(rollout.learner_goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        version = 1 if active_plan is None else active_plan.version + 1
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_generation",
            trigger_source=trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id if active_plan is not None else None,
            daily_task_id=None,
        )
        try:
            materialized = await self._planner_service.build_plan(
                goal=goal,
                version=version,
                trigger_source=trigger_source,
                supersedes_plan_id=active_plan.id if active_plan is not None else None,
                rollout_overlay=rollout.runtime_overlay_payload if use_overlay else None,
                rollout_context={
                    "rollout_id": rollout.id,
                    "surface": rollout.surface,
                    "status": rollout.status,
                    "reason_code": reason_code,
                } if use_overlay else None,
            )
            if active_plan is not None:
                await self._study_plan_repository.update(active_plan.with_status("superseded"))
                await self._daily_task_repository.bulk_mark_superseded(active_plan.id)
            await self._study_plan_repository.create(materialized.study_plan)
            await self._plan_stage_repository.create_many(materialized.stages)
            await self._daily_task_repository.create_many(materialized.tasks)
            await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="study_plan",
                result_resource_ids=[materialized.study_plan.id],
            )
            if self._goal_autonomy_state_repository is not None:
                state = await self._goal_autonomy_state_repository.get_by_goal(goal.id)
                if state is None:
                    state = GoalAutonomyState.build(learner_goal_id=goal.id)
                    await self._goal_autonomy_state_repository.create(state)
                await self._goal_autonomy_state_repository.update(
                    state.with_transition(
                        phase="active",
                        current_plan_id=materialized.study_plan.id,
                        reason=trigger_source,
                    )
                )
            key = "staged_plan_id" if use_overlay else "rollback_restored_plan_id"
            rollout = rollout.with_status(
                rollout.status,
                staged_plan_id=materialized.study_plan.id if key == "staged_plan_id" else rollout.staged_plan_id,
                rollback_restored_plan_id=(
                    materialized.study_plan.id if key == "rollback_restored_plan_id" else rollout.rollback_restored_plan_id
                ),
            )
            await self._rollout_repository.update(rollout)
            return rollout
        except Exception:
            await self._workflow_run_service.fail_run(run=run, error_code="rollout_plan_failed")
            raise

    async def _observe_chat_like(self, rollout: ReflectionProposalRollout) -> ReflectionProposalRolloutObservation:
        sessions = await self._session_repository.list_by_goal(rollout.learner_goal_id, limit=5)
        assistant_messages = []
        for session in sessions:
            history = await self._message_repository.list_history(session_id=session.id, limit=12, before_id=None)
            assistant_messages.extend(
                [
                    item
                    for item in history
                    if item.role == "assistant"
                    and item.mode == rollout.surface
                    and item.created_at >= rollout.activated_at
                ]
            )
        signals = await self._reflection_evidence_repository.list_by_goal(rollout.learner_goal_id, limit=50)
        signals = [item for item in signals if item.observed_at >= rollout.activated_at]
        direct_answer_given_count = sum(
            1 for item in assistant_messages if bool((item.content_payload or {}).get("direct_answer_given"))
        )
        repeat_confusion_count = sum(1 for item in signals if item.signal_code == "repeat_confusion")
        high_hint_dependency_count = sum(1 for item in signals if item.signal_code == "high_hint_dependency")
        scaffolded_count = sum(1 for item in assistant_messages if (item.content_payload or {}).get("hint_level") == "scaffolded")
        targeted_count = sum(1 for item in assistant_messages if (item.content_payload or {}).get("hint_level") == "targeted")
        observed_turn_count = len(assistant_messages)
        recommendation = "collecting"
        reason_codes: list[str] = []
        if direct_answer_given_count > 0 or repeat_confusion_count >= 2 or high_hint_dependency_count >= 2:
            recommendation = "rollback"
            if direct_answer_given_count > 0:
                reason_codes.append("direct_answer_given")
            if repeat_confusion_count >= 2:
                reason_codes.append("repeat_confusion")
            if high_hint_dependency_count >= 2:
                reason_codes.append("high_hint_dependency")
        elif observed_turn_count >= 3:
            recommendation = "promote"
            reason_codes.append("sufficient_turns")
        return ReflectionProposalRolloutObservation.build(
            rollout_id=rollout.id,
            proposal_id=rollout.proposal_id,
            learner_goal_id=rollout.learner_goal_id,
            surface=rollout.surface,
            recommendation=recommendation,
            observed_sample_count=observed_turn_count,
            positive_score=min(1.0, (scaffolded_count + targeted_count + observed_turn_count) / 6),
            negative_score=min(1.0, (direct_answer_given_count + repeat_confusion_count + high_hint_dependency_count) / 4),
            signal_summary={
                "observed_turn_count": observed_turn_count,
                "direct_answer_given_count": direct_answer_given_count,
                "repeat_confusion_signal_count": repeat_confusion_count,
                "high_hint_dependency_signal_count": high_hint_dependency_count,
                "scaffolded_hint_count": scaffolded_count,
                "targeted_hint_count": targeted_count,
            },
            reason_codes=reason_codes or ["collecting"],
        )

    async def _observe_plan_generation(self, rollout: ReflectionProposalRollout) -> ReflectionProposalRolloutObservation:
        tasks = await self._daily_task_repository.list_by_goal(rollout.learner_goal_id)
        workflow_runs = await self._workflow_run_repository.list_recent_by_goal(rollout.learner_goal_id, limit=20)
        reflections = await self._reflection_record_repository.list_by_goal(rollout.learner_goal_id, limit=20)
        task_window = [
            item for item in tasks
            if rollout.staged_plan_id is not None and item.study_plan_id == rollout.staged_plan_id
        ]
        workflow_window = [
            item for item in workflow_runs
            if rollout.staged_plan_id is not None and item.study_plan_id == rollout.staged_plan_id
        ]
        reflection_window = [
            item for item in reflections
            if item.study_plan_id == rollout.staged_plan_id
        ]
        completed_count = len([item for item in task_window if item.status == "completed"])
        failed_count = len([item for item in task_window if item.status == "failed"])
        skipped_count = len([item for item in task_window if item.status == "skipped"])
        workflow_failed_count = len([item for item in workflow_window if item.status == "failed"])
        recommendation = "collecting"
        reason_codes: list[str] = []
        if workflow_failed_count > 0 or failed_count + skipped_count >= 2:
            recommendation = "rollback"
            if workflow_failed_count > 0:
                reason_codes.append("workflow_failed")
            if failed_count + skipped_count >= 2:
                reason_codes.append("task_failure_cluster")
        elif completed_count >= 1:
            recommendation = "promote"
            reason_codes.append("task_completed")
        return ReflectionProposalRolloutObservation.build(
            rollout_id=rollout.id,
            proposal_id=rollout.proposal_id,
            learner_goal_id=rollout.learner_goal_id,
            surface=rollout.surface,
            recommendation=recommendation,
            observed_sample_count=len(task_window) + len(workflow_window),
            positive_score=min(1.0, completed_count / 3 if completed_count else 0.0),
            negative_score=min(1.0, (failed_count + skipped_count + workflow_failed_count) / 3),
            signal_summary={
                "task_completed_count": completed_count,
                "task_failed_count": failed_count,
                "task_skipped_count": skipped_count,
                "workflow_failed_count": workflow_failed_count,
                "reflection_count": len(reflection_window),
            },
            reason_codes=reason_codes or ["collecting"],
        )

    async def _require_proposal(self, proposal_id: str) -> ReflectionProposal:
        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
        return proposal

    async def _require_goal(self, goal_id: str) -> LearnerGoal:
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    @staticmethod
    def _eligible_surface(proposal: ReflectionProposal) -> str:
        if proposal.status != "approved":
            raise ValidationError("Only approved proposals can be activated.")
        surface = proposal_rollout_surface(proposal.target_scope)
        if surface is None:
            raise ValidationError("This proposal target scope is not rollout-enabled.")
        return surface

    @staticmethod
    def _baseline_snapshot(proposal: ReflectionProposal) -> dict[str, Any]:
        return dict(proposal.structured_patch_payload)

    @staticmethod
    def _runtime_overlay_payload(proposal: ReflectionProposal) -> dict[str, Any]:
        if proposal.proposal_type == "prompt_optimization":
            return {
                "response_preference": proposal.structured_patch_payload.get("response_preference_bias"),
                "teaching_goal": proposal.structured_patch_payload.get("teaching_goal_override"),
                "hint_level_preference": proposal.structured_patch_payload.get("hint_level_preference"),
            }
        if proposal.proposal_type == "workflow_optimization":
            return {
                "review_bias": "intensive"
                if proposal.structured_patch_payload.get("review_interval_policy") == "denser"
                else "normal",
                "assessment_bias": "early"
                if proposal.structured_patch_payload.get("assessment_threshold_policy") == "earlier"
                else "standard",
                "replan_bias": "aggressive"
                if proposal.structured_patch_payload.get("replan_mode_policy") == "more_aggressive"
                else "normal",
            }
        if proposal.proposal_type == "skill_package":
            return {
                "skill_name": proposal.structured_patch_payload.get("skill_name"),
                "surface": proposal.structured_patch_payload.get("surface"),
                "match_rules": dict(proposal.structured_patch_payload.get("match_rules") or {}),
                "runtime_directives": dict(proposal.structured_patch_payload.get("runtime_directives") or {}),
                "tool_plan": [dict(item) for item in (proposal.structured_patch_payload.get("tool_plan") or [])],
            }
        raise ValidationError("This proposal type is not rollout-enabled.")

    async def _observe_workflow_surface(self, rollout: ReflectionProposalRollout) -> ReflectionProposalRolloutObservation:
        tasks = await self._daily_task_repository.list_by_goal(rollout.learner_goal_id)
        workflow_runs = await self._workflow_run_repository.list_recent_by_goal(rollout.learner_goal_id, limit=20)
        relevant_tasks = [item for item in tasks if item.updated_at >= rollout.activated_at]
        relevant_runs = [item for item in workflow_runs if (item.finished_at or item.created_at) >= rollout.activated_at]
        surface_task_type = {
            "review_scheduling": "review",
            "assessment_generation": "assessment",
            "replan": "repair",
        }.get(rollout.surface)
        task_window = [item for item in relevant_tasks if surface_task_type is None or item.task_type == surface_task_type]
        workflow_window = [
            item
            for item in relevant_runs
            if (
                (rollout.surface == "review_scheduling" and item.workflow_type == "review_scheduling")
                or (rollout.surface == "assessment_generation" and item.workflow_type == "assessment_generation")
                or (rollout.surface == "replan" and item.workflow_type == "plan_extension")
            )
        ]
        completed_count = len([item for item in task_window if item.status == "completed"])
        failed_count = len([item for item in task_window if item.status == "failed"])
        skipped_count = len([item for item in task_window if item.status == "skipped"])
        workflow_failed_count = len([item for item in workflow_window if item.status == "failed"])
        observed_sample_count = len(task_window) + len(workflow_window)
        recommendation = "collecting"
        reason_codes: list[str] = []
        if workflow_failed_count > 0:
            recommendation = "rollback"
            reason_codes.append("workflow_failed")
        elif rollout.surface == "review_scheduling":
            if failed_count + skipped_count >= 2:
                recommendation = "rollback"
                reason_codes.append("review_failure_cluster")
            elif observed_sample_count >= 2 and completed_count >= 1:
                recommendation = "promote"
                reason_codes.append("review_completed")
        elif rollout.surface == "assessment_generation":
            if failed_count >= 1 and completed_count == 0:
                recommendation = "rollback"
                reason_codes.append("assessment_regressed")
            elif completed_count >= 1:
                recommendation = "promote"
                reason_codes.append("assessment_completed")
        elif rollout.surface == "replan":
            if failed_count + skipped_count >= 2:
                recommendation = "rollback"
                reason_codes.append("post_replan_failure_cluster")
            elif observed_sample_count >= 2 and failed_count + skipped_count <= 1:
                recommendation = "promote"
                reason_codes.append("post_replan_recovered")
        return ReflectionProposalRolloutObservation.build(
            rollout_id=rollout.id,
            proposal_id=rollout.proposal_id,
            learner_goal_id=rollout.learner_goal_id,
            surface=rollout.surface,
            recommendation=recommendation,
            observed_sample_count=observed_sample_count,
            positive_score=min(1.0, completed_count / 3 if completed_count else 0.0),
            negative_score=min(1.0, (failed_count + skipped_count + workflow_failed_count) / 3),
            signal_summary={
                "task_completed_count": completed_count,
                "task_failed_count": failed_count,
                "task_skipped_count": skipped_count,
                "workflow_failed_count": workflow_failed_count,
                "surface": rollout.surface,
            },
            reason_codes=reason_codes or ["collecting"],
        )
