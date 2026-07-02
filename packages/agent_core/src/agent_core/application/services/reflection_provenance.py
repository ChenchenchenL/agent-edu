"""Reflection-sourced proposal provenance and evidence snapshot builders.

All builders are pure functions: deterministic, no repository access, no audit
writes.  Use these to ensure ``evidence_snapshot[\"source\"]`` and related
provenance fields remain consistent across all paths that create
``ReflectionProposal`` objects:

- Direct reflection → ``skill_package`` proposals
- Curator recommendation → ``skill_patch_request``
- ``skill_patch_request_realization`` → replacement ``skill_package``
- Curator merge recommendation → ``skill_package``

The curator service reads these fields in ``_trusted_auto_stage_source()`` and
``_proposal_event_data()``.  Keeping them in one place prevents silent drift
when proposal creation code is spread across multiple services.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Source identifier constants – single source of truth
# ---------------------------------------------------------------------------

PROPOSAL_SOURCE_DIRECT_REFLECTION: str = "reflection_direct"
"""Proposals created directly via create_skill_packages_from_reflection()."""

PROPOSAL_SOURCE_CURATOR_RECOMMENDATION: str = "skill_curator_recommendation"
"""Proposals created via create_skill_patch_request_from_recommendation()."""

PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION: str = "skill_patch_request_realization"
"""Replacement proposals realized from an approved skill_patch_request."""

PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION: str = "skill_curator_merge_recommendation"
"""Replacement proposals created via create_skill_merge_package_from_recommendation()."""

TRUSTED_AUTO_STAGE_SOURCES: frozenset[str] = frozenset(
    {
        PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION,
        PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION,
    }
)
"""Sources whose proposals may be considered for automatic staging.

Mirrors ``TRUSTED_AUTO_STAGE_SOURCES`` in the curator service.  The two must
remain identical; tests should import and compare both to guard against drift.
"""


# ---------------------------------------------------------------------------
# Evidence snapshot builders
# ---------------------------------------------------------------------------


def direct_reflection_evidence(
    *,
    reflection_record_id: str,
    learner_goal_id: str,
    evidence_payload: dict[str, Any],
) -> dict[str, object]:
    """Build evidence snapshot for a proposal created directly from a reflection.

    Args:
        reflection_record_id: ID of the originating ``ReflectionRecord``.
        learner_goal_id: ID of the learner goal.
        evidence_payload: The reflection's ``evidence_payload`` dict.

    Returns:
        A dict suitable for ``ReflectionProposal.evidence_snapshot``.
    """
    return {
        "source": PROPOSAL_SOURCE_DIRECT_REFLECTION,
        "reflection_record_id": reflection_record_id,
        "learner_goal_id": learner_goal_id,
        **evidence_payload,
    }


def curator_recommendation_evidence(
    *,
    recommendation_id: str,
    artifact_id: str | None,
    skill_name: str,
    scope: str,
    surface: str,
    recommendation_reason_code: str,
    evidence_snapshot: dict[str, Any],
    metrics_snapshot: dict[str, Any],
) -> dict[str, object]:
    """Build evidence snapshot for a proposal created from a curator recommendation.

    This snapshot is **not** trusted for auto-staging; the proposal must
    first be realized into a ``skill_patch_request_realization`` replacement
    before it becomes eligible.

    Args:
        recommendation_id: ID of the ``SkillCuratorRecommendation``.
        artifact_id: Target skill artifact (may be None for new skills).
        skill_name: Human-readable skill name.
        scope: Skill scope identifier.
        surface: Deployment surface.
        recommendation_reason_code: Why the curator raised this recommendation.
        evidence_snapshot: Raw evidence dict from the curator job.
        metrics_snapshot: Metrics snapshot from the curator job.

    Returns:
        A dict suitable for ``ReflectionProposal.evidence_snapshot``.
    """
    return {
        "source": PROPOSAL_SOURCE_CURATOR_RECOMMENDATION,
        "recommendation_id": recommendation_id,
        "artifact_id": artifact_id,
        "skill_name": skill_name,
        "scope": scope,
        "surface": surface,
        "recommendation_reason_code": recommendation_reason_code,
        "evidence_snapshot": dict(evidence_snapshot),
        "metrics_snapshot": dict(metrics_snapshot),
    }


def patch_request_realization_evidence(
    *,
    source_skill_patch_request_id: str,
    recommendation_id: str | None,
    source_artifact_id: str | None,
    source_artifact_lineage_id: str | None,
    skill_name: str,
    scope: str,
) -> dict[str, object]:
    """Build evidence snapshot for a replacement proposal realized from a patch request.

    The ``source`` field is ``"skill_patch_request_realization"``, which IS
    included in ``TRUSTED_AUTO_STAGE_SOURCES``.

    Args:
        source_skill_patch_request_id: ID of the originating patch request proposal.
        recommendation_id: Original curator recommendation (if available).
        source_artifact_id: Source skill artifact being replaced.
        source_artifact_lineage_id: Lineage ID of the source artifact.
        skill_name: Human-readable skill name.
        scope: Skill scope identifier.

    Returns:
        A dict suitable for ``ReflectionProposal.evidence_snapshot``.
    """
    return {
        "source": PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION,
        "source_skill_patch_request_id": source_skill_patch_request_id,
        "recommendation_id": recommendation_id,
        "source_artifact_id": source_artifact_id,
        "source_artifact_lineage_id": source_artifact_lineage_id,
        "skill_name": skill_name,
        "scope": scope,
    }


def curator_merge_evidence(
    *,
    recommendation_id: str,
    recommendation_reason_code: str,
    source_artifact_id: str,
    source_artifact_lineage_id: str | None,
    merge_artifact_ids: list[str],
    evidence_snapshot: dict[str, Any],
    metrics_snapshot: dict[str, Any],
) -> dict[str, object]:
    """Build evidence snapshot for a proposal from a curator merge recommendation.

    The ``source`` field is ``"skill_curator_merge_recommendation"``, which IS
    included in ``TRUSTED_AUTO_STAGE_SOURCES``.

    Args:
        recommendation_id: ID of the merge recommendation.
        recommendation_reason_code: Why the curator raised this recommendation.
        source_artifact_id: Primary artifact being merged.
        source_artifact_lineage_id: Lineage ID of the primary artifact.
        merge_artifact_ids: IDs of all artifacts being merged.
        evidence_snapshot: Raw evidence dict from the curator job.
        metrics_snapshot: Metrics snapshot from the curator job.

    Returns:
        A dict suitable for ``ReflectionProposal.evidence_snapshot``.
    """
    return {
        "source": PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION,
        "recommendation_id": recommendation_id,
        "recommendation_reason_code": recommendation_reason_code,
        "source_artifact_id": source_artifact_id,
        "source_artifact_lineage_id": source_artifact_lineage_id,
        "merge_artifact_ids": list(merge_artifact_ids),
        "evidence_snapshot": dict(evidence_snapshot),
        "metrics_snapshot": dict(metrics_snapshot),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_trusted_auto_stage_source(evidence_snapshot: dict[str, object]) -> bool:
    """Return True if the evidence_snapshot identifies a trusted auto-stage source.

    This is the pure-function equivalent of the curator's
    ``_trusted_auto_stage_source()`` static method.  Tests should verify that
    both implementations agree.

    Args:
        evidence_snapshot: The proposal's ``evidence_snapshot`` dict.
    """
    source = evidence_snapshot.get("source")
    return isinstance(source, str) and source in TRUSTED_AUTO_STAGE_SOURCES


def minimum_provenance_keys(source: str) -> frozenset[str]:
    """Return the minimum required keys for a given proposal source.

    Use this in tests to assert that evidence snapshots are structurally
    complete.
    """
    common = frozenset({"source"})
    extras: dict[str, frozenset[str]] = {
        PROPOSAL_SOURCE_DIRECT_REFLECTION: frozenset(
            {"reflection_record_id", "learner_goal_id"}
        ),
        PROPOSAL_SOURCE_CURATOR_RECOMMENDATION: frozenset(
            {"recommendation_id", "recommendation_reason_code", "evidence_snapshot", "metrics_snapshot"}
        ),
        PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION: frozenset(
            {"source_skill_patch_request_id", "skill_name", "scope"}
        ),
        PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION: frozenset(
            {
                "recommendation_id",
                "recommendation_reason_code",
                "source_artifact_id",
                "merge_artifact_ids",
                "evidence_snapshot",
                "metrics_snapshot",
            }
        ),
    }
    return common | extras.get(source, frozenset())
