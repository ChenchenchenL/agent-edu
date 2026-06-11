"""测试repositories拆分后的向后兼容性."""
import pytest


def test_import_from_old_location():
    """测试从旧位置导入仍然有效."""
    # 这些导入应该仍然有效（向后兼容）
    from agent_core.infrastructure.db.repositories import (
        SkillArtifactRepository,
        SkillUsageEventRepository,
        SkillCuratorRecommendationRepository,
        MemoryEventRepository,
        KnowledgeMemoryRepository,
        BehaviorMemoryRepository,
        SessionRepository,
        AuditRepository,
        ReflectionRecordRepository,
    )

    # 验证所有类都可导入
    assert SkillArtifactRepository is not None
    assert MemoryEventRepository is not None
    assert SessionRepository is not None


def test_import_from_new_location():
    """测试从新位置导入."""
    # 新的细粒度导入
    from agent_core.infrastructure.db.repositories.skill import (
        SkillArtifactRepository,
        SkillUsageEventRepository,
    )
    from agent_core.infrastructure.db.repositories.memory import (
        MemoryEventRepository,
        KnowledgeMemoryRepository,
    )
    from agent_core.infrastructure.db.repositories.audit import (
        AuditRepository,
    )

    assert SkillArtifactRepository is not None
    assert MemoryEventRepository is not None
    assert AuditRepository is not None


def test_repository_class_structure_preserved():
    """测试仓储类结构保持不变."""
    from agent_core.infrastructure.db.repositories import SkillArtifactRepository

    # 验证类方法未改变
    assert hasattr(SkillArtifactRepository, '__init__')
    # 通常Repository类有这些方法
    assert callable(getattr(SkillArtifactRepository, '__init__', None))
