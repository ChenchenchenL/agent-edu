from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent_core.application.services.goal_skill_binding_resolver import (
    ActiveGoalSkillBinding,
    GoalSkillBindingResolver,
)
from agent_core.application.services.skill.capability import (
    CapabilityRequest,
    CapabilitySelection,
    RuntimeCapabilityExecutionPlan,
)
from agent_core.application.services.skill.capability_bridge import CapabilityRequestBridge
from agent_core.application.services.skill.capability_catalog import reverse_lookup
from agent_core.application.services.skill.router import (
    SkillRouterCandidate,
    SkillRouterDecision,
    SkillRouterRequest,
    SkillRouterService,
)
from agent_core.application.services.skill.usage import SkillUsageService
from agent_core.application.services.plan_template_selector import (
    PlanTemplateSelectionRequest,
    PlanTemplateSelectionResult,
    PlanTemplateSelector,
)
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.infrastructure.db.repositories import SkillArtifactRepository
from agent_core.infrastructure.db.repositories.learner import LearnerTopicMasteryRepository
from agent_core.infrastructure.observability.metrics import observe_skill_router_decision
import logging

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DynamicRuntimeSourceSummary:
    artifact_source: str
    directives_source: str
    tool_plan_source: str


@dataclass(frozen=True)
class RuntimeSkillExecutionPlan:
    plan: SkillExecutionPlan
    contract_summary: dict[str, Any]
    source_summary: DynamicRuntimeSourceSummary
    selected_template_id: str | None = None
    selected_template_source: str | None = None
    router_decision: object | None = None

    @property
    def resolution(self):
        return self.plan.resolution

    @property
    def execution_kind(self) -> str:
        return self.plan.execution_kind

    @property
    def runtime_directives(self) -> dict[str, Any]:
        return self.plan.runtime_directives

    @property
    def tool_plan(self) -> list[dict[str, Any]]:
        return self.plan.tool_plan

    @property
    def binding_metadata(self) -> dict[str, Any]:
        return self.plan.binding_metadata

    @property
    def implementation_binding(self) -> str:
        return self.plan.implementation_binding

    @property
    def artifact_id(self) -> str | None:
        return self.plan.artifact_id

    @property
    def artifact_status(self) -> str | None:
        return self.plan.artifact_status


class DynamicRuntimeRegistryService:
    def __init__(
        self,
        *,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None,
        skill_usage_service: SkillUsageService | None,
        router: SkillRouterService | None = None,
        template_selector: PlanTemplateSelector | None = None,
        artifact_repository: SkillArtifactRepository | None = None,
        topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
    ) -> None:
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._skill_usage_service = skill_usage_service
        self._router = router
        self._template_selector = template_selector
        self._artifact_repository = artifact_repository
        self._topic_mastery_repository = topic_mastery_repository

    async def resolve_capability_request(
        self,
        request: CapabilityRequest,
        resource_id: str,
    ) -> RuntimeCapabilityExecutionPlan | None:
        """Resolve a capability-driven runtime execution plan.

        When a ``SkillRouterService`` is configured, the router is the
        primary decision-maker.  Otherwise the legacy bridge path is
        used (Phase 1 behaviour).
        """
        if self._skill_usage_service is None:
            return None

        if self._router is not None:
            return await self._resolve_via_router(request, resource_id)

        return await self._resolve_via_legacy_bridge(request, resource_id)

    async def _resolve_via_router(
        self,
        request: CapabilityRequest,
        resource_id: str,
    ) -> RuntimeCapabilityExecutionPlan | None:
        mastery_band = None
        mastery_band_missing = False

        if self._topic_mastery_repository is not None and request.learner_goal_id and request.topic_key:
            try:
                mastery = await self._topic_mastery_repository.get_by_goal_and_topic(
                    learner_goal_id=request.learner_goal_id,
                    topic_key=request.topic_key,
                )
                if mastery is not None:
                    score = mastery.mastery_score
                    if score < 0.45:
                        mastery_band = "novice"
                    elif score < 0.75:
                        mastery_band = "developing"
                    else:
                        mastery_band = "confident"
                else:
                    mastery_band_missing = True
            except Exception:
                mastery_band_missing = True
        else:
            mastery_band_missing = True

        if mastery_band_missing:
            mastery_band = "standard"

        router_request = SkillRouterRequest(
            capability_request=request,
            resource_id=resource_id,
            learner_goal_id=request.learner_goal_id,
            topic_key=request.topic_key,
            mastery_band=mastery_band,
        )
        decision = await self._router.decide(router_request)
        if mastery_band_missing:
            decision = replace(
                decision,
                selection_reason_codes=list(decision.selection_reason_codes) + ["mastery_band_missing"]
            )
        winner = decision.winner
        if winner is None:
            return None

        template_selection = await self._select_template_for_winner(winner, request)
        tool_plan_override = template_selection.expanded_tool_plan if template_selection is not None else None

        binding = await self._resolve_binding(
            learner_goal_id=request.learner_goal_id,
            surface=winner.surface,
            topic_key=request.topic_key,
            task_type=request.task_type,
            trigger_source=request.trigger_source,
            include_staged=False,
        )

        resolution = self._build_resolution_from_winner(winner, decision)
        # Attach the selected template_id to the resolution so usage metadata captures it
        selected_template_id = (
            template_selection.selected_template.template_id
            if template_selection is not None and template_selection.selected_template is not None
            else None
        )
        if selected_template_id is not None:
            resolution = replace(resolution, template_id=selected_template_id)
        plan = await self._skill_usage_service.build_execution_plan_from_resolution(
            resolution=resolution,
            skill_binding=binding,
            tool_plan_override=tool_plan_override,
        )

        runtime_plan = self.build_runtime_plan(plan=plan, binding=binding)
        selection = self._build_selection_from_decision(
            request,
            decision,
            template_id=(
                template_selection.selected_template.template_id
                if template_selection is not None and template_selection.selected_template is not None
                else None
            ),
            template_source=(
                template_selection.template_source
                if template_selection is not None and template_selection.selected_template is not None
                else None
            ),
        )

        self._observe_decision(decision)

        template_source = (
            template_selection.template_source
            if template_selection is not None and template_selection.selected_template is not None
            else None
        )
        return RuntimeCapabilityExecutionPlan(
            plan=self.build_runtime_plan(
                plan=plan,
                binding=binding,
                selected_template_id=selection.tool_plan_template_id,
                selected_template_source=template_source,
                router_decision=decision,
            ),
            selection=selection,
            request=request,
            router_decision=decision,
        )

    async def _select_template_for_winner(
        self,
        winner: SkillRouterCandidate,
        request: CapabilityRequest,
    ) -> PlanTemplateSelectionResult | None:
        """Select and expand a plan template for the winning candidate.

        Template candidate resolution order:
        1. Artifact-provided structured plan_template_candidates
        2. Fallback: build a legacy template from the artifact's tool_plan

        Either path produces an ``expanded_tool_plan`` that overrides
        the artifact's raw tool_plan in the execution plan, completing
        the Phase-5 contract: runtime selects and fills templates rather
        than executing the raw artifact tool_plan directly.
        """
        if self._template_selector is None:
            return None
        artifact = None
        if winner.artifact_id and self._artifact_repository is not None:
            artifact = await self._artifact_repository.get_by_id(winner.artifact_id)
        if artifact is None:
            return None

        # Primary path: structured plan_template_candidates from the artifact
        candidates_data = artifact.get_plan_template_candidates()
        if candidates_data:
            candidates = self._template_selector.build_candidates_from_artifact_templates(
                plan_templates=candidates_data,
                surface=winner.surface,
            )
        else:
            candidates = []

        # Fallback path: treat the artifact's existing tool_plan as a legacy
        # template so the selector still validates and expands it.  This
        # ensures that even artifacts without explicit template metadata go
        # through policy validation before execution.
        if not candidates:
            candidates = self._template_selector.build_candidates_from_legacy_tool_plan(
                surface=winner.surface,
                tool_plan=artifact.tool_plan,
                source_artifact_id=artifact.id,
            )

        if not candidates:
            return None

        runtime_vars: dict[str, Any] = {"$learner_goal_id": request.learner_goal_id or ""}
        if request.topic_key:
            runtime_vars["$topic_focus"] = request.topic_key
        selection_result = self._template_selector.select_template(
            PlanTemplateSelectionRequest(
                surface=winner.surface,
                candidate_templates=candidates,
                runtime_variables=runtime_vars,
                resource_id=winner.artifact_id or "",
            )
        )
        if selection_result.selected_template is None:
            return None
        return selection_result

    @staticmethod
    def _build_resolution_from_winner(
        winner: SkillRouterCandidate,
        decision: SkillRouterDecision,
    ) -> SkillResolution:
        """Build SkillResolution from the router winner.

        When baseline fallback is used the resolution must carry
        ``artifact_id=None`` so that ``build_execution_plan_from_resolution``
        does not re-load a non-baseline active artifact and override the
        router's decision.  The resolver_status is set to
        ``missing_artifact`` to signal the static-fallback path.
        """
        # Build winner_candidate summary for explainability (operator-facing, no internals)
        winner_candidate: dict[str, Any] = {
            "candidate_id": winner.candidate_id,
            "source_type": winner.source_type,
            "skill_name": winner.skill_name,
            "artifact_id": winner.artifact_id,
            "artifact_status": winner.artifact_status,
            "total_score": winner.total_score,
            "trust_level": winner.trust_level,
            "eligible": winner.eligible,
            "reason_codes": list(winner.reason_codes or []),
        }
        # Loser reason summary: maps each non-winner candidate_id -> rejection codes
        loser_reason_summary: dict[str, Any] = dict(decision.loser_reason_map)

        if decision.baseline_used:
            # Force no artifact so the execution layer truly walks the
            # registry-provided static baseline, not any active artifact.
            return SkillResolution.build(
                skill_name=winner.skill_name,
                surface=winner.surface,
                artifact_id=None,
                skill_version=None,
                artifact_status="baseline",
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
                implementation_binding=winner.implementation_binding,
                winner_candidate=winner_candidate,
                loser_reason_summary=loser_reason_summary,
                confidence=decision.confidence,
                fallback_chain=list(decision.fallback_chain or []),
            )
        return SkillResolution.build(
            skill_name=winner.skill_name,
            surface=winner.surface,
            artifact_id=winner.artifact_id,
            skill_version=None,
            artifact_status=winner.artifact_status,
            resolver_status="resolved",
            selection_reason="production_default",
            implementation_binding=winner.implementation_binding,
            winner_candidate=winner_candidate,
            loser_reason_summary=loser_reason_summary,
            confidence=decision.confidence,
            fallback_chain=list(decision.fallback_chain or []),
        )

    async def _resolve_via_legacy_bridge(
        self,
        request: CapabilityRequest,
        resource_id: str,
    ) -> RuntimeCapabilityExecutionPlan | None:
        legacy_inputs = CapabilityRequestBridge.to_legacy_inputs(request)
        if legacy_inputs is None:
            return None

        binding = await self._resolve_binding(
            learner_goal_id=request.learner_goal_id,
            surface=legacy_inputs["surface"],
            topic_key=request.topic_key,
            task_type=request.task_type,
            trigger_source=request.trigger_source,
            include_staged=False,
        )

        plan = await self._skill_usage_service.resolve_execution_plan(
            skill_name=legacy_inputs["skill_name"],
            surface=legacy_inputs["surface"],
            resource_id=resource_id,
            skill_binding=binding,
        )

        runtime_plan = self.build_runtime_plan(plan=plan, binding=binding)
        selection = CapabilityRequestBridge.build_selection(
            request,
            artifact_id=plan.artifact_id,
            resolver_status=plan.resolver_status,
            selection_reason=plan.selection_reason,
            tool_plan=plan.tool_plan,
            binding_applied=binding is not None,
        )

        return RuntimeCapabilityExecutionPlan(
            plan=runtime_plan,
            selection=selection,
            request=request,
        )

    @staticmethod
    def _build_selection_from_decision(
        request: CapabilityRequest,
        decision: SkillRouterDecision,
        *,
        template_id: str | None = None,
        template_source: str | None = None,
    ) -> CapabilitySelection:
        winner = decision.winner
        return CapabilitySelection(
            requested_capability=request.capability,
            selected_artifact_id=winner.artifact_id if winner else None,
            selected_capability=winner.skill_name if winner else request.capability,
            reason_codes=list(decision.selection_reason_codes),
            fallback_chain=list(decision.fallback_chain),
            confidence=decision.confidence,
            tool_plan_template_id=template_id,
            legacy_skill_name=winner.skill_name if winner else None,
            bridge_version="router_v2",
            resolution_mode=decision.routing_mode,
        )

    @staticmethod
    def _observe_decision(decision: SkillRouterDecision) -> None:
        winner_source = decision.winner.source_type if decision.winner else "none"
        rejection_reasons: list[str] = []
        for reasons in decision.loser_reason_map.values():
            rejection_reasons.extend(reasons)
        observe_skill_router_decision(
            capability=decision.winner.capability if decision.winner else "unknown",
            surface=decision.winner.surface if decision.winner else "unknown",
            winner_source=winner_source,
            candidate_count=len(decision.ranked_candidates),
            baseline_used=decision.baseline_used,
            fallback_reasons=decision.fallback_chain,
            rejection_reasons=rejection_reasons,
        )

    async def resolve_runtime_plan(
        self,
        *,
        learner_goal_id: str | None,
        skill_name: str,
        surface: str,
        resource_id: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> RuntimeSkillExecutionPlan | None:
        """Compatibility bridge -- constructs a CapabilityRequest internally.

        Callers that can express their intent as a capability should
        migrate to ``resolve_capability_request``.
        """
        capability = reverse_lookup(skill_name, surface)
        if capability is not None:
            request = CapabilityRequest(
                capability=capability,
                surface=surface,
                learner_goal_id=learner_goal_id,
                topic_key=topic_key,
                task_type=task_type,
                trigger_source=trigger_source,
            )
            result = await self.resolve_capability_request(request, resource_id=resource_id)
            if result is not None:
                return result.plan

        if self._skill_usage_service is None:
            return None
        binding = await self._resolve_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )
        plan = await self._skill_usage_service.resolve_execution_plan(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            skill_binding=binding,
        )
        return self.build_runtime_plan(plan=plan, binding=binding)

    @classmethod
    def build_runtime_plan(
        cls,
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
        selected_template_id: str | None = None,
        selected_template_source: str | None = None,
        router_decision: object | None = None,
    ) -> RuntimeSkillExecutionPlan:
        return RuntimeSkillExecutionPlan(
            plan=plan,
            contract_summary=cls._contract_summary(plan=plan, binding=binding),
            source_summary=cls._source_summary(plan=plan, binding=binding),
            selected_template_id=selected_template_id,
            selected_template_source=selected_template_source,
            router_decision=router_decision,
        )

    @staticmethod
    def runtime_metadata_for_usage(
        runtime_plan: RuntimeSkillExecutionPlan | None,
        *,
        base_metadata: dict[str, object] | None = None,
        capability_selection: CapabilitySelection | None = None,
    ) -> dict[str, object]:
        metadata = dict(base_metadata or {})
        if runtime_plan is None:
            return metadata
        metadata.update(runtime_plan.binding_metadata)
        metadata.update(runtime_plan.contract_summary)
        metadata["source_summary"] = {
            "artifact_source": runtime_plan.source_summary.artifact_source,
            "directives_source": runtime_plan.source_summary.directives_source,
            "tool_plan_source": runtime_plan.source_summary.tool_plan_source,
        }
        if runtime_plan.selected_template_id is not None:
            metadata["selected_template_id"] = runtime_plan.selected_template_id
        if runtime_plan.selected_template_source is not None:
            metadata["selected_template_source"] = runtime_plan.selected_template_source
        if capability_selection is not None:
            metadata["capability"] = {
                "requested_capability": capability_selection.requested_capability,
                "selected_capability": capability_selection.selected_capability,
                "bridge_version": capability_selection.bridge_version,
                "resolution_mode": capability_selection.resolution_mode,
                "reason_codes": capability_selection.reason_codes,
            }
        return metadata

    @staticmethod
    def usage_metadata_for_plan(
        *,
        execution_plan: SkillExecutionPlan | None,
        runtime_plan: RuntimeSkillExecutionPlan | None,
        base_metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if runtime_plan is not None:
            return DynamicRuntimeRegistryService.runtime_metadata_for_usage(
                runtime_plan,
                base_metadata=base_metadata,
            )
        metadata = dict(base_metadata or {})
        if execution_plan is None:
            return metadata
        metadata.update(execution_plan.binding_metadata)
        metadata["implementation_binding"] = execution_plan.implementation_binding
        metadata["execution_kind"] = execution_plan.execution_kind
        return metadata

    async def _resolve_binding(
        self,
        *,
        learner_goal_id: str | None,
        surface: str,
        topic_key: str | None,
        task_type: str | None,
        trigger_source: str | None,
        include_staged: bool,
    ) -> ActiveGoalSkillBinding | None:
        if self._goal_skill_binding_resolver is None or learner_goal_id is None:
            return None
        return await self._goal_skill_binding_resolver.get_active_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    @staticmethod
    def _contract_summary(
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
    ) -> dict[str, Any]:
        rollout = plan.binding_metadata.get("skill_package_rollout")
        rollout_id = None
        binding_id = None
        if isinstance(rollout, dict):
            rollout_id = rollout.get("rollout_id")
            binding_id = rollout.get("binding_id")
        return {
            "implementation_binding": plan.implementation_binding,
            "execution_kind": plan.execution_kind,
            "artifact_id": plan.artifact_id,
            "artifact_status": plan.artifact_status,
            "binding_id": binding_id or (binding.binding_id if binding is not None else None),
            "rollout_id": rollout_id or (binding.rollout_id if binding is not None else None),
            "tool_plan_enabled": bool(plan.tool_plan),
            "dynamic_registry_version": "v1",
        }

    @staticmethod
    def _source_summary(
        *,
        plan: SkillExecutionPlan,
        binding: ActiveGoalSkillBinding | None,
    ) -> DynamicRuntimeSourceSummary:
        has_artifact = plan.artifact_id is not None
        has_binding = binding is not None
        artifact_source = "binding_overlay" if has_binding else "artifact"
        if not has_artifact:
            artifact_source = "static_fallback"
        directives_source = "binding_overlay" if has_binding and binding.runtime_directives else "artifact"
        if not plan.runtime_directives:
            directives_source = "none"
        tool_plan_source = "binding_overlay" if has_binding and binding.tool_plan else "artifact"
        if not plan.tool_plan:
            tool_plan_source = "none"
        return DynamicRuntimeSourceSummary(
            artifact_source=artifact_source,
            directives_source=directives_source,
            tool_plan_source=tool_plan_source,
        )
