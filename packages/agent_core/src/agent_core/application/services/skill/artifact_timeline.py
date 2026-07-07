from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.infrastructure.db.repositories.audit import AuditRepository
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository, SkillCuratorRecommendationRepository, SkillUsageEventRepository


@dataclass(frozen=True)
class ArtifactTimeline:
    artifact_id: str
    artifact_summary: dict[str, Any]
    lifecycle_events: list[dict[str, Any]]
    usage_summary: dict[str, Any]
    quality_history: list[dict[str, Any]]
    related_proposal_ids: list[str]
    suppression_history: list[dict[str, Any]]
    recommendation_history: list[dict[str, Any]]


class SkillArtifactTimelineService:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        audit_repository: AuditRepository,
        usage_repository: SkillUsageEventRepository,
        recommendation_repository: SkillCuratorRecommendationRepository,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._audit_repository = audit_repository
        self._usage_repository = usage_repository
        self._recommendation_repository = recommendation_repository

    async def build_timeline(self, artifact_id: str) -> ArtifactTimeline:
        artifact = await self._artifact_repository.get_by_id(artifact_id)
        if artifact is None:
            from agent_core.domain.errors import NotFoundError
            raise NotFoundError(f"Skill artifact not found: {artifact_id}")

        artifact_summary = {
            "id": artifact.id,
            "name": artifact.name,
            "version": artifact.version,
            "status": artifact.status,
            "skill_type": artifact.skill_type,
            "scope": artifact.scope,
            "quality_score": artifact.quality_score,
            "lineage_id": artifact.lineage_id,
            "parent_artifact_id": artifact.parent_artifact_id,
            "supersedes_artifact_id": artifact.supersedes_artifact_id,
            "source_proposal_id": artifact.source_proposal_id,
            "created_by": artifact.created_by,
            "approved_by": artifact.approved_by,
            "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
        }

        all_events = await self._audit_repository.list_events(
            resource_type="skill_artifact",
            limit=200,
        )
        lifecycle_events = [
            {
                "event_type": e.event_type,
                "actor": e.actor,
                "event_data": dict(e.event_data or {}),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in all_events
            if (e.event_data or {}).get("artifact_id") == artifact_id or e.resource_id == artifact_id
        ]
        lifecycle_events.sort(key=lambda e: e.get("created_at") or "", reverse=True)

        usage_events = await self._usage_repository.list_events(
            artifact_id=artifact_id,
            limit=50,
        )
        total = len(usage_events)
        positive = sum(1 for e in usage_events if e.outcome_status in ("completed", "partial_success"))
        negative = sum(1 for e in usage_events if e.outcome_status in ("failed", "aborted"))
        usage_summary = {
            "total_events": total,
            "positive_count": positive,
            "negative_count": negative,
            "success_rate": round(positive / total, 4) if total > 0 else 0.0,
        }

        quality_history = [
            {
                "event_type": e["event_type"],
                "old_score": e["event_data"].get("old_score"),
                "new_score": e["event_data"].get("new_score"),
                "created_at": e["created_at"],
            }
            for e in lifecycle_events
            if e["event_type"] == "skill.quality_score.updated"
        ]

        related_proposal_ids: list[str] = []
        if artifact.source_proposal_id:
            related_proposal_ids.append(artifact.source_proposal_id)

        suppression_history = [
            {
                "event_type": e["event_type"],
                "reason_code": e["event_data"].get("reason_code"),
                "reason_note": e["event_data"].get("reason_note"),
                "actor": e["actor"],
                "created_at": e["created_at"],
            }
            for e in lifecycle_events
            if "suppress" in e["event_type"] or "restore" in e["event_type"]
        ]

        recommendations = await self._recommendation_repository.list_recommendations(
            artifact_id=artifact_id,
            limit=20,
        )
        recommendation_history = [
            {
                "id": r.id,
                "recommendation_type": r.recommendation_type,
                "recommended_action": r.recommended_action,
                "status": r.status,
                "reason_code": r.reason_code,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recommendations
        ]

        return ArtifactTimeline(
            artifact_id=artifact_id,
            artifact_summary=artifact_summary,
            lifecycle_events=lifecycle_events,
            usage_summary=usage_summary,
            quality_history=quality_history,
            related_proposal_ids=related_proposal_ids,
            suppression_history=suppression_history,
            recommendation_history=recommendation_history,
        )
