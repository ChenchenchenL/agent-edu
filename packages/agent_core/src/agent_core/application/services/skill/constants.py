"""Skill service constants and thresholds.

This module contains all constants and threshold values used by the skill
service subsystem. These values govern artifact lifecycle transitions,
readiness evaluation, curator job behavior, and runtime resolution.
"""

from __future__ import annotations

from agent_core.domain.constants import (
    SkillArtifactStatus,
    SkillLifecycleThresholds,
)

_thresholds = SkillLifecycleThresholds()
CANDIDATE_MIN_SCORE_DELTA = _thresholds.CANDIDATE_MIN_SCORE_DELTA
STABLE_MIN_SUCCESSFUL_USAGE_COUNT = _thresholds.STABLE_MIN_SUCCESSFUL_USAGE
STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT = _thresholds.STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT
STABLE_MAX_NEGATIVE_USAGE_RATE = _thresholds.STABLE_MAX_NEGATIVE_RATE
REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN = _thresholds.STAGING_MIN_USAGE_COUNT
REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN = _thresholds.REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN
REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE = _thresholds.STAGING_MAX_FAILURE_RATE

ALLOWED_SKILL_PACKAGE_TOOLS = {"review_scheduling", "assessment_generation", "partial_replan"}
STABLE_SUCCESSFUL_USAGE_STATUSES = {"completed", "partial_success"}
STABLE_NEGATIVE_USAGE_STATUSES = {"failed", "skipped", "aborted"}
ACTIVE_SKILL_REFERENCE_STATUSES = [
    SkillArtifactStatus.STAGED.value,
    "rolled_out",
]
CURATOR_DEACTIVATION_REASON_CODES = {
    "rollout_rollback",
    "quality_regression",
    "safety_risk",
    "superseded",
    "operator_request",
}
CURATOR_SUPPRESSION_REASON_CODES = {
    "safety_risk",
    "quality_regression",
    "policy_violation",
    "operator_request",
}
CURATOR_RESTORE_REASON_CODES = {
    "operator_restore",
    "risk_mitigated",
    "false_positive",
}
CURATOR_ARCHIVE_REASON_CODES = {
    "stale_deprecated",
    "operator_request",
    "cleanup",
}
CURATOR_ACTIVATION_REASON_CODES = {
    "operator_reviewed",
    "replacement_evidence_ready",
    "source_selectable_missing",
    "operator_request",
    "rollout_promoted",
}
MERGE_SOURCE_ARTIFACT_STATUSES = {
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value,
}
MERGE_RELATED_ARTIFACT_STATUSES = {
    SkillArtifactStatus.CANDIDATE.value,
    SkillArtifactStatus.STAGED.value,
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value,
    SkillArtifactStatus.DEPRECATED.value,
}
MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER = (
    SkillArtifactStatus.CANDIDATE.value,
    SkillArtifactStatus.STAGED.value,
    SkillArtifactStatus.ACTIVE.value,
    SkillArtifactStatus.STABLE.value,
    SkillArtifactStatus.DEPRECATED.value,
)
MERGE_OVERLAP_RULE_KEYS = ("task_types", "topic_keys")
