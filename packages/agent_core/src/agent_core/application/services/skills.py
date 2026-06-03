from __future__ import annotations

from hashlib import sha256
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillResolution, SkillUsageEvent
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    ReflectionProposalRepository,
    SkillArtifactRepository,
    SkillUsageEventRepository,
)


ALLOWED_SKILL_PACKAGE_TOOLS = {"review_scheduling", "assessment_generation", "partial_replan"}
CANDIDATE_MIN_SCORE_DELTA = 0.1


class SkillCatalogService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
        skill_registry: SkillRegistry,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service
        self._skill_registry = skill_registry

    async def list_artifacts(
        self,
        *,
        status: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        lineage_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillArtifact]:
        return await self._artifact_repository.list_artifacts(
            status=status,
            name=name,
            scope=scope,
            lineage_id=lineage_id,
            limit=bounded_limit(limit),
        )

    async def get_artifact(self, artifact_id: str) -> SkillArtifact:
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        return artifact

    async def list_lineage(self, artifact_id: str, *, limit: int = 50) -> list[SkillArtifact]:
        artifact = await self.get_artifact(artifact_id)
        return await self._artifact_repository.list_by_lineage(
            artifact.lineage_id,
            limit=bounded_limit(limit),
        )


class SkillCandidateService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        audit_service: AuditService,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._audit_service = audit_service

    async def create_candidate_from_proposal(
        self,
        *,
        proposal_id: str,
        operator_id: str,
    ) -> SkillArtifact:
        existing = await self._artifact_repository.get_by_source_proposal_id(proposal_id)
        if existing is not None:
            await self._audit_candidate(
                existing,
                event_type="skill.artifact.candidate_reused",
                operator_id=operator_id,
            )
            return existing

        proposal = await self._proposal_repository.get_by_id(proposal_id)
        if proposal is None:
            raise NotFoundError(f"Reflection proposal '{proposal_id}' was not found.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal_id)
        self._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = self._validated_payload(proposal)
        skill_name = str(payload["skill_name"])
        surface = str(payload["surface"])
        artifact = SkillArtifact.build(
            name=skill_name,
            version=await self._next_candidate_version(skill_name),
            skill_type="learned",
            scope=surface,
            status="candidate",
            description=proposal.change_summary,
            definition={
                "artifact_kind": payload["artifact_kind"],
                "hypothesis": proposal.hypothesis,
                "change_summary": proposal.change_summary,
                "expected_improvement": proposal.expected_improvement,
                "match_rules": dict(payload["match_rules"]),
                "scoring_contract": dict(payload["scoring_contract"]),
                "source_proposal": {
                    "id": proposal.id,
                    "risk_level": proposal.risk_level,
                    "evaluation_status": evaluation.evaluation_status if evaluation else None,
                    "score_delta": evaluation.score_delta if evaluation else None,
                    "sandbox_run_id": evaluation.sandbox_run_id if evaluation else None,
                },
            },
            runtime_directives=dict(payload["runtime_directives"]),
            tool_plan=[dict(item) for item in payload["tool_plan"]],
            compatibility_contract={
                "surfaces": [surface],
                "implementation_binding": skill_name,
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=[proposal.reflection_record_id],
            source_memory_ids=self._source_memory_ids(proposal.evidence_snapshot),
            source_proposal_id=proposal.id,
            quality_score=self._quality_score(evaluation.score_delta if evaluation else 0.0),
            created_by=operator_id,
        )
        await self._artifact_repository.create(artifact)
        await self._audit_candidate(artifact, event_type="skill.artifact.candidate_created", operator_id=operator_id)
        return artifact

    @staticmethod
    def _validate_candidate_source(
        *,
        proposal: ReflectionProposal,
        evaluation: ReflectionProposalEvaluation | None,
    ) -> None:
        if proposal.proposal_type != "skill_package":
            raise ValidationError("Only skill_package proposals can create skill candidates.")
        if proposal.status != "approved":
            raise ValidationError("Only approved skill_package proposals can create skill candidates.")
        if evaluation is None or evaluation.evaluation_status != "effective":
            raise ValidationError("Skill candidate creation requires an effective evaluation.")
        if evaluation.score_delta is None or evaluation.score_delta < CANDIDATE_MIN_SCORE_DELTA:
            raise ValidationError("Skill candidate creation requires sufficient evaluation score_delta.")

    @staticmethod
    def _validated_payload(proposal: ReflectionProposal) -> dict[str, object]:
        payload = dict(proposal.structured_patch_payload)
        if payload.get("artifact_kind") != "declarative_skill_package":
            raise ValidationError("Unsupported skill package artifact_kind.")
        skill_name = payload.get("skill_name")
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise ValidationError("Skill package skill_name is required.")
        surface = payload.get("surface")
        if surface != proposal.target_scope:
            raise ValidationError("Skill package surface must match proposal target scope.")
        for key in ("match_rules", "runtime_directives", "scoring_contract"):
            if not isinstance(payload.get(key), dict):
                raise ValidationError(f"Skill package {key} must be an object.")
        tool_plan = payload.get("tool_plan")
        if not isinstance(tool_plan, list):
            raise ValidationError("Skill package tool_plan must be a list.")
        for item in tool_plan:
            if not isinstance(item, dict):
                raise ValidationError("Skill package tool_plan items must be objects.")
            tool_name = item.get("tool_name")
            if tool_name not in ALLOWED_SKILL_PACKAGE_TOOLS:
                raise ValidationError("Unsupported skill package tool.")
        return {
            "artifact_kind": payload["artifact_kind"],
            "skill_name": skill_name.strip(),
            "surface": str(surface),
            "match_rules": dict(payload["match_rules"]),
            "runtime_directives": dict(payload["runtime_directives"]),
            "tool_plan": [dict(item) for item in tool_plan],
            "scoring_contract": dict(payload["scoring_contract"]),
        }

    async def _next_candidate_version(self, name: str) -> str:
        max_patch = await self._artifact_repository.max_candidate_patch_version(name)
        return f"0.1.{max_patch + 1}"

    @staticmethod
    def _source_memory_ids(evidence_snapshot: dict[str, Any]) -> list[str]:
        items = list((evidence_snapshot.get("memory_corpus") or {}).get("items") or [])
        memory_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            memory_id = item.get("memory_id")
            if isinstance(memory_id, str) and memory_id and memory_id not in memory_ids:
                memory_ids.append(memory_id)
        return memory_ids

    @staticmethod
    def _quality_score(score_delta: float) -> float:
        return min(1.0, max(0.0, 0.5 + score_delta))

    async def _audit_candidate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str | None = None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id or "system",
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "source_reflection_ids": artifact.source_reflection_ids,
                "source_memory_ids": artifact.source_memory_ids,
                "quality_score": artifact.quality_score,
                "operator_id": operator_id,
            },
        )


class SkillArtifactLifecycleService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        proposal_repository: ReflectionProposalRepository,
        evaluation_repository: ReflectionProposalEvaluationRepository,
        rollout_repository: ReflectionProposalRolloutRepository,
        rollout_observation_repository: ReflectionProposalRolloutObservationRepository,
        goal_skill_binding_repository: GoalSkillBindingRepository,
        usage_repository: SkillUsageEventRepository,
        skill_registry: SkillRegistry,
        audit_service: AuditService,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._proposal_repository = proposal_repository
        self._evaluation_repository = evaluation_repository
        self._rollout_repository = rollout_repository
        self._rollout_observation_repository = rollout_observation_repository
        self._goal_skill_binding_repository = goal_skill_binding_repository
        self._usage_repository = usage_repository
        self._skill_registry = skill_registry
        self._audit_service = audit_service

    async def stage_candidate(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")

        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == "staged":
            await self._audit_stage(
                artifact,
                event_type="skill.artifact.stage_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                evaluation_id=None,
                score_delta=None,
            )
            return artifact
        if artifact.status != "candidate":
            raise ValidationError("Only candidate skill artifacts can be staged.")
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact staging requires a source proposal.")

        proposal = await self._proposal_repository.get_by_id(artifact.source_proposal_id)
        if proposal is None:
            raise ValidationError("Skill artifact staging requires an existing source proposal.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = SkillCandidateService._validated_payload(proposal)
        self._validate_artifact_against_source(artifact, payload)

        staged = artifact.mark_staged()
        await self._artifact_repository.update(staged)
        await self._audit_stage(
            staged,
            event_type="skill.artifact.staged",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            evaluation_id=evaluation.id if evaluation else None,
            score_delta=evaluation.score_delta if evaluation else None,
        )
        return staged

    async def activate_staged(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")

        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == "active":
            await self._audit_activate(
                artifact,
                event_type="skill.artifact.activate_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
                evaluation_id=None,
                score_delta=None,
                rollout_id=None,
                binding_id=None,
                observation_id=None,
                usage_event_ids=[],
            )
            return artifact
        if artifact.status != "staged":
            raise ValidationError("Only staged skill artifacts can be activated.")
        if not self._skill_registry.has_skill(artifact.name):
            raise ValidationError("Skill artifact activation requires an enabled skill name.")

        existing_selectable = await self._artifact_repository.get_selectable_by_name_scope(
            name=artifact.name,
            scope=artifact.scope,
        )
        if existing_selectable is not None and existing_selectable.id != artifact.id:
            raise ValidationError("A selectable skill artifact already exists for this name and scope.")
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact activation requires a source proposal.")

        proposal = await self._proposal_repository.get_by_id(artifact.source_proposal_id)
        if proposal is None:
            raise ValidationError("Skill artifact activation requires an existing source proposal.")
        evaluation = await self._evaluation_repository.get_by_proposal(proposal.id)
        SkillCandidateService._validate_candidate_source(
            proposal=proposal,
            evaluation=evaluation,
        )
        payload = SkillCandidateService._validated_payload(proposal)
        self._validate_artifact_against_source(artifact, payload)
        rollout, binding, observation = await self._validate_activation_rollout_evidence(artifact)
        usage_events = await self._activation_usage_events(
            artifact=artifact,
            proposal_id=proposal.id,
            rollout_id=rollout.id,
            binding_id=binding.id,
            learner_goal_id=rollout.learner_goal_id,
            activated_at=rollout.activated_at,
        )
        if not usage_events:
            raise ValidationError("Skill artifact activation requires successful attributed rollout usage.")

        activated = artifact.mark_active(operator_id=operator_id)
        await self._artifact_repository.update(activated)
        await self._audit_activate(
            activated,
            event_type="skill.artifact.activated",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
            evaluation_id=evaluation.id if evaluation else None,
            score_delta=evaluation.score_delta if evaluation else None,
            rollout_id=rollout.id,
            binding_id=binding.id,
            observation_id=observation.id,
            usage_event_ids=[item.id for item in usage_events],
        )
        return activated

    async def deactivate_active(
        self,
        *,
        artifact_id: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> SkillArtifact:
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")

        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            raise NotFoundError(f"Skill artifact '{artifact_id}' was not found.")
        if artifact.status == "deprecated":
            await self._audit_deactivate(
                artifact,
                event_type="skill.artifact.deactivate_reused",
                operator_id=operator_id,
                reason_code=reason_code,
                reason_note=reason_note,
            )
            return artifact
        if artifact.status != "active":
            raise ValidationError("Only active skill artifacts can be deactivated.")

        deactivated = artifact.mark_deprecated()
        await self._artifact_repository.update(deactivated)
        await self._audit_deactivate(
            deactivated,
            event_type="skill.artifact.deactivated",
            operator_id=operator_id,
            reason_code=reason_code,
            reason_note=reason_note,
        )
        return deactivated

    @staticmethod
    def _validate_artifact_against_source(artifact: SkillArtifact, payload: dict[str, object]) -> None:
        if not artifact.source_reflection_ids:
            raise ValidationError("Skill artifact staging requires source reflections.")
        if artifact.name != payload["skill_name"] or artifact.scope != payload["surface"]:
            raise ValidationError("Skill artifact does not match its source proposal.")
        if artifact.runtime_directives != payload["runtime_directives"]:
            raise ValidationError("Skill artifact runtime_directives do not match its source proposal.")
        if artifact.tool_plan != payload["tool_plan"]:
            raise ValidationError("Skill artifact tool_plan does not match its source proposal.")
        if artifact.definition.get("match_rules") != payload["match_rules"]:
            raise ValidationError("Skill artifact match_rules do not match its source proposal.")
        if artifact.definition.get("scoring_contract") != payload["scoring_contract"]:
            raise ValidationError("Skill artifact scoring_contract does not match its source proposal.")

        contract = artifact.compatibility_contract
        surfaces = contract.get("surfaces")
        if contract.get("dynamic_execution") is not False:
            raise ValidationError("Skill artifact staging requires static compatibility contract execution.")
        if not isinstance(surfaces, list) or not all(isinstance(item, str) for item in surfaces):
            raise ValidationError("Skill artifact compatibility contract surfaces are invalid.")
        if surfaces != [artifact.scope]:
            raise ValidationError("In V2, artifact surfaces must exactly match artifact scope.")
        if contract.get("implementation_binding") != artifact.name:
            raise ValidationError("Skill artifact implementation binding must match artifact name.")

    async def _validate_activation_rollout_evidence(
        self,
        artifact: SkillArtifact,
    ) -> tuple[ReflectionProposalRollout, GoalSkillBinding, ReflectionProposalRolloutObservation]:
        if artifact.source_proposal_id is None:
            raise ValidationError("Skill artifact activation requires a source proposal.")
        rollout = await self._rollout_repository.get_by_proposal(artifact.source_proposal_id)
        if rollout is None:
            raise ValidationError("Skill artifact activation requires rollout evidence.")
        if rollout.status != "rolled_out":
            raise ValidationError("Skill artifact activation requires a promoted rollout.")
        if rollout.surface != artifact.scope:
            raise ValidationError("Skill artifact rollout surface does not match artifact scope.")
        binding = await self._goal_skill_binding_repository.get_by_rollout(rollout.id)
        if binding is None:
            raise ValidationError("Skill artifact activation requires a rollout skill binding.")
        if binding.status != "rolled_out":
            raise ValidationError("Skill artifact activation requires a promoted skill binding.")
        if (
            binding.proposal_id != artifact.source_proposal_id
            or binding.rollout_id != rollout.id
            or binding.surface != artifact.scope
        ):
            raise ValidationError("Skill artifact activation rollout binding does not match artifact.")
        if rollout.latest_observation_id is None:
            raise ValidationError("Skill artifact activation requires rollout observation evidence.")
        observation = await self._rollout_observation_repository.get_by_id(rollout.latest_observation_id)
        if observation is None:
            raise ValidationError("Skill artifact activation requires existing rollout observation evidence.")
        if (
            observation.rollout_id != rollout.id
            or observation.proposal_id != artifact.source_proposal_id
            or observation.surface != artifact.scope
        ):
            raise ValidationError("Skill artifact activation observation does not match rollout.")
        if observation.recommendation != "promote":
            raise ValidationError("Skill artifact activation requires promote rollout observation.")
        return rollout, binding, observation

    async def _activation_usage_events(
        self,
        *,
        artifact: SkillArtifact,
        proposal_id: str,
        rollout_id: str,
        binding_id: str,
        learner_goal_id: str,
        activated_at,
    ) -> list[SkillUsageEvent]:
        events = await self._usage_repository.list_events(
            skill_name=artifact.name,
            learner_goal_id=learner_goal_id,
            surface=artifact.scope,
            created_at_from=activated_at,
            limit=200,
        )
        matching: list[SkillUsageEvent] = []
        for event in events:
            if event.skill_name != artifact.name or event.surface != artifact.scope:
                continue
            if event.outcome_status not in {"completed", "partial_success"}:
                continue
            rollout_metadata = event.metadata.get("skill_package_rollout")
            if not isinstance(rollout_metadata, dict):
                continue
            if (
                rollout_metadata.get("proposal_id") == proposal_id
                and rollout_metadata.get("rollout_id") == rollout_id
                and rollout_metadata.get("binding_id") == binding_id
                and rollout_metadata.get("skill_name") == artifact.name
                and rollout_metadata.get("surface") == artifact.scope
            ):
                matching.append(event)
        return matching

    async def _audit_stage(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        evaluation_id: str | None,
        score_delta: float | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "evaluation_id": evaluation_id,
                "score_delta": score_delta,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_activate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
        evaluation_id: str | None,
        score_delta: float | None,
        rollout_id: str | None,
        binding_id: str | None,
        observation_id: str | None,
        usage_event_ids: list[str],
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "evaluation_id": evaluation_id,
                "score_delta": score_delta,
                "rollout_id": rollout_id,
                "binding_id": binding_id,
                "observation_id": observation_id,
                "usage_event_ids": list(usage_event_ids),
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )

    async def _audit_deactivate(
        self,
        artifact: SkillArtifact,
        *,
        event_type: str,
        operator_id: str,
        reason_code: str,
        reason_note: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_artifact",
            resource_id=artifact.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "skill_name": artifact.name,
                "version": artifact.version,
                "scope": artifact.scope,
                "status": artifact.status,
                "source_proposal_id": artifact.source_proposal_id,
                "operator_id": operator_id,
                "reason_code": reason_code,
                "reason_note": reason_note,
            },
        )


class SkillResolver:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
        skill_registry: SkillRegistry,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service
        self._skill_registry = skill_registry

    async def resolve(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
        audit: bool = True,
    ) -> SkillResolution:
        if not self._skill_registry.has_skill(skill_name):
            raise ValidationError(f"Skill '{skill_name}' is not enabled.")
        suppressed = await self._artifact_repository.get_suppressed_by_name_scope(name=skill_name, scope=surface)
        if suppressed is not None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=suppressed.id,
                skill_version=suppressed.version,
                artifact_status=suppressed.status,
                resolver_status="blocked",
                selection_reason="suppressed_artifact",
                implementation_binding=skill_name,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.blocked",
                    resource_id=resource_id,
                )
            return resolution
        artifact = await self._artifact_repository.get_selectable_by_name_scope(name=skill_name, scope=surface)
        if artifact is None:
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=None,
                skill_version=None,
                artifact_status=None,
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
                implementation_binding=skill_name,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.missing_artifact",
                    resource_id=resource_id,
                )
            return resolution
        implementation_binding = str(artifact.compatibility_contract.get("implementation_binding") or "")
        surfaces = artifact.compatibility_contract.get("surfaces")
        if (
            artifact.compatibility_contract.get("dynamic_execution") is not False
            or implementation_binding != skill_name
            or not isinstance(surfaces, list)
            or surfaces != [surface]
        ):
            resolution = SkillResolution.build(
                skill_name=skill_name,
                surface=surface,
                artifact_id=artifact.id,
                skill_version=artifact.version,
                artifact_status=artifact.status,
                resolver_status="incompatible",
                selection_reason="contract_incompatible",
                implementation_binding=implementation_binding or skill_name,
            )
            if audit:
                await self._audit_resolution(
                    resolution,
                    event_type="skill.resolution.incompatible",
                    resource_id=resource_id,
                )
            return resolution
        return SkillResolution.build(
            skill_name=skill_name,
            surface=surface,
            artifact_id=artifact.id,
            skill_version=artifact.version,
            artifact_status=artifact.status,
            resolver_status="resolved",
            selection_reason="production_default",
            implementation_binding=implementation_binding,
        )

    async def _audit_resolution(
        self,
        resolution: SkillResolution,
        *,
        event_type: str,
        resource_id: str | None,
    ) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill",
            resource_id=resource_id or resolution.artifact_id,
            actor="system",
            event_data={
                "skill_name": resolution.skill_name,
                "surface": resolution.surface,
                "artifact_id": resolution.artifact_id,
                "skill_version": resolution.skill_version,
                "artifact_status": resolution.artifact_status,
                "resolver_status": resolution.resolver_status,
                "selection_reason": resolution.selection_reason,
                "implementation_binding": resolution.implementation_binding,
            },
        )


class SkillUsageService:
    def __init__(
        self,
        *,
        usage_repository: SkillUsageEventRepository,
        skill_resolver: SkillResolver,
        audit_service: AuditService,
    ) -> None:
        self._usage_repository = usage_repository
        self._skill_resolver = skill_resolver
        self._audit_service = audit_service

    async def resolve_for_runtime(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str | None = None,
    ) -> SkillResolution:
        resolution = await self._skill_resolver.resolve(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )
        if resolution.resolver_status in {"blocked", "incompatible"}:
            raise ValidationError(f"Skill resolution is {resolution.resolver_status}.")
        return resolution

    async def record_usage(
        self,
        *,
        skill_name: str,
        surface: str,
        outcome_status: str,
        resolution: SkillResolution | None = None,
        learner_profile_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        daily_task_id: str | None = None,
        workflow_run_id: str | None = None,
        topic_key: str | None = None,
        trigger_source: str | None = None,
        latency_ms: int | None = None,
        cost_units: float | None = None,
        input_summary: str | None = None,
        input_fingerprint: str | None = None,
        output_summary: str | None = None,
        output_fingerprint: str | None = None,
        error_code: str | None = None,
        outcome_signals: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SkillUsageEvent | None:
        resolution_error_code: str | None = None
        if resolution is None:
            try:
                resolution = await self._skill_resolver.resolve(
                    skill_name=skill_name,
                    surface=surface,
                    resource_id=session_id or daily_task_id or workflow_run_id,
                )
            except ValidationError:
                resolution = SkillResolution.build(
                    skill_name=skill_name,
                    surface=surface,
                    artifact_id=None,
                    skill_version=None,
                    artifact_status=None,
                    resolver_status="blocked",
                    selection_reason="runtime_resolution_failed",
                    implementation_binding=skill_name,
                )
                resolution_error_code = "SkillResolutionValidationError"
        elif resolution.skill_name != skill_name or resolution.surface != surface:
            raise ValidationError("Skill resolution does not match usage context.")
        event = SkillUsageEvent.build(
            skill_artifact_id=resolution.artifact_id,
            skill_name=resolution.skill_name,
            skill_version=resolution.skill_version,
            skill_status_at_use=resolution.artifact_status,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            daily_task_id=daily_task_id,
            workflow_run_id=workflow_run_id,
            surface=surface,
            topic_key=topic_key,
            trigger_source=trigger_source,
            outcome_status=outcome_status,
            latency_ms=latency_ms,
            cost_units=cost_units,
            input_summary=self._truncate(input_summary),
            input_fingerprint=input_fingerprint or self._fingerprint(input_summary),
            output_summary=self._truncate(output_summary),
            output_fingerprint=output_fingerprint or self._fingerprint(output_summary),
            error_code=error_code or resolution_error_code,
            resolver_status=resolution.resolver_status,
            selection_reason=resolution.selection_reason,
            outcome_signals=outcome_signals,
            metadata=metadata,
        )
        try:
            await self._persist_usage_event(event)
            return event
        except Exception as exc:
            await self._audit_service.record_durable(
                event_type="skill.usage.record_failed",
                resource_type="skill",
                resource_id=event.skill_artifact_id,
                actor="system",
                event_data={
                    "skill_name": event.skill_name,
                    "skill_version": event.skill_version,
                    "skill_status_at_use": event.skill_status_at_use,
                    "surface": event.surface,
                    "outcome_status": event.outcome_status,
                    "resolver_status": event.resolver_status,
                    "selection_reason": event.selection_reason,
                    "learner_profile_id": event.learner_profile_id,
                    "learner_goal_id": event.learner_goal_id,
                    "session_id": event.session_id,
                    "daily_task_id": event.daily_task_id,
                    "workflow_run_id": event.workflow_run_id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            return None

    async def _persist_usage_event(self, event: SkillUsageEvent) -> None:
        await self._usage_repository.create(event)
        await self._audit_service.record(
            event_type="skill.usage.recorded",
            resource_type="skill",
            resource_id=event.skill_artifact_id,
            actor="system",
            event_data={
                "usage_event_id": event.id,
                "skill_name": event.skill_name,
                "skill_version": event.skill_version,
                "skill_status_at_use": event.skill_status_at_use,
                "surface": event.surface,
                "outcome_status": event.outcome_status,
                "resolver_status": event.resolver_status,
                "selection_reason": event.selection_reason,
                "learner_profile_id": event.learner_profile_id,
                "learner_goal_id": event.learner_goal_id,
                "session_id": event.session_id,
                "daily_task_id": event.daily_task_id,
                "workflow_run_id": event.workflow_run_id,
            },
        )

    async def list_usage_by_artifact(self, artifact_id: str, *, limit: int = 50) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_by_artifact(artifact_id, limit=bounded_limit(limit))

    async def list_usage(
        self,
        *,
        artifact_id: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        surface: str | None = None,
        outcome_status: str | None = None,
        resolver_status: str | None = None,
        limit: int = 50,
    ) -> list[SkillUsageEvent]:
        return await self._usage_repository.list_events(
            artifact_id=artifact_id,
            learner_goal_id=learner_goal_id,
            session_id=session_id,
            surface=surface,
            outcome_status=outcome_status,
            resolver_status=resolver_status,
            limit=bounded_limit(limit),
        )

    @staticmethod
    def _truncate(value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if len(stripped) <= 500:
            return stripped
        return stripped[:497] + "..."

    @staticmethod
    def _fingerprint(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        if not normalized:
            return sha256(b"").hexdigest()
        return sha256(normalized.encode("utf-8")).hexdigest()
