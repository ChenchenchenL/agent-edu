"""Skill artifact catalog service.

This module provides read-only queries for skill artifacts. It does not
perform state transitions or write audit events. All queries use bounded
limits to avoid unbounded result sets.
"""

from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillArtifact
from agent_core.domain.errors import NotFoundError
from agent_core.domain.value_objects.pagination import bounded_limit
from agent_core.infrastructure.db.repositories import SkillArtifactRepository


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
