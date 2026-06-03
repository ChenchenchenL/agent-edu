from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.skills import ALLOWED_SKILL_PACKAGE_TOOLS
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposal,
    ReflectionProposalApprovalDecision,
    ReflectionProposalEvaluation,
    proposal_policy_keys,
    proposal_rollout_surface,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalApprovalDecisionRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
)


class ReflectionProposalService:
    def __init__(
        self,
        *,
        repository: ReflectionProposalRepository,
        approval_decision_repository: ReflectionProposalApprovalDecisionRepository | None = None,
        evaluation_repository: ReflectionProposalEvaluationRepository | None = None,
        autonomy_job_service: AutonomyJobService | None = None,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._approval_decision_repository = approval_decision_repository
        self._evaluation_repository = evaluation_repository
        self._autonomy_job_service = autonomy_job_service
        self._audit_service = audit_service

    async def create_from_reflection(self, *, reflection: ReflectionRecord) -> list[ReflectionProposal]:
        proposals: list[ReflectionProposal] = []
        prompt_scope = self._prompt_target_scope(reflection)
        workflow_scope = self._workflow_target_scope(reflection)
        if reflection.primary_root_cause in {"knowledge_gap", "difficulty_mismatch", "review_gap", "engagement_constraint"}:
            proposals.append(
                ReflectionProposal.build(
                    reflection_record_id=reflection.id,
                    learner_goal_id=reflection.learner_goal_id,
                    proposal_type="prompt_optimization",
                    target_scope=prompt_scope,
                    priority_score=min(1.0, reflection.priority_score + 0.05),
                    hypothesis=self._prompt_hypothesis(reflection),
                    change_summary=self._prompt_change_summary(reflection),
                    structured_patch_payload=self._prompt_patch(reflection),
                    expected_improvement=self._prompt_expected_improvement(reflection),
                    risk_level="low",
                    evidence_snapshot=dict(reflection.evidence_payload),
                )
            )
        if reflection.primary_root_cause in {"sequencing_issue", "assessment_regression", "workflow_issue", "review_gap"}:
            proposals.append(
                ReflectionProposal.build(
                    reflection_record_id=reflection.id,
                    learner_goal_id=reflection.learner_goal_id,
                    proposal_type="workflow_optimization",
                    target_scope=workflow_scope,
                    priority_score=min(1.0, reflection.priority_score + 0.08),
                    hypothesis=self._workflow_hypothesis(reflection),
                    change_summary=self._workflow_change_summary(reflection),
                    structured_patch_payload=self._workflow_patch(reflection),
                    expected_improvement=self._workflow_expected_improvement(reflection),
                    risk_level="medium" if reflection.primary_root_cause != "workflow_issue" else "high",
                    evidence_snapshot=dict(reflection.evidence_payload),
                )
            )
        for proposal in proposals:
            self._validate_patch_payload(proposal)
            existing = await self._find_equivalent_active_proposal(proposal)
            if existing is not None:
                await self._audit_service.record(
                    event_type="reflection.proposal.deduplicated",
                    resource_type="reflection_proposal",
                    resource_id=existing.id,
                    actor="system",
                    event_data={
                        "reflection_record_id": reflection.id,
                        "proposal_type": existing.proposal_type,
                        "target_scope": existing.target_scope,
                    },
                )
                proposals[proposals.index(proposal)] = existing
                continue
            await self._repository.create(proposal)
            await self._audit_service.record(
                event_type="reflection.proposal.created",
                resource_type="reflection_proposal",
                resource_id=proposal.id,
                actor="system",
                event_data={
                    "reflection_record_id": reflection.id,
                    "proposal_type": proposal.proposal_type,
                    "target_scope": proposal.target_scope,
                    "priority_score": proposal.priority_score,
                },
            )
            admitted = await self._auto_admit_to_sandbox(proposal)
            if admitted is not None:
                proposals[proposals.index(proposal)] = admitted
        return proposals

    async def create_skill_packages_from_reflection(self, *, reflection: ReflectionRecord) -> list[ReflectionProposal]:
        bundle_id = str(uuid4())
        proposals: list[ReflectionProposal] = []
        for draft in self._skill_package_drafts(reflection, bundle_id=bundle_id):
            proposal = ReflectionProposal.build(
                reflection_record_id=reflection.id,
                learner_goal_id=reflection.learner_goal_id,
                proposal_type="skill_package",
                target_scope=str(draft["target_scope"]),
                priority_score=float(draft["priority_score"]),
                hypothesis=str(draft["hypothesis"]),
                change_summary=str(draft["change_summary"]),
                structured_patch_payload=dict(draft["structured_patch_payload"]),
                expected_improvement=str(draft["expected_improvement"]),
                risk_level=str(draft["risk_level"]),
                evidence_snapshot=dict(reflection.evidence_payload),
                proposal_bundle_id=bundle_id,
            )
            self._validate_patch_payload(proposal)
            existing = await self._find_equivalent_active_proposal(proposal)
            if existing is not None:
                proposals.append(existing)
                continue
            await self._repository.create(proposal)
            await self._audit_service.record(
                event_type="reflection.proposal.created",
                resource_type="reflection_proposal",
                resource_id=proposal.id,
                actor="system",
                event_data={
                    "reflection_record_id": reflection.id,
                    "proposal_type": proposal.proposal_type,
                    "target_scope": proposal.target_scope,
                    "priority_score": proposal.priority_score,
                    "proposal_bundle_id": bundle_id,
                },
            )
            admitted = await self._auto_admit_to_sandbox(proposal)
            proposals.append(admitted if admitted is not None else proposal)
        return proposals

    async def list_by_reflection(self, reflection_record_id: str) -> list[ReflectionProposal]:
        return await self._repository.list_by_reflection(reflection_record_id)

    async def list_queue(
        self,
        *,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ReflectionProposal], int]:
        items = await self._repository.list_queue(statuses=statuses, limit=limit, offset=offset)
        total = await self._repository.count_queue(statuses=statuses)
        return items, total

    async def get(self, proposal_id: str) -> ReflectionProposal:
        proposal = await self._repository.get_by_id(proposal_id)
        if proposal is None:
            raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
        return proposal

    async def get_evaluation(self, proposal_id: str) -> ReflectionProposalEvaluation:
        await self.get(proposal_id)
        if self._evaluation_repository is None:
            raise NotFoundError(f"Reflection proposal evaluation for '{proposal_id}' was not found.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal_id)
        if evaluation is None:
            raise NotFoundError(f"Reflection proposal evaluation for '{proposal_id}' was not found.")
        return evaluation

    async def describe(self, proposal: ReflectionProposal) -> dict[str, object]:
        activation_surface = proposal_rollout_surface(proposal.target_scope)
        return {
            **proposal.__dict__,
            "auto_sandbox_eligible": proposal.risk_level in {"low", "medium"},
            "admission_mode": "auto" if proposal.risk_level in {"low", "medium"} else "manual",
            "rollout_eligible": activation_surface is not None,
            "activation_surface": activation_surface,
        }

    async def review(self, *, proposal_id: str, status: str, evaluation_status: str | None = None, evaluation_summary: str | None = None) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.with_status(
            status,
            evaluation_status=evaluation_status,
            evaluation_summary=evaluation_summary,
        )
        await self._repository.update(updated)
        return updated

    async def enqueue_sandbox(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        if self._autonomy_job_service is None:
            raise ValidationError("Sandbox job service is not configured.")
        proposal = await self.get(proposal_id)
        if proposal.status in {"sandbox_queued", "sandbox_running", "sandbox_completed", "approved"}:
            return proposal
        job = await self._autonomy_job_service.create_job(
            learner_goal_id=proposal.learner_goal_id,
            job_type="reflection_proposal_evaluation",
            trigger_source="operator_sandbox_request",
            due_at=proposal.updated_at,
            idempotency_key=f"proposal:{proposal.id}:sandbox",
            payload={
                "proposal_id": proposal.id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )
        if job is None:
            raise ValidationError("Sandbox job could not be scheduled.")
        updated = proposal.enqueue_sandbox(sandbox_run_id=job.id)
        await self._repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.proposal.sandbox.queued",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "proposal_id": proposal.id,
                "autonomy_job_id": job.id,
                "operator_id": operator_id,
                "reason_code": reason_code,
            },
        )
        return updated

    async def auto_enqueue_sandbox(self, *, proposal_id: str) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        if self._autonomy_job_service is None:
            return proposal
        if proposal.status in {"sandbox_queued", "sandbox_running", "sandbox_completed", "approved"}:
            return proposal
        job = await self._autonomy_job_service.create_job(
            learner_goal_id=proposal.learner_goal_id,
            job_type="reflection_proposal_evaluation",
            trigger_source="reflection_auto_admission",
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"proposal:{proposal.id}:auto_sandbox",
            payload={
                "proposal_id": proposal.id,
                "admission_mode": "auto",
            },
        )
        if job is None:
            return proposal
        updated = proposal.enqueue_sandbox(sandbox_run_id=job.id)
        await self._repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.proposal.auto_admitted",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor="system",
            event_data={
                "proposal_id": proposal.id,
                "autonomy_job_id": job.id,
                "risk_level": proposal.risk_level,
                "target_scope": proposal.target_scope,
            },
        )
        return updated

    async def approve(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.approve(
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        await self._repository.update(updated)
        await self._record_decision(
            ReflectionProposalApprovalDecision.build(
                proposal_id=proposal.id,
                decision_type="approved",
                previous_status=proposal.status,
                new_status=updated.status,
                reason_code=reason_code,
                reason_note=reason_note,
                operator_id=operator_id,
            )
        )
        await self._audit_service.record(
            event_type="reflection.proposal.approved",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={"proposal_id": proposal.id, "operator_id": operator_id, "reason_code": reason_code},
        )
        return updated

    async def reject(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.reject(
            evaluation_status="ineffective" if proposal.evaluation_status == "pending" else proposal.evaluation_status,
            evaluation_summary=reason_note or reason_code,
        )
        await self._repository.update(updated)
        await self._record_decision(
            ReflectionProposalApprovalDecision.build(
                proposal_id=proposal.id,
                decision_type="rejected",
                previous_status=proposal.status,
                new_status=updated.status,
                reason_code=reason_code,
                reason_note=reason_note,
                operator_id=operator_id,
            )
        )
        await self._audit_service.record(
            event_type="reflection.proposal.rejected",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={"proposal_id": proposal.id, "operator_id": operator_id, "reason_code": reason_code},
        )
        return updated

    async def list_approval_decisions(self, proposal_id: str) -> list[ReflectionProposalApprovalDecision]:
        if self._approval_decision_repository is None:
            return []
        return await self._approval_decision_repository.list_by_proposal(proposal_id)

    async def mark_sandbox_started(self, *, proposal_id: str, sandbox_run_id: str) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.start_sandbox(sandbox_run_id=sandbox_run_id)
        await self._repository.update(updated)
        return updated

    async def mark_sandbox_queued(self, *, proposal_id: str, sandbox_run_id: str) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.enqueue_sandbox(sandbox_run_id=sandbox_run_id)
        await self._repository.update(updated)
        return updated

    async def mark_sandbox_completed(
        self,
        *,
        proposal_id: str,
        sandbox_run_id: str,
        evaluation_status: str,
        evaluation_summary: str,
    ) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.complete_sandbox(
            sandbox_run_id=sandbox_run_id,
            evaluation_status=evaluation_status,
            evaluation_summary=evaluation_summary,
        )
        await self._repository.update(updated)
        return updated

    async def mark_sandbox_failed(
        self,
        *,
        proposal_id: str,
        sandbox_run_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        proposal = await self.get(proposal_id)
        updated = proposal.with_status(
            "proposed",
            latest_sandbox_run_id=sandbox_run_id,
            evaluation_status="pending",
            evaluation_summary=reason_note or reason_code,
        )
        await self._repository.update(updated)
        return updated

    @staticmethod
    def _workflow_target_scope(reflection: ReflectionRecord) -> str:
        if reflection.target_type == "workflow_run":
            workflow = str((reflection.evidence_payload.get("workflow") or {}).get("workflow_type") or "")
            return {
                "plan_generation": "plan_generation",
                "review_scheduling": "review_scheduling",
                "assessment_generation": "assessment_generation",
                "plan_extension": "replan",
            }.get(workflow, "replan")
        if reflection.primary_root_cause == "review_gap":
            return "review_scheduling"
        if reflection.primary_root_cause == "assessment_regression":
            return "assessment_generation"
        return "replan"

    @staticmethod
    def _prompt_target_scope(reflection: ReflectionRecord) -> str:
        task_type = str((reflection.evidence_payload.get("task") or {}).get("task_type") or "")
        session_signals = dict((reflection.evidence_payload or {}).get("session_signals") or {})
        if int(session_signals.get("hint_turn_count") or 0) >= 2:
            return "hint"
        if task_type in {"lesson", "repair"}:
            return "chat"
        return "hint"

    @staticmethod
    def _validate_patch_payload(proposal: ReflectionProposal) -> None:
        allowed = proposal_policy_keys(proposal.proposal_type)
        keys = set(proposal.structured_patch_payload.keys())
        if not keys.issubset(allowed):
            raise ValidationError("Unsupported proposal patch keys.")
        if proposal.proposal_type == "skill_package":
            surface = str(proposal.structured_patch_payload.get("surface") or "")
            if surface != proposal.target_scope:
                raise ValidationError("Skill package surface must match proposal target scope.")
            tool_plan = proposal.structured_patch_payload.get("tool_plan") or []
            if not isinstance(tool_plan, list):
                raise ValidationError("Skill package tool_plan must be a list.")
            for item in tool_plan:
                if not isinstance(item, dict):
                    raise ValidationError("Skill package tool_plan items must be objects.")
                tool_name = str(item.get("tool_name") or "")
                if tool_name not in ALLOWED_SKILL_PACKAGE_TOOLS:
                    raise ValidationError("Unsupported skill package tool.")

    async def _find_equivalent_active_proposal(
        self,
        proposal: ReflectionProposal,
    ) -> ReflectionProposal | None:
        candidates = await self._repository.list_queue(
            statuses={"proposed", "sandbox_queued", "sandbox_running", "sandbox_completed", "approved"},
            learner_goal_id=proposal.learner_goal_id,
            proposal_type=proposal.proposal_type,
            target_scope=proposal.target_scope,
            limit=200,
            offset=0,
        )
        for item in candidates:
            if (
                item.structured_patch_payload == proposal.structured_patch_payload
            ):
                return item
        return None

    async def _auto_admit_to_sandbox(self, proposal: ReflectionProposal) -> ReflectionProposal | None:
        if self._autonomy_job_service is None:
            await self._audit_service.record(
                event_type="reflection.proposal.manual_review_required",
                resource_type="reflection_proposal",
                resource_id=proposal.id,
                actor="system",
                event_data={
                    "proposal_id": proposal.id,
                    "risk_level": proposal.risk_level,
                    "target_scope": proposal.target_scope,
                    "reason_code": "sandbox_job_service_unavailable",
                },
            )
            return None
        if proposal.risk_level not in {"low", "medium"}:
            await self._audit_service.record(
                event_type="reflection.proposal.manual_review_required",
                resource_type="reflection_proposal",
                resource_id=proposal.id,
                actor="system",
                event_data={
                    "proposal_id": proposal.id,
                    "risk_level": proposal.risk_level,
                    "target_scope": proposal.target_scope,
                },
            )
            return None
        return await self.auto_enqueue_sandbox(proposal_id=proposal.id)

    @staticmethod
    def _skill_package_drafts(
        reflection: ReflectionRecord,
        *,
        bundle_id: str,
    ) -> list[dict[str, object]]:
        mapping = {
            "knowledge_gap": ["chat", "hint", "quiz"],
            "difficulty_mismatch": ["chat", "hint", "plan_generation"],
            "review_gap": ["quiz", "review_scheduling"],
            "sequencing_issue": ["plan_generation", "replan"],
            "engagement_constraint": ["chat", "hint"],
            "workflow_issue": ["replan"],
            "assessment_regression": ["quiz", "assessment_generation", "plan_generation"],
        }
        surfaces = mapping.get(reflection.primary_root_cause, [])
        topic_key = str((reflection.evidence_payload.get("task") or {}).get("topic_focus") or "")
        task_type = str((reflection.evidence_payload.get("task") or {}).get("task_type") or "")
        skill_name_by_surface = {
            "chat": "explain_concept",
            "hint": "adaptive_hint",
            "quiz": "create_quiz",
            "plan_generation": "plan_study_path",
            "review_scheduling": "schedule_review",
            "assessment_generation": "create_quiz",
            "replan": "plan_study_path",
        }
        trigger_sources_by_surface = {
            "chat": ["chat"],
            "hint": ["hint"],
            "quiz": ["quiz_generation"],
            "review_scheduling": ["task_completed"],
        }
        drafts: list[dict[str, object]] = []
        for surface in surfaces:
            runtime_directives: dict[str, object]
            tool_plan: list[dict[str, object]]
            if surface in {"chat", "hint"}:
                runtime_directives = {
                    "response_preference": "guided",
                    "teaching_goal": "unblock next step",
                    "hint_level_preference": "targeted" if surface == "hint" else "scaffolded",
                    "skill_directives": [f"Use a {reflection.primary_root_cause} remediation micro-lesson."],
                }
                tool_plan = []
            elif surface == "quiz":
                runtime_directives = {
                    "difficulty_bias": "supportive",
                    "question_count": 3 if reflection.primary_root_cause != "assessment_regression" else 5,
                    "feedback_style": "guided_correction",
                    "skill_directives": [f"Probe for {reflection.primary_root_cause} with short checks."],
                }
                tool_plan = []
            elif surface == "plan_generation":
                runtime_directives = {
                    "practice_density": "high",
                    "milestone_bias": "earlier" if reflection.primary_root_cause == "assessment_regression" else "standard",
                    "skill_directives": [f"Bias plan generation toward {reflection.primary_root_cause} recovery."],
                }
                tool_plan = []
            elif surface == "review_scheduling":
                runtime_directives = {"review_bias": "intensive"}
                tool_plan = [{"tool_name": "review_scheduling", "payload_template": {"source_task_id": "$source_task_id"}}]
            elif surface == "assessment_generation":
                runtime_directives = {"assessment_bias": "early"}
                tool_plan = [{"tool_name": "assessment_generation", "payload_template": {"learner_goal_id": "$learner_goal_id", "topic_focus": "$topic_focus"}}]
            else:
                runtime_directives = {"replan_bias": "aggressive"}
                tool_plan = [{"tool_name": "partial_replan", "payload_template": {"source_task_id": "$source_task_id"}}]
            drafts.append(
                {
                    "target_scope": surface,
                    "priority_score": min(1.0, reflection.priority_score + 0.12),
                    "hypothesis": f"A reusable {surface} skill package can reduce repeated {reflection.primary_root_cause} failures.",
                    "change_summary": f"Introduce a governed single-surface skill package for {surface}.",
                    "expected_improvement": "Turn repeated effective reflection patterns into reusable runtime behavior.",
                    "risk_level": "high" if surface == "replan" else ("medium" if surface in {"plan_generation", "review_scheduling", "assessment_generation"} else "low"),
                    "structured_patch_payload": {
                        "artifact_kind": "declarative_skill_package",
                        "skill_name": skill_name_by_surface[surface],
                        "bundle_id": bundle_id,
                        "surface": surface,
                        "match_rules": {
                            "required_root_causes": [reflection.primary_root_cause],
                            "topic_keys": [topic_key] if topic_key else [],
                            "task_types": [task_type] if task_type else [],
                            "trigger_sources": trigger_sources_by_surface.get(surface, []),
                        },
                        "runtime_directives": runtime_directives,
                        "tool_plan": tool_plan,
                        "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
                    },
                }
            )
        return drafts

    @staticmethod
    def _prompt_patch(reflection: ReflectionRecord) -> dict[str, object]:
        if reflection.primary_root_cause == "difficulty_mismatch":
            return {
                "response_preference_bias": "guided",
                "hint_level_preference": "targeted",
                "teaching_goal_override": "reduce difficulty gradient",
            }
        return {
            "response_preference_bias": "guided",
            "hint_level_preference": "scaffolded",
            "teaching_goal_override": "unblock next step",
        }

    @staticmethod
    def _prompt_hypothesis(reflection: ReflectionRecord) -> str:
        return f"Interaction framing for {reflection.primary_root_cause} is not producing stable learner progress."

    @staticmethod
    def _prompt_change_summary(reflection: ReflectionRecord) -> str:
        if reflection.primary_root_cause == "difficulty_mismatch":
            return "Bias the tutor toward smaller, targeted steps before fuller explanations."
        return "Bias the tutor toward scaffolded guidance before longer explanations."

    @staticmethod
    def _prompt_expected_improvement(reflection: ReflectionRecord) -> str:
        return "Reduce repeated confusion, direct-answer pressure, and high hint dependency."

    @staticmethod
    def _workflow_patch(reflection: ReflectionRecord) -> dict[str, object]:
        if reflection.primary_root_cause == "review_gap":
            return {
                "review_interval_policy": "denser",
                "assessment_threshold_policy": "standard",
                "replan_mode_policy": "normal",
            }
        if reflection.primary_root_cause == "assessment_regression":
            return {
                "review_interval_policy": "normal",
                "assessment_threshold_policy": "earlier",
                "replan_mode_policy": "normal",
            }
        return {
            "review_interval_policy": "denser",
            "assessment_threshold_policy": "earlier",
            "replan_mode_policy": "more_aggressive",
        }

    @staticmethod
    def _workflow_hypothesis(reflection: ReflectionRecord) -> str:
        return f"Workflow sequencing for {reflection.primary_root_cause} is not matching learner state."

    @staticmethod
    def _workflow_change_summary(reflection: ReflectionRecord) -> str:
        mapping = {
            "review_gap": "Tighten review scheduling without making replan more aggressive.",
            "assessment_regression": "Move assessment checkpoints earlier and preserve normal replan posture.",
        }
        return mapping.get(
            reflection.primary_root_cause,
            "Adjust review, assessment, and replan orchestration thresholds.",
        )

    @staticmethod
    def _workflow_expected_improvement(reflection: ReflectionRecord) -> str:
        return "Improve post-failure recovery and reduce repeated review/assessment/replan loops."

    async def _record_decision(self, decision: ReflectionProposalApprovalDecision) -> None:
        if self._approval_decision_repository is None:
            return
        await self._approval_decision_repository.create(decision)
