"""Skill service cross-service protocols.

This module defines Protocol types used for cross-service contracts
within the skill service subsystem. These protocols allow loose
coupling between services while maintaining type safety.
"""

from __future__ import annotations

from typing import Any, Protocol

from agent_core.domain.entities.reflection_closure import ReflectionProposal


class SkillPatchProposalService(Protocol):
    async def get(self, proposal_id: str) -> ReflectionProposal:
        ...

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
        ...

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
        ...
