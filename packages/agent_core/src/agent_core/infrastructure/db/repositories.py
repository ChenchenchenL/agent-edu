# Re-export layer for backward compatibility.
# This file previously contained all 44 Repository classes in a single module.
# They have been split into domain-specific modules under:
#   agent_core.infrastructure.db.repositories.*
#
# All public names are re-exported here so existing imports continue to work.

from agent_core.infrastructure.db.repositories.session import (  # noqa: F401
    SessionRepository,
    SessionMessageRepository,
    SessionQuizRepository,
)
from agent_core.infrastructure.db.repositories.skill import (  # noqa: F401
    SkillArtifactRepository,
    SkillUsageEventRepository,
    SkillCuratorRecommendationRepository,
)
from agent_core.infrastructure.db.repositories.memory import (  # noqa: F401
    MemoryEventRepository,
    MemoryEmbeddingRepository,
    KnowledgeMemoryRepository,
    KnowledgeMemoryEmbeddingRepository,
    BehaviorMemoryRepository,
    BehaviorMemoryEmbeddingRepository,
    MemoryEvidenceLinkRepository,
    MemoryGovernanceDecisionRepository,
    MemoryAnnotationRepository,
    MemoryConflictRepository,
    MemoryMaintenanceJobRepository,
)
from agent_core.infrastructure.db.repositories.audit import (  # noqa: F401
    AuditRepository,
)
from agent_core.infrastructure.db.repositories.reflection import (  # noqa: F401
    ReflectionRecordRepository,
    ReflectionActionRepository,
    ReflectionEvidenceSignalRepository,
    ReflectionOutcomeEvaluationRepository,
    ReflectionReviewDecisionRepository,
    LearnerGoalStrategyCardRepository,
    ReflectiveMemoryRepository,
    ReflectionProposalRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalSandboxRunRepository,
    ReflectionProposalApprovalDecisionRepository,
    ReflectionProposalRolloutRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutDecisionRepository,
    GoalSkillBindingRepository,
)
from agent_core.infrastructure.db.repositories.learner import (  # noqa: F401
    LearnerProfileRepository,
    LearnerGoalRepository,
    GoalAutonomyStateRepository,
    ScheduledAutonomyJobRepository,
    LearnerAvailabilityRepository,
    LearnerTopicMasteryRepository,
    TaskAttemptRepository,
)
from agent_core.infrastructure.db.repositories.planning import (  # noqa: F401
    StudyPlanRepository,
    PlanStageRepository,
    DailyTaskRepository,
    WorkflowRunRepository,
)
