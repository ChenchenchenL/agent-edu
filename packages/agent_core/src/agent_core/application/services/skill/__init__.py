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

from agent_core.application.services.skill.capability import (
    CAPABILITY_BRIDGE_VERSION,
    CapabilityRequest,
    CapabilitySelection,
    RuntimeCapabilityExecutionPlan,
)
from agent_core.application.services.skill.capability_bridge import CapabilityRequestBridge
from agent_core.application.services.skill.capability_catalog import (
    CapabilityBridgeEntry,
    get_bridge_entry,
    list_capabilities,
    resolve_capability_to_legacy,
)
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
from agent_core.application.services.skill.curator_execution_policy import (
    AUTO_EXECUTABLE_RECOMMENDATION_TYPES,
    CURATOR_EXECUTION_STATUSES,
    FAILURE_REASON_CODES,
    MANUAL_GATE_RECOMMENDATION_TYPES,
    CuratorExecutionEligibility,
    CuratorExecutionEligibilityService,
)
from agent_core.application.services.skill.curator_executor import (
    CuratorExecutionRequest,
    CuratorExecutionResult,
    CuratorExecutorService,
)
from agent_core.application.services.skill.router import (
    CANDIDATE_SOURCE_TYPES,
    ROUTING_CONFIDENCE_THRESHOLDS,
    TRUST_LEVELS,
    SkillCandidateSource,
    SkillRouterCandidate,
    SkillRouterDecision,
    SkillRouterRequest,
    SkillRouterService,
)
from agent_core.application.services.skill.router_policy import SkillCandidateRanker
from agent_core.application.services.skill.router_sources import (
    ActiveArtifactCandidateSource,
    BaselineBuiltinCandidateSource,
    StagedArtifactCandidateSource,
    TenantExternalArtifactCandidateSource,
)
from agent_core.application.services.skill.runtime_explain import RuntimeExplainService
from agent_core.application.services.skill.runtime_readiness import RuntimeBindingExplainResult, RuntimeBindingReadiness
from agent_core.application.services.skill.outcome_aggregator import SkillOutcomeAggregator
from agent_core.application.services.skill.outcome_feedback_job import (
    SkillOutcomeFeedbackConfig,
    SkillOutcomeFeedbackJob,
    SkillOutcomeFeedbackResult,
)
from agent_core.application.services.skill.usage import SkillUsageService
from agent_core.application.services.tool_capabilities import (
    BUILTIN_CAPABILITIES,
    ToolCapability,
    get_capability,
    get_capability_by_tool_name,
)
from agent_core.application.services.surface_policies import (
    BUILTIN_POLICIES,
    SurfacePolicy,
    get_surface_policy,
    list_surface_policies,
    require_surface_policy,
)
from agent_core.application.services.plan_templates import (
    PlanTemplate,
    PlanTemplateOutputReferenceContract,
    PlanTemplateStep,
    PlanTemplateVariableContract,
    build_plan_template_from_legacy_tool_plan,
)
from agent_core.application.services.plan_template_validation import (
    PlanTemplateValidator,
    TemplateValidationResult,
)
from agent_core.application.services.plan_template_selector import (
    PlanTemplateSelectionRequest,
    PlanTemplateSelectionResult,
    PlanTemplateSelector,
)

__all__ = [
    "ACTIVE_SKILL_REFERENCE_STATUSES",
    "ALLOWED_SKILL_PACKAGE_TOOLS",
    "AUTO_EXECUTABLE_RECOMMENDATION_TYPES",
    "ActiveArtifactCandidateSource",
    "BaselineBuiltinCandidateSource",
    "CANDIDATE_SOURCE_TYPES",
    "CAPABILITY_BRIDGE_VERSION",
    "CANDIDATE_MIN_SCORE_DELTA",
    "CURATOR_ACTIVATION_REASON_CODES",
    "CURATOR_ARCHIVE_REASON_CODES",
    "CURATOR_DEACTIVATION_REASON_CODES",
    "CURATOR_EXECUTION_STATUSES",
    "CURATOR_RESTORE_REASON_CODES",
    "CURATOR_SUPPRESSION_REASON_CODES",
    "CuratorExecutionEligibility",
    "CuratorExecutionEligibilityService",
    "CuratorExecutionRequest",
    "CuratorExecutionResult",
    "CuratorExecutorService",
    "CapabilityBridgeEntry",
    "CapabilityRequest",
    "CapabilityRequestBridge",
    "CapabilitySelection",
    "FAILURE_REASON_CODES",
    "MERGE_OVERLAP_RULE_KEYS",
    "MERGE_RELATED_ARTIFACT_STATUSES",
    "MERGE_RELATED_ARTIFACT_STATUS_SCAN_ORDER",
    "MERGE_SOURCE_ARTIFACT_STATUSES",
    "REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE",
    "REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN",
    "REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN",
    "ROUTING_CONFIDENCE_THRESHOLDS",
    "RuntimeCapabilityExecutionPlan",
    "STABLE_MAX_NEGATIVE_USAGE_RATE",
    "STABLE_MIN_SUCCESSFUL_USAGE_COUNT",
    "STABLE_NEGATIVE_USAGE_STATUSES",
    "STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT",
    "STABLE_SUCCESSFUL_USAGE_STATUSES",
    "SkillArtifactLifecycleService",
    "SkillCandidateRanker",
    "SkillCandidateSource",
    "SkillCatalogService",
    "SkillCandidateService",
    "SkillCuratorJobConfig",
    "SkillCuratorJobResult",
    "SkillCuratorJobService",
    "SkillCuratorRecommendationService",
    "SkillOutcomeAggregator",
    "SkillOutcomeFeedbackConfig",
    "SkillOutcomeFeedbackJob",
    "SkillOutcomeFeedbackResult",
    "SkillPatchProposalService",
    "SkillReplacementReadiness",
    "SkillReplacementReadinessAction",
    "SkillReplacementReadinessService",
    "SkillReplacementReadinessThresholds",
    "SkillReplacementStagingService",
    "SkillResolver",
    "SkillRouterCandidate",
    "SkillRouterDecision",
    "SkillRouterRequest",
    "SkillRouterService",
    "SkillUsageService",
    "StagedArtifactCandidateSource",
    "TRUST_LEVELS",
    "TenantExternalArtifactCandidateSource",
    "RuntimeExplainService",
    "RuntimeBindingExplainResult",
    "RuntimeBindingReadiness",
    "get_bridge_entry",
    "list_capabilities",
    "MANUAL_GATE_RECOMMENDATION_TYPES",
    "matches_rollout_metadata",
    "refresh_skill_observability_metrics",
    "resolve_capability_to_legacy",
    "BUILTIN_CAPABILITIES",
    "BUILTIN_POLICIES",
    "PlanTemplate",
    "PlanTemplateOutputReferenceContract",
    "PlanTemplateSelectionRequest",
    "PlanTemplateSelectionResult",
    "PlanTemplateSelector",
    "PlanTemplateStep",
    "PlanTemplateValidator",
    "PlanTemplateVariableContract",
    "SurfacePolicy",
    "TemplateValidationResult",
    "ToolCapability",
    "build_plan_template_from_legacy_tool_plan",
    "get_capability",
    "get_capability_by_tool_name",
    "get_surface_policy",
    "list_surface_policies",
    "require_surface_policy",
]
