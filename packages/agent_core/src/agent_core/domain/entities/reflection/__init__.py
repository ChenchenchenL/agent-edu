"""Reflection entities."""

from agent_core.domain.entities.reflection.record import (
    ReflectionAction,
    ReflectionRecord,
    REFLECTION_ACTION_TYPES,
    REFLECTION_ROOT_CAUSES,
    REFLECTION_STATUSES,
)
from agent_core.domain.entities.reflection.evaluation import (
    LearnerGoalStrategyCard,
    ReflectionEvidenceSignal,
    ReflectionOutcomeEvaluation,
    ReflectionReviewDecision,
    ReflectiveMemory,
)
from agent_core.domain.entities.reflection.proposal import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalApprovalDecision,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutDecision,
    ReflectionProposalRolloutObservation,
    ReflectionProposalSandboxRun,
    PROPOSAL_STATUSES,
    proposal_policy_keys,
    proposal_rollout_surface,
)

__all__ = [
    # Record
    "ReflectionAction",
    "ReflectionRecord",
    "REFLECTION_ACTION_TYPES",
    "REFLECTION_ROOT_CAUSES",
    "REFLECTION_STATUSES",
    # Evaluation
    "LearnerGoalStrategyCard",
    "ReflectionEvidenceSignal",
    "ReflectionOutcomeEvaluation",
    "ReflectionReviewDecision",
    "ReflectiveMemory",
    # Proposal & Rollout
    "GoalSkillBinding",
    "ReflectionProposal",
    "ReflectionProposalApprovalDecision",
    "ReflectionProposalEvaluation",
    "ReflectionProposalRollout",
    "ReflectionProposalRolloutDecision",
    "ReflectionProposalRolloutObservation",
    "ReflectionProposalSandboxRun",
    "PROPOSAL_STATUSES",
    "proposal_policy_keys",
    "proposal_rollout_surface",
]
