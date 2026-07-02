"""Skill observability metrics refresh.

This module provides functions to refresh skill-related observability
metrics from repository data. It reads aggregated data and updates
metrics adapters without making lifecycle decisions or creating artifacts.
"""

from __future__ import annotations

from typing import Any

from agent_core.domain.entities.skill import (
    SKILL_ARTIFACT_STATUSES,
    SKILL_CURATOR_RECOMMENDATION_TYPES,
)
from agent_core.infrastructure.observability.metrics import (
    set_skill_artifacts_total,
    set_skill_curator_pending_recommendations,
)


async def refresh_skill_observability_metrics(
    *,
    artifact_repository: Any | None = None,
    recommendation_repository: Any | None = None,
) -> None:
    """Refresh skill artifact and recommendation metrics from repository state."""
    if artifact_repository is not None:
        count_by_status = getattr(artifact_repository, "count_by_status", None)
        if count_by_status is not None:
            artifact_counts = await count_by_status()
            for status in SKILL_ARTIFACT_STATUSES:
                set_skill_artifacts_total(status=status, count=int(artifact_counts.get(status, 0)))
    if recommendation_repository is not None:
        count_pending_by_type = getattr(recommendation_repository, "count_pending_by_type", None)
        if count_pending_by_type is not None:
            pending_counts = await count_pending_by_type()
            for recommendation_type in SKILL_CURATOR_RECOMMENDATION_TYPES:
                set_skill_curator_pending_recommendations(
                    recommendation_type=recommendation_type,
                    count=int(pending_counts.get(recommendation_type, 0)),
                )
