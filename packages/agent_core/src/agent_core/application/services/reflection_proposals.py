from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.skills import ALLOWED_SKILL_PACKAGE_TOOLS
from agent_core.application.services.tool_plan_contracts import validate_tool_plan_contract
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
    SkillArtifactRepository,
)

MERGE_RELATED_ARTIFACT_STATUSES = {"candidate", "staged", "active", "stable", "deprecated"}


class ReflectionProposalService:
    def __init__(
        self,
        *,
        repository: ReflectionProposalRepository,
        approval_decision_repository: ReflectionProposalApprovalDecisionRepository | None = None,
        evaluation_repository: ReflectionProposalEvaluationRepository | None = None,
        artifact_repository: SkillArtifactRepository | None = None,
        autonomy_job_service: AutonomyJobService | None = None,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._approval_decision_repository = approval_decision_repository
        self._evaluation_repository = evaluation_repository
        self._artifact_repository = artifact_repository
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

    async def create_skill_patch_request_from_recommendation(
        self,
        *,
        recommendation_id: str,
        artifact_id: str | None,
        skill_name: str,
        skill_version: str | None,
        scope: str,
        surface: str,
        recommendation_reason_code: str,
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        related_artifact_ids: list[str],
        reflection_record_id: str,
        learner_goal_id: str,
        operator_id: str,
    ) -> ReflectionProposal:
        if not reflection_record_id.strip() or not learner_goal_id.strip():
            raise ValidationError("Skill patch request requires reflection_record_id and learner_goal_id.")
        payload = {
            "artifact_id": artifact_id,
            "skill_name": skill_name,
            "skill_version": skill_version,
            "scope": scope,
            "surface": surface,
            "recommendation_id": recommendation_id,
            "recommendation_reason_code": recommendation_reason_code,
            "usage_event_ids": self._skill_patch_usage_event_ids(evidence_snapshot),
            "related_artifact_ids": list(related_artifact_ids),
            "evidence_snapshot": dict(evidence_snapshot),
            "metrics_snapshot": dict(metrics_snapshot),
        }
        proposal = ReflectionProposal.build(
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            proposal_type="skill_patch_request",
            target_scope=surface,
            priority_score=self._skill_patch_priority(metrics_snapshot),
            hypothesis=f"Curator evidence indicates {skill_name} may need a governed skill patch.",
            change_summary=f"Create a governed patch request for {skill_name} on {surface}.",
            structured_patch_payload=payload,
            expected_improvement="Route negative skill evidence into sandboxed proposal review before artifact changes.",
            risk_level="medium",
            evidence_snapshot={
                "source": "skill_curator_recommendation",
                "recommendation_id": recommendation_id,
                "artifact_id": artifact_id,
                "skill_name": skill_name,
                "scope": scope,
                "surface": surface,
                "recommendation_reason_code": recommendation_reason_code,
                "evidence_snapshot": dict(evidence_snapshot),
                "metrics_snapshot": dict(metrics_snapshot),
            },
        )
        self._validate_patch_payload(proposal)
        existing = await self._find_equivalent_active_proposal(proposal)
        if existing is not None:
            await self._audit_service.record(
                event_type="reflection.proposal.deduplicated",
                resource_type="reflection_proposal",
                resource_id=existing.id,
                actor=operator_id,
                event_data={
                    "reflection_record_id": reflection_record_id,
                    "proposal_type": existing.proposal_type,
                    "target_scope": existing.target_scope,
                    "recommendation_id": recommendation_id,
                },
            )
            return existing
        await self._repository.create(proposal)
        await self._audit_service.record(
            event_type="reflection.proposal.created",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "reflection_record_id": reflection_record_id,
                "proposal_type": proposal.proposal_type,
                "target_scope": proposal.target_scope,
                "priority_score": proposal.priority_score,
                "recommendation_id": recommendation_id,
            },
        )
        admitted = await self._auto_admit_to_sandbox(proposal)
        return admitted if admitted is not None else proposal

    async def create_skill_merge_package_from_recommendation(
        self,
        *,
        recommendation_id: str,
        artifact_id: str | None,
        skill_name: str,
        skill_version: str | None,
        scope: str,
        surface: str,
        recommendation_reason_code: str,
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
        related_artifact_ids: list[str],
        reflection_record_id: str,
        learner_goal_id: str,
        operator_id: str,
    ) -> ReflectionProposal:
        if not reflection_record_id.strip() or not learner_goal_id.strip():
            raise ValidationError("Skill merge proposal requires reflection_record_id and learner_goal_id.")
        if self._artifact_repository is None:
            raise ValidationError("Skill merge proposal requires skill artifact access.")
        if artifact_id is None or not artifact_id.strip():
            raise ValidationError("Skill merge proposal requires a source artifact_id.")

        source_artifact = await self._artifact_repository.get_by_id(artifact_id)
        if source_artifact is None:
            raise ValidationError("Skill merge proposal requires an existing source artifact.")
        self._validate_merge_source_artifact(
            artifact=source_artifact,
            skill_name=skill_name,
            skill_version=skill_version,
            scope=scope,
            surface=surface,
        )
        merge_artifacts = await self._merge_source_artifacts(
            source_artifact=source_artifact,
            related_artifact_ids=related_artifact_ids,
        )

        proposal = ReflectionProposal.build(
            reflection_record_id=reflection_record_id,
            learner_goal_id=learner_goal_id,
            proposal_type="skill_package",
            target_scope=source_artifact.scope,
            priority_score=self._skill_merge_priority(metrics_snapshot),
            hypothesis=f"A governed merge for {source_artifact.name} can consolidate overlapping skill package coverage.",
            change_summary=f"Merge compatible {source_artifact.name} skill package match coverage into a replacement package.",
            structured_patch_payload=self._merge_skill_package_payload(
                source_artifact=source_artifact,
                merge_artifacts=merge_artifacts,
            ),
            expected_improvement="Evaluate merged skill package coverage through existing sandbox and lifecycle gates before artifact changes.",
            risk_level="medium",
            evidence_snapshot=self._merge_skill_package_evidence(
                recommendation_id=recommendation_id,
                recommendation_reason_code=recommendation_reason_code,
                source_artifact=source_artifact,
                merge_artifacts=merge_artifacts,
                evidence_snapshot=evidence_snapshot,
                metrics_snapshot=metrics_snapshot,
            ),
        )
        self._validate_patch_payload(proposal)
        existing = await self._find_merge_skill_package_proposal(
            recommendation_id=recommendation_id,
            learner_goal_id=learner_goal_id,
            target_scope=source_artifact.scope,
        )
        if existing is not None:
            await self._audit_service.record(
                event_type="reflection.proposal.deduplicated",
                resource_type="reflection_proposal",
                resource_id=existing.id,
                actor=operator_id,
                event_data={
                    "reflection_record_id": reflection_record_id,
                    "proposal_type": existing.proposal_type,
                    "target_scope": existing.target_scope,
                    "recommendation_id": recommendation_id,
                    "source": "skill_curator_merge_recommendation",
                },
            )
            return existing
        await self._repository.create(proposal)
        await self._audit_service.record(
            event_type="reflection.proposal.created",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "reflection_record_id": reflection_record_id,
                "proposal_type": proposal.proposal_type,
                "target_scope": proposal.target_scope,
                "priority_score": proposal.priority_score,
                "recommendation_id": recommendation_id,
                "source": "skill_curator_merge_recommendation",
            },
        )
        await self._audit_service.record(
            event_type="reflection.proposal.skill_merge_created",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "recommendation_id": recommendation_id,
                "derived_proposal_id": proposal.id,
                "source_artifact_id": source_artifact.id,
                "source_artifact_version": source_artifact.version,
                "source_artifact_status": source_artifact.status,
                "merge_source_artifact_ids": [artifact.id for artifact in merge_artifacts],
                "operator_id": operator_id,
            },
        )
        admitted = await self._auto_admit_to_sandbox(proposal)
        return admitted if admitted is not None else proposal

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

    async def realize_skill_patch_request(
        self,
        *,
        proposal_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> ReflectionProposal:
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        if self._evaluation_repository is None:
            raise ValidationError("Skill patch realization requires proposal evaluations.")
        if self._artifact_repository is None:
            raise ValidationError("Skill patch realization requires skill artifact access.")

        patch_request = await self.get(proposal_id)
        if patch_request.proposal_type != "skill_patch_request":
            raise ValidationError("Only skill_patch_request proposals can be realized.")
        if patch_request.status != "approved":
            raise ValidationError("Only approved skill_patch_request proposals can be realized.")
        if patch_request.evaluation_status != "effective":
            raise ValidationError("Skill patch realization requires an effective patch request.")

        evaluation = await self._evaluation_repository.get_by_proposal(patch_request.id)
        if evaluation is None or evaluation.evaluation_status != "effective":
            raise ValidationError("Skill patch realization requires an effective evaluation.")

        payload = dict(patch_request.structured_patch_payload)
        artifact_id = payload.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id.strip():
            raise ValidationError("Skill patch realization requires a source artifact_id.")
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise ValidationError("Skill patch realization requires an existing source artifact.")
        self._validate_patch_request_artifact_anchor(patch_request=patch_request, artifact=artifact)

        existing = await self._find_realized_skill_patch_proposal(patch_request)
        if existing is not None:
            await self._audit_service.record(
                event_type="reflection.proposal.skill_patch_realize_reused",
                resource_type="reflection_proposal",
                resource_id=existing.id,
                actor=operator_id,
                event_data={
                    "source_skill_patch_request_id": patch_request.id,
                    "derived_proposal_id": existing.id,
                    "source_artifact_id": artifact.id,
                    "operator_id": operator_id,
                    "reason_code": reason_code,
                    "reason_note": reason_note,
                },
            )
            return existing

        proposal = ReflectionProposal.build(
            reflection_record_id=patch_request.reflection_record_id,
            learner_goal_id=patch_request.learner_goal_id,
            proposal_type="skill_package",
            target_scope=artifact.scope,
            priority_score=patch_request.priority_score,
            hypothesis=f"A governed replacement for {artifact.name} can address curator patch request evidence.",
            change_summary=f"Realize approved skill patch request into a replacement skill package for {artifact.name}.",
            structured_patch_payload=self._replacement_skill_package_payload(artifact),
            expected_improvement="Evaluate a replacement skill package through existing sandbox and lifecycle gates before artifact changes.",
            risk_level=patch_request.risk_level,
            evidence_snapshot=self._replacement_skill_package_evidence(
                patch_request=patch_request,
                evaluation=evaluation,
                artifact=artifact,
            ),
        )
        self._validate_patch_payload(proposal)
        await self._repository.create(proposal)
        await self._audit_service.record(
            event_type="reflection.proposal.created",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "reflection_record_id": proposal.reflection_record_id,
                "proposal_type": proposal.proposal_type,
                "target_scope": proposal.target_scope,
                "priority_score": proposal.priority_score,
                "source_skill_patch_request_id": patch_request.id,
            },
        )
        await self._audit_service.record(
            event_type="reflection.proposal.skill_patch_realized",
            resource_type="reflection_proposal",
            resource_id=proposal.id,
            actor=operator_id,
            event_data={
                "source_skill_patch_request_id": patch_request.id,
                "derived_proposal_id": proposal.id,
                "source_artifact_id": artifact.id,
                "source_artifact_version": artifact.version,
                "source_artifact_status": artifact.status,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )
        admitted = await self._auto_admit_to_sandbox(proposal)
        return admitted if admitted is not None else proposal

    async def describe(self, proposal: ReflectionProposal) -> dict[str, object]:
        activation_surface = self._activation_surface(proposal)
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
            validate_tool_plan_contract(surface, tool_plan)
        if proposal.proposal_type == "skill_patch_request":
            payload = proposal.structured_patch_payload
            for key in ("skill_name", "scope", "surface", "recommendation_id", "recommendation_reason_code"):
                if not isinstance(payload.get(key), str) or not str(payload.get(key)).strip():
                    raise ValidationError("Skill patch request payload is incomplete.")
            if payload.get("surface") != proposal.target_scope:
                raise ValidationError("Skill patch request surface must match proposal target scope.")
            for key in ("usage_event_ids", "related_artifact_ids"):
                if not isinstance(payload.get(key), list):
                    raise ValidationError("Skill patch request reference fields must be lists.")
            for key in ("evidence_snapshot", "metrics_snapshot"):
                if not isinstance(payload.get(key), dict):
                    raise ValidationError("Skill patch request snapshots must be objects.")

    @staticmethod
    def _validate_patch_request_artifact_anchor(
        *,
        patch_request: ReflectionProposal,
        artifact: Any,
    ) -> None:
        payload = patch_request.structured_patch_payload
        if payload.get("skill_name") != artifact.name:
            raise ValidationError("Skill patch request skill_name does not match source artifact.")
        if payload.get("scope") != artifact.scope or payload.get("surface") != artifact.scope:
            raise ValidationError("Skill patch request scope does not match source artifact.")
        skill_version = payload.get("skill_version")
        if isinstance(skill_version, str) and skill_version.strip() and skill_version != artifact.version:
            raise ValidationError("Skill patch request skill_version does not match source artifact.")

    @staticmethod
    def _replacement_skill_package_payload(artifact: Any) -> dict[str, Any]:
        match_rules = artifact.definition.get("match_rules")
        scoring_contract = artifact.definition.get("scoring_contract")
        if not isinstance(match_rules, dict):
            raise ValidationError("Source artifact is missing match_rules for replacement proposal.")
        if not isinstance(scoring_contract, dict):
            raise ValidationError("Source artifact is missing scoring_contract for replacement proposal.")
        return {
            "artifact_kind": "declarative_skill_package",
            "skill_name": artifact.name,
            "surface": artifact.scope,
            "match_rules": dict(match_rules),
            "runtime_directives": dict(artifact.runtime_directives),
            "tool_plan": [dict(item) for item in artifact.tool_plan],
            "scoring_contract": dict(scoring_contract),
        }

    @staticmethod
    def _replacement_skill_package_evidence(
        *,
        patch_request: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation,
        artifact: Any,
    ) -> dict[str, Any]:
        payload = dict(patch_request.structured_patch_payload)
        return {
            "source": "skill_patch_request_realization",
            "source_skill_patch_request_id": patch_request.id,
            "source_artifact_id": artifact.id,
            "source_artifact_version": artifact.version,
            "source_artifact_status": artifact.status,
            "source_artifact_lineage_id": artifact.lineage_id,
            "source_parent_artifact_id": artifact.parent_artifact_id,
            "source_supersedes_artifact_id": artifact.supersedes_artifact_id,
            "recommendation_id": payload.get("recommendation_id"),
            "recommendation_reason_code": payload.get("recommendation_reason_code"),
            "usage_event_ids": list(payload.get("usage_event_ids") or []),
            "related_artifact_ids": list(payload.get("related_artifact_ids") or []),
            "patch_request_evidence_snapshot": dict(payload.get("evidence_snapshot") or {}),
            "patch_request_metrics_snapshot": dict(payload.get("metrics_snapshot") or {}),
            "patch_request_evaluation": {
                "id": evaluation.id,
                "evaluation_status": evaluation.evaluation_status,
                "comparison_window_size": evaluation.comparison_window_size,
                "score_delta": evaluation.score_delta,
                "evaluator_type": evaluation.evaluator_type,
                "sandbox_run_id": evaluation.sandbox_run_id,
                "proposal_evaluation_summary": patch_request.evaluation_summary,
                "simulated_outcome_summary": dict(evaluation.simulated_outcome_summary),
            },
        }

    def _validate_merge_source_artifact(
        self,
        *,
        artifact: Any,
        skill_name: str,
        skill_version: str | None,
        scope: str,
        surface: str,
    ) -> None:
        if artifact.status not in {"active", "stable"}:
            raise ValidationError("Skill merge proposal requires an active or stable source artifact.")
        if artifact.name != skill_name or artifact.scope != scope or artifact.scope != surface:
            raise ValidationError("Skill merge proposal source artifact does not match recommendation anchor.")
        if skill_version is not None and skill_version.strip() and artifact.version != skill_version:
            raise ValidationError("Skill merge proposal source artifact version does not match recommendation anchor.")
        self._replacement_skill_package_payload(artifact)

    async def _merge_source_artifacts(
        self,
        *,
        source_artifact: Any,
        related_artifact_ids: list[str],
    ) -> list[Any]:
        if self._artifact_repository is None:
            raise ValidationError("Skill merge proposal requires skill artifact access.")
        unique_ids: list[str] = []
        for artifact_id in related_artifact_ids:
            if not isinstance(artifact_id, str) or not artifact_id.strip():
                continue
            artifact_id = artifact_id.strip()
            if artifact_id == source_artifact.id or artifact_id in unique_ids:
                continue
            unique_ids.append(artifact_id)
        if not unique_ids:
            raise ValidationError("Skill merge proposal requires related_artifact_ids.")

        artifacts: list[Any] = []
        for artifact_id in unique_ids:
            artifact = await self._artifact_repository.get_by_id(artifact_id)
            if artifact is None:
                raise ValidationError("Skill merge proposal requires existing related artifacts.")
            if artifact.status not in MERGE_RELATED_ARTIFACT_STATUSES:
                raise ValidationError(
                    "Skill merge proposal related artifacts must be governed candidate, staged, active, stable, "
                    "or deprecated artifacts."
                )
            if not self._merge_artifact_matches_source(source_artifact=source_artifact, artifact=artifact):
                raise ValidationError(
                    "Skill merge proposal related artifacts must match source skill/scope or implementation binding."
                )
            self._replacement_skill_package_payload(artifact)
            artifacts.append(artifact)
        return artifacts

    @staticmethod
    def _merge_artifact_matches_source(
        *,
        source_artifact: Any,
        artifact: Any,
    ) -> bool:
        if artifact.scope != source_artifact.scope:
            return False
        if artifact.name == source_artifact.name:
            return True
        source_binding = ReflectionProposalService._implementation_binding(source_artifact)
        artifact_binding = ReflectionProposalService._implementation_binding(artifact)
        return source_binding is not None and artifact_binding == source_binding

    @staticmethod
    def _implementation_binding(artifact: Any) -> str | None:
        value = artifact.compatibility_contract.get("implementation_binding")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @staticmethod
    def _merge_skill_package_payload(
        *,
        source_artifact: Any,
        merge_artifacts: list[Any],
    ) -> dict[str, Any]:
        payload = ReflectionProposalService._replacement_skill_package_payload(source_artifact)
        match_rules = dict(payload["match_rules"])
        for artifact in merge_artifacts:
            merge_match_rules = artifact.definition.get("match_rules")
            if not isinstance(merge_match_rules, dict):
                raise ValidationError("Related artifact is missing match_rules for merge proposal.")
            for key, value in merge_match_rules.items():
                if not isinstance(value, list):
                    continue
                existing = match_rules.get(key)
                if not isinstance(existing, list):
                    existing = []
                merged = list(existing)
                for item in value:
                    if item not in merged:
                        merged.append(item)
                match_rules[key] = merged
        payload["match_rules"] = match_rules
        return payload

    @staticmethod
    def _merge_skill_package_evidence(
        *,
        recommendation_id: str,
        recommendation_reason_code: str,
        source_artifact: Any,
        merge_artifacts: list[Any],
        evidence_snapshot: dict[str, Any],
        metrics_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "source": "skill_curator_merge_recommendation",
            "recommendation_id": recommendation_id,
            "recommendation_reason_code": recommendation_reason_code,
            "source_artifact_id": source_artifact.id,
            "source_artifact_version": source_artifact.version,
            "source_artifact_status": source_artifact.status,
            "source_artifact_lineage_id": source_artifact.lineage_id,
            "source_parent_artifact_id": source_artifact.parent_artifact_id,
            "source_supersedes_artifact_id": source_artifact.supersedes_artifact_id,
            "merge_source_artifact_ids": [artifact.id for artifact in merge_artifacts],
            "merge_source_artifact_versions": {
                artifact.id: artifact.version for artifact in merge_artifacts
            },
            "merge_source_artifact_statuses": {
                artifact.id: artifact.status for artifact in merge_artifacts
            },
            "recommendation_evidence_snapshot": dict(evidence_snapshot),
            "recommendation_metrics_snapshot": dict(metrics_snapshot),
        }

    async def _find_realized_skill_patch_proposal(
        self,
        patch_request: ReflectionProposal,
    ) -> ReflectionProposal | None:
        candidates = await self._repository.list_queue(
            statuses={"proposed", "sandbox_queued", "sandbox_running", "sandbox_completed", "approved"},
            learner_goal_id=patch_request.learner_goal_id,
            proposal_type="skill_package",
            target_scope=patch_request.target_scope,
            limit=200,
            offset=0,
        )
        for item in candidates:
            if item.evidence_snapshot.get("source_skill_patch_request_id") == patch_request.id:
                return item
        return None

    async def _find_merge_skill_package_proposal(
        self,
        *,
        recommendation_id: str,
        learner_goal_id: str,
        target_scope: str,
    ) -> ReflectionProposal | None:
        candidates = await self._repository.list_queue(
            statuses={"proposed", "sandbox_queued", "sandbox_running", "sandbox_completed", "approved"},
            learner_goal_id=learner_goal_id,
            proposal_type="skill_package",
            target_scope=target_scope,
            limit=200,
            offset=0,
        )
        for item in candidates:
            if (
                item.evidence_snapshot.get("source") == "skill_curator_merge_recommendation"
                and item.evidence_snapshot.get("recommendation_id") == recommendation_id
            ):
                return item
        return None

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
    def _activation_surface(proposal: ReflectionProposal) -> str | None:
        if proposal.proposal_type == "skill_patch_request":
            return None
        return proposal_rollout_surface(proposal.target_scope)

    @staticmethod
    def _skill_patch_usage_event_ids(evidence_snapshot: dict[str, Any]) -> list[str]:
        usage_ids: list[str] = []
        for key in (
            "usage_event_ids",
            "matched_usage_event_ids",
            "successful_usage_event_ids",
            "negative_usage_event_ids",
            "resolver_failure_event_ids",
        ):
            for value in evidence_snapshot.get(key) or []:
                if isinstance(value, str) and value and value not in usage_ids:
                    usage_ids.append(value)
        coverage_evidence = evidence_snapshot.get("coverage_regression")
        if not isinstance(coverage_evidence, dict):
            return usage_ids
        for key in (
            "attributed_usage_event_ids_by_topic",
            "binding_gap_event_ids_by_topic",
            "unresolved_usage_event_ids_by_topic",
        ):
            value = coverage_evidence.get(key)
            if not isinstance(value, dict):
                continue
            for event_ids in value.values():
                if not isinstance(event_ids, list):
                    continue
                for event_id in event_ids:
                    if isinstance(event_id, str) and event_id and event_id not in usage_ids:
                        usage_ids.append(event_id)
        return usage_ids

    @staticmethod
    def _skill_patch_priority(metrics_snapshot: dict[str, Any]) -> float:
        negative_rate = metrics_snapshot.get("negative_usage_rate")
        if isinstance(negative_rate, (int, float)):
            return min(1.0, max(0.55, 0.6 + float(negative_rate) * 0.3))
        return 0.65

    @staticmethod
    def _skill_merge_priority(metrics_snapshot: dict[str, Any]) -> float:
        overlap_score = metrics_snapshot.get("overlap_score")
        if isinstance(overlap_score, (int, float)):
            return min(1.0, max(0.6, 0.65 + float(overlap_score) * 0.25))
        duplicate_count = metrics_snapshot.get("duplicate_artifact_count")
        if isinstance(duplicate_count, int):
            return min(1.0, max(0.6, 0.65 + duplicate_count * 0.05))
        return 0.7

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
