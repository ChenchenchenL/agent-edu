"""测试repositories拆分后的向后兼容性及各模块完整性."""
import pytest


# ---------------------------------------------------------------------------
# 向后兼容性测试 — 旧 import 路径必须继续有效
# ---------------------------------------------------------------------------


def test_import_from_old_location_session():
    """旧路径导入 Session 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
        SessionRepository,
        SessionMessageRepository,
        SessionQuizRepository,
    )
    assert SessionRepository is not None
    assert SessionMessageRepository is not None
    assert SessionQuizRepository is not None


def test_import_from_old_location_skill():
    """旧路径导入 Skill 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
        SkillArtifactRepository,
        SkillUsageEventRepository,
        SkillCuratorRecommendationRepository,
    )
    assert SkillArtifactRepository is not None
    assert SkillUsageEventRepository is not None
    assert SkillCuratorRecommendationRepository is not None


def test_import_from_old_location_memory():
    """旧路径导入 Memory 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
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
    assert MemoryEventRepository is not None
    assert KnowledgeMemoryRepository is not None
    assert BehaviorMemoryRepository is not None
    assert MemoryMaintenanceJobRepository is not None


def test_import_from_old_location_audit():
    """旧路径导入 Audit Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import AuditRepository
    assert AuditRepository is not None


def test_import_from_old_location_reflection():
    """旧路径导入 Reflection 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
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
    assert ReflectionRecordRepository is not None
    assert ReflectionProposalRepository is not None
    assert GoalSkillBindingRepository is not None


def test_import_from_old_location_learner():
    """旧路径导入 Learner 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
        LearnerProfileRepository,
        LearnerGoalRepository,
        GoalAutonomyStateRepository,
        ScheduledAutonomyJobRepository,
        LearnerAvailabilityRepository,
        LearnerTopicMasteryRepository,
        TaskAttemptRepository,
    )
    assert LearnerProfileRepository is not None
    assert LearnerGoalRepository is not None
    assert TaskAttemptRepository is not None


def test_import_from_old_location_planning():
    """旧路径导入 Planning 相关 Repository 仍有效."""
    from agent_core.infrastructure.db.repositories import (
        StudyPlanRepository,
        PlanStageRepository,
        DailyTaskRepository,
        WorkflowRunRepository,
    )
    assert StudyPlanRepository is not None
    assert DailyTaskRepository is not None
    assert WorkflowRunRepository is not None


# ---------------------------------------------------------------------------
# 新细粒度 import 路径测试
# ---------------------------------------------------------------------------


def test_import_from_new_location_skill():
    """新路径从 repositories.skill 导入."""
    from agent_core.infrastructure.db.repositories.skill import (
        SkillArtifactRepository,
        SkillUsageEventRepository,
        SkillCuratorRecommendationRepository,
    )
    assert SkillArtifactRepository is not None
    assert SkillUsageEventRepository is not None
    assert SkillCuratorRecommendationRepository is not None


def test_import_from_new_location_memory():
    """新路径从 repositories.memory 导入."""
    from agent_core.infrastructure.db.repositories.memory import (
        MemoryEventRepository,
        KnowledgeMemoryRepository,
        BehaviorMemoryRepository,
        MemoryMaintenanceJobRepository,
    )
    assert MemoryEventRepository is not None
    assert KnowledgeMemoryRepository is not None
    assert BehaviorMemoryRepository is not None
    assert MemoryMaintenanceJobRepository is not None


def test_import_from_new_location_audit():
    """新路径从 repositories.audit 导入."""
    from agent_core.infrastructure.db.repositories.audit import AuditRepository
    assert AuditRepository is not None


def test_import_from_new_location_session():
    """新路径从 repositories.session 导入."""
    from agent_core.infrastructure.db.repositories.session import (
        SessionRepository,
        SessionMessageRepository,
        SessionQuizRepository,
    )
    assert SessionRepository is not None
    assert SessionMessageRepository is not None
    assert SessionQuizRepository is not None


def test_import_from_new_location_learner():
    """新路径从 repositories.learner 导入."""
    from agent_core.infrastructure.db.repositories.learner import (
        LearnerProfileRepository,
        LearnerGoalRepository,
        GoalAutonomyStateRepository,
        ScheduledAutonomyJobRepository,
        LearnerAvailabilityRepository,
        LearnerTopicMasteryRepository,
        TaskAttemptRepository,
    )
    assert LearnerProfileRepository is not None
    assert GoalAutonomyStateRepository is not None
    assert TaskAttemptRepository is not None


def test_import_from_new_location_planning():
    """新路径从 repositories.planning 导入."""
    from agent_core.infrastructure.db.repositories.planning import (
        StudyPlanRepository,
        PlanStageRepository,
        DailyTaskRepository,
        WorkflowRunRepository,
    )
    assert StudyPlanRepository is not None
    assert WorkflowRunRepository is not None


def test_import_from_new_location_reflection():
    """新路径从 repositories.reflection 导入."""
    from agent_core.infrastructure.db.repositories.reflection import (
        ReflectionRecordRepository,
        ReflectionProposalRepository,
        ReflectionProposalRolloutRepository,
        GoalSkillBindingRepository,
    )
    assert ReflectionRecordRepository is not None
    assert ReflectionProposalRepository is not None
    assert GoalSkillBindingRepository is not None


# ---------------------------------------------------------------------------
# 包级 __init__ 导出完整性测试
# ---------------------------------------------------------------------------


def test_package_init_exports_all_classes():
    """repositories 包的 __init__.py 应导出全部 44 个类."""
    import agent_core.infrastructure.db.repositories as repo_pkg

    expected_classes = [
        # session
        "SessionRepository", "SessionMessageRepository", "SessionQuizRepository",
        # skill
        "SkillArtifactRepository", "SkillUsageEventRepository", "SkillCuratorRecommendationRepository",
        # audit
        "AuditRepository",
        # learner
        "LearnerProfileRepository", "LearnerGoalRepository", "GoalAutonomyStateRepository",
        "ScheduledAutonomyJobRepository", "LearnerAvailabilityRepository",
        "LearnerTopicMasteryRepository", "TaskAttemptRepository",
        # planning
        "StudyPlanRepository", "PlanStageRepository", "DailyTaskRepository", "WorkflowRunRepository",
        # memory
        "MemoryEventRepository", "MemoryEmbeddingRepository", "KnowledgeMemoryRepository",
        "KnowledgeMemoryEmbeddingRepository", "BehaviorMemoryRepository",
        "BehaviorMemoryEmbeddingRepository", "MemoryEvidenceLinkRepository",
        "MemoryGovernanceDecisionRepository", "MemoryAnnotationRepository",
        "MemoryConflictRepository", "MemoryMaintenanceJobRepository",
        # reflection
        "ReflectionRecordRepository", "ReflectionActionRepository",
        "ReflectionEvidenceSignalRepository", "ReflectionOutcomeEvaluationRepository",
        "ReflectionReviewDecisionRepository", "LearnerGoalStrategyCardRepository",
        "ReflectiveMemoryRepository", "ReflectionProposalRepository",
        "ReflectionProposalEvaluationRepository", "ReflectionProposalSandboxRunRepository",
        "ReflectionProposalApprovalDecisionRepository", "ReflectionProposalRolloutRepository",
        "ReflectionProposalRolloutObservationRepository",
        "ReflectionProposalRolloutDecisionRepository", "GoalSkillBindingRepository",
    ]

    missing = [cls for cls in expected_classes if not hasattr(repo_pkg, cls)]
    assert not missing, f"Missing from repositories package __init__: {missing}"
    assert len(expected_classes) == 44


# ---------------------------------------------------------------------------
# 类结构完整性测试
# ---------------------------------------------------------------------------


def test_repository_class_structure_preserved():
    """仓储类结构保持不变——具备可调用的 __init__."""
    from agent_core.infrastructure.db.repositories import (
        SkillArtifactRepository,
        MemoryEventRepository,
        ReflectionRecordRepository,
        AuditRepository,
        SessionRepository,
    )
    for cls in (
        SkillArtifactRepository,
        MemoryEventRepository,
        ReflectionRecordRepository,
        AuditRepository,
        SessionRepository,
    ):
        assert callable(getattr(cls, "__init__", None)), f"{cls.__name__} missing callable __init__"


def test_same_class_identity_old_and_new_path():
    """旧路径和新路径导入的类是同一个对象（无重复定义）."""
    from agent_core.infrastructure.db.repositories import SkillArtifactRepository as Old
    from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository as New
    assert Old is New, "SkillArtifactRepository from old and new path must be the same class object"

    from agent_core.infrastructure.db.repositories import MemoryEventRepository as OldMem
    from agent_core.infrastructure.db.repositories.memory import MemoryEventRepository as NewMem
    assert OldMem is NewMem, "MemoryEventRepository from old and new path must be the same class object"
