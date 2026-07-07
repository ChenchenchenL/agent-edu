"""Candidate source implementations for the skill router.

Four sources feed the router:

1. ``ActiveArtifactCandidateSource`` -- active/stable governed artifacts
2. ``StagedArtifactCandidateSource`` -- staged artifacts (shadow/probe)
3. ``TenantExternalArtifactCandidateSource`` -- installed external packages
4. ``BaselineBuiltinCandidateSource`` -- static fallback from registry

Each source returns normalised ``SkillRouterCandidate`` objects.
Eligibility filtering (governance, suppression, compatibility) happens
inside each source, not in the router.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
from agent_core.application.services.skill.capability_catalog import resolve_capability_to_legacy
from agent_core.application.services.skill.router import (
    SkillRouterCandidate,
    SkillRouterRequest,
    TRUST_LEVELS,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.infrastructure.db.repositories import SkillArtifactRepository, SkillUsageEventRepository
from agent_core.infrastructure.db.repositories.learner import LearnerGoalRepository


class ActiveArtifactCandidateSource:
    """Collect active/stable artifacts that match the requested capability."""

    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        usage_repository: SkillUsageEventRepository,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._usage_repository = usage_repository
        self._binding_resolver = goal_skill_binding_resolver

    @property
    def source_type(self) -> str:
        return "active_artifact"

    async def collect(self, request: SkillRouterRequest) -> list[SkillRouterCandidate]:
        legacy = resolve_capability_to_legacy(
            request.capability_request.capability,
            surface=request.capability_request.surface,
        )
        if legacy is None:
            return []
        skill_name, surface = legacy

        candidates: list[SkillRouterCandidate] = []
        for status in ("stable", "active"):
            artifacts = await self._artifact_repository.list_artifacts(
                status=status,
                name=skill_name,
                scope=surface,
                limit=10,
            )
            for artifact in artifacts:
                contract = artifact.compatibility_contract
                impl_binding = str(contract.get("implementation_binding") or skill_name)
                surfaces = contract.get("surfaces")
                if not isinstance(surfaces, list) or surface not in surfaces:
                    continue
                if contract.get("dynamic_execution") is not False:
                    continue

                binding = None
                if self._binding_resolver is not None and request.learner_goal_id:
                    binding = await self._binding_resolver.get_active_binding(
                        learner_goal_id=request.learner_goal_id,
                        surface=surface,
                        topic_key=request.topic_key,
                    )

                usage_score, failure_rate, avg_confidence, correction_rate = await self._usage_signals(
                    artifact_id=artifact.id,
                    skill_name=skill_name,
                    surface=surface,
                )

                candidates.append(SkillRouterCandidate(
                    candidate_id=f"active:{artifact.id}",
                    source_type=self.source_type,
                    capability=request.capability_request.capability,
                    artifact_id=artifact.id,
                    skill_name=skill_name,
                    surface=surface,
                    implementation_binding=impl_binding,
                    artifact_status=artifact.status,
                    trust_level=TRUST_LEVELS.get(
                        f"{artifact.status}_governed",
                        TRUST_LEVELS["active_governed"],
                    ),
                    eligible=True,
                    topic_coverage=1.0,
                    surface_compatibility=1.0,
                    recent_usage_score=usage_score,
                    failure_rate=failure_rate,
                    binding_overlay=(
                        {
                            "binding_id": binding.binding_id,
                            "tool_plan": binding.tool_plan,
                            "runtime_directives": binding.runtime_directives,
                        }
                        if binding is not None
                        else None
                    ),
                    tool_plan=list(artifact.tool_plan),
                    artifact_quality=artifact.quality_score,
                    compatibility_contract=contract,
                ))
        return candidates

    async def _usage_signals(
        self,
        *,
        artifact_id: str,
        skill_name: str,
        surface: str,
    ) -> tuple[float, float, float, float]:
        events = await self._usage_repository.list_events(
            artifact_id=artifact_id,
            surface=surface,
            limit=50,
        )
        if not events:
            return 0.5, 0.0, 0.5, 0.0
        total = len(events)
        positive = sum(1 for e in events if e.outcome_status in ("completed", "partial_success"))
        negative = sum(1 for e in events if e.outcome_status in ("failed", "aborted"))
        outcome_ratio = positive / total

        correction_count = 0
        accepted_count = 0
        confidence_sum = 0.0
        confidence_count = 0
        for event in events:
            signals = event.outcome_signals or {}
            if signals.get("user_correction_requested"):
                correction_count += 1
            if signals.get("accepted_by_user"):
                accepted_count += 1
            conf = signals.get("confidence")
            if isinstance(conf, (int, float)):
                confidence_sum += float(conf)
                confidence_count += 1

        correction_rate = correction_count / total
        acceptance_rate = accepted_count / total
        avg_confidence = confidence_sum / confidence_count if confidence_count > 0 else 0.5
        failure_rate = negative / total

        usage_score = 0.6 * outcome_ratio + 0.2 * acceptance_rate + 0.2 * (1.0 - correction_rate)
        return usage_score, failure_rate, avg_confidence, correction_rate


class StagedArtifactCandidateSource:
    """Collect staged artifacts for shadow/probe participation."""

    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
    ) -> None:
        self._artifact_repository = artifact_repository

    @property
    def source_type(self) -> str:
        return "staged_artifact"

    async def collect(self, request: SkillRouterRequest) -> list[SkillRouterCandidate]:
        legacy = resolve_capability_to_legacy(
            request.capability_request.capability,
            surface=request.capability_request.surface,
        )
        if legacy is None:
            return []
        skill_name, surface = legacy

        artifacts = await self._artifact_repository.list_artifacts(
            status="staged",
            name=skill_name,
            scope=surface,
            limit=5,
        )

        candidates: list[SkillRouterCandidate] = []
        for artifact in artifacts:
            contract = artifact.compatibility_contract
            impl_binding = str(contract.get("implementation_binding") or skill_name)
            surfaces = contract.get("surfaces")
            eligible = True
            reason_codes: list[str] = []
            if not isinstance(surfaces, list) or surface not in surfaces:
                eligible = False
                reason_codes.append("surface_incompatible")
            if contract.get("dynamic_execution") is not False:
                eligible = False
                reason_codes.append("dynamic_execution_not_supported")

            match_rules = contract.get("match_rules") or contract
            topic_cov = match_rules.get("topic_coverage")
            if topic_cov is not None:
                topic_coverage = float(topic_cov)
            else:
                topic_coverage = 0.8

            candidates.append(SkillRouterCandidate(
                candidate_id=f"staged:{artifact.id}",
                source_type=self.source_type,
                capability=request.capability_request.capability,
                artifact_id=artifact.id,
                skill_name=skill_name,
                surface=surface,
                implementation_binding=impl_binding,
                artifact_status="staged",
                trust_level=TRUST_LEVELS["staged_probe"],
                eligible=eligible,
                ineligible_reason_codes=reason_codes,
                topic_coverage=topic_coverage,
                surface_compatibility=1.0 if eligible else 0.0,
                recent_usage_score=0.3,
                tool_plan=list(artifact.tool_plan),
                compatibility_contract=contract,
            ))
        return candidates


class TenantExternalArtifactCandidateSource:
    """Collect installed external artifacts from trusted sources."""

    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        installation_repository: Any | None = None,
        goal_repository: LearnerGoalRepository | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._installation_repository = installation_repository
        self._goal_repository = goal_repository

    @property
    def source_type(self) -> str:
        return "tenant_external"

    async def collect(self, request: SkillRouterRequest) -> list[SkillRouterCandidate]:
        legacy = resolve_capability_to_legacy(
            request.capability_request.capability,
            surface=request.capability_request.surface,
        )
        if legacy is None:
            return []
        skill_name, surface = legacy

        artifacts = await self._artifact_repository.list_artifacts(
            status="active",
            name=skill_name,
            scope=surface,
            limit=5,
        )

        installed_package_ids: set[str] | None = None
        if self._installation_repository is not None and request.learner_goal_id:
            profile_id = await self._resolve_profile_id(request.learner_goal_id)
            if profile_id:
                installed_package_ids = await self._installation_repository.get_installed_package_ids_for_profile(profile_id)

        candidates: list[SkillRouterCandidate] = []
        for artifact in artifacts:
            if artifact.skill_type not in ("learned", "curated"):
                continue
            contract = artifact.compatibility_contract
            impl_binding = str(contract.get("implementation_binding") or skill_name)
            surfaces = contract.get("surfaces")
            eligible = True
            reason_codes: list[str] = []
            if not isinstance(surfaces, list) or surface not in surfaces:
                eligible = False
                reason_codes.append("surface_incompatible")
            if artifact.approved_by is None:
                eligible = False
                reason_codes.append("unapproved_external")

            if installed_package_ids is not None:
                package_id = (artifact.definition or {}).get("package_id")
                if package_id and package_id not in installed_package_ids:
                    eligible = False
                    reason_codes.append("package_not_installed")

            match_rules = contract.get("match_rules") or contract
            topic_cov = match_rules.get("topic_coverage")
            if topic_cov is not None:
                topic_coverage = float(topic_cov)
            else:
                topic_coverage = 0.7

            candidates.append(SkillRouterCandidate(
                candidate_id=f"external:{artifact.id}",
                source_type=self.source_type,
                capability=request.capability_request.capability,
                artifact_id=artifact.id,
                skill_name=skill_name,
                surface=surface,
                implementation_binding=impl_binding,
                artifact_status=artifact.status,
                trust_level=TRUST_LEVELS["external_installed"],
                eligible=eligible,
                ineligible_reason_codes=reason_codes,
                topic_coverage=topic_coverage,
                surface_compatibility=1.0 if eligible else 0.0,
                recent_usage_score=0.3,
                tool_plan=list(artifact.tool_plan),
                compatibility_contract=contract,
            ))
        return candidates

    async def _resolve_profile_id(self, learner_goal_id: str) -> str | None:
        if self._goal_repository is None:
            return None
        goal = await self._goal_repository.get_by_id(learner_goal_id)
        if goal is None:
            return None
        return goal.learner_profile_id


class BaselineBuiltinCandidateSource:
    """Provide the baseline builtin fallback from the skill registry."""

    def __init__(
        self,
        *,
        skill_registry: SkillRegistry,
    ) -> None:
        self._skill_registry = skill_registry

    @property
    def source_type(self) -> str:
        return "baseline_builtin"

    async def collect(self, request: SkillRouterRequest) -> list[SkillRouterCandidate]:
        legacy = resolve_capability_to_legacy(
            request.capability_request.capability,
            surface=request.capability_request.surface,
        )
        if legacy is None:
            return []
        skill_name, surface = legacy

        if not self._skill_registry.has_skill(skill_name):
            return []

        return [SkillRouterCandidate(
            candidate_id=f"baseline:{skill_name}:{surface}",
            source_type=self.source_type,
            capability=request.capability_request.capability,
            artifact_id=None,
            skill_name=skill_name,
            surface=surface,
            implementation_binding=skill_name,
            artifact_status="baseline",
            trust_level=TRUST_LEVELS["baseline_builtin"],
            eligible=True,
            topic_coverage=0.5,
            surface_compatibility=1.0,
            mastery_fit=0.5,
            recent_usage_score=0.5,
            failure_rate=0.0,
            rollback_pressure=0.0,
        )]
