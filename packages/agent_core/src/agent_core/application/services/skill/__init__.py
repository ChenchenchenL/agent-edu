"""Skill service subpackage.

This package contains the split skill service modules. Each module has
a single, well-defined responsibility:

- constants: Skill service constants and thresholds
- protocols: Cross-service protocol definitions
- observability: Metrics refresh functions
- catalog: Read-only artifact queries
- candidates: Proposal-to-candidate materialization
- readiness: Replacement readiness evaluation
- lifecycle: Artifact state transitions (single entry point)
- replacement_staging: Replacement proposal staging orchestration
- recommendations: Curator recommendation management
- curator_job: Background curator job scanning and recommendation generation
- resolution: Runtime skill resolution
- usage: Usage event recording and querying
"""

from agent_core.application.services.skill.catalog import SkillCatalogService
from agent_core.application.services.skill.candidates import SkillCandidateService
from agent_core.application.services.skill.constants import (
    ACTIVE_SKILL_REFERENCE_STATUSES,
    ALLOWED_SKILL_PACKAGE_TOOLS,
    CANDIDATE_MIN_SCORE_DELTA,
    CURATOR_ACTIVATION_REASON_CODES,
    CURATOR_ARCHIVE_REASON_CODES,
    CURATOR_DEACTIVATION_REASON_CODES,
    CURATOR_RESTORE_REASON_CODES,
    CURATOR_SUPPRESSION_REASON_CODES,
    MERGE_OVERLAP_RULE_KEYS,
    MERGE_RELATED_ARTIFACT_STATUSES,
    MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER,
    MERGE_SOURCE_ARTIFACT_STATUSES,
    REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE,
    REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN,
    REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN,
    STABLE_MAX_NEGATIVE_USAGE_RATE,
    STABLE_MIN_SUCCESSFUL_USAGE_COUNT,
    STABLE_NEGATIVE_USAGE_STATUSES,
    STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT,
    STABLE_SUCCESSFUL_USAGE_STATUSES,
)
from agent_core.application.services.skill.curator_job import (
    SkillCuratorJobConfig,
    SkillCuratorJobResult,
    SkillCuratorJobService,
)
from agent_core.application.services.skill.lifecycle import SkillArtifactLifecycleService
from agent_core.application.services.skill.observability import refresh_skill_observability_metrics
from agent_core.application.services.skill.protocols import SkillPatchProposalService
from agent_core.application.services.skill.readiness import (
    SkillReplacementReadiness,
    SkillReplacementReadinessAction,
    SkillReplacementReadinessService,
    SkillReplacementReadinessThresholds,
    matches_rollout_metadata,
)
from agent_core.application.services.skill.recommendations import SkillCuratorRecommendationService
from agent_core.application.services.skill.replacement_staging import SkillReplacementStagingService
from agent_core.application.services.skill.resolution import SkillResolver
from agent_core.application.services.skill.runtime_explain import RuntimeExplainService
from agent_core.application.services.skill.runtime_readiness import RuntimeBindingExplainResult, RuntimeBindingReadiness
from agent_core.application.services.skill.usage import SkillUsageService

__all__ = [
    "ACTIVE_SKILL_REFERENCE_STATUSES",
    "ALLOWED_SKILL_PACKAGE_TOOLS",
    "CANDIDATE_MIN_SCORE_DELTA",
    "CURATOR_ACTIVATION_REASON_CODES",
    "CURATOR_ARCHIVE_REASON_CODES",
    "CURATOR_DEACTIVATION_REASON_CODES",
    "CURATOR_RESTORE_REASON_CODES",
    "CURATOR_SUPPRESSION_REASON_CODES",
    "MERGE_OVERLAP_RULE_KEYS",
    "MERGE_RELATED_ARTIFACT_STATUSES",
    "MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER",
    "MERGE_SOURCE_ARTIFACT_STATUSES",
    "REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE",
    "REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN",
    "REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN",
    "STABLE_MAX_NEGATIVE_USAGE_RATE",
    "STABLE_MIN_SUCCESSFUL_USAGE_COUNT",
    "STABLE_NEGATIVE_USAGE_STATUSES",
    "STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT",
    "STABLE_SUCCESSFUL_USAGE_STATUSES",
    "SkillArtifactLifecycleService",
    "SkillCatalogService",
    "SkillCandidateService",
    "SkillCuratorJobConfig",
    "SkillCuratorJobResult",
    "SkillCuratorJobService",
    "SkillCuratorRecommendationService",
    "SkillPatchProposalService",
    "SkillReplacementReadiness",
    "SkillReplacementReadinessAction",
    "SkillReplacementReadinessService",
    "SkillReplacementReadinessThresholds",
    "SkillReplacementStagingService",
    "SkillResolver",
    "SkillUsageService",
    "RuntimeExplainService",
    "RuntimeBindingExplainResult",
    "RuntimeBindingReadiness",
    "matches_rollout_metadata",
    "refresh_skill_observability_metrics",
]
