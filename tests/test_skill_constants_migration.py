"""测试skills.py迁移到新常量系统."""
from agent_core.domain.constants import SkillArtifactStatus, ALLOWED_SKILL_PACKAGE_TOOLS


def test_skill_status_string_values_preserved():
    """确保枚举值与原字符串一致."""
    # 这些是代码中实际使用的字符串值
    assert SkillArtifactStatus.CANDIDATE.value == "candidate"
    assert SkillArtifactStatus.STAGED.value == "staged"
    assert SkillArtifactStatus.ACTIVE.value == "active"
    assert SkillArtifactStatus.STABLE.value == "stable"
    assert SkillArtifactStatus.DEPRECATED.value == "deprecated"
    assert SkillArtifactStatus.ARCHIVED.value == "archived"

    # 确保可以用于字符串比较（向后兼容）
    status = "candidate"
    assert status == SkillArtifactStatus.CANDIDATE.value


def test_allowed_tools_migration():
    """测试工具集合迁移."""
    # 原代码中的检查方式
    tool_name = "Read"
    assert tool_name in ALLOWED_SKILL_PACKAGE_TOOLS

    # 不存在的工具
    assert "InvalidTool" not in ALLOWED_SKILL_PACKAGE_TOOLS


def test_status_enum_in_set_operations():
    """测试枚举值可用于集合操作."""
    # 原代码使用字符串集合
    MERGE_SOURCE_ARTIFACT_STATUSES = {
        SkillArtifactStatus.ACTIVE.value,
        SkillArtifactStatus.STABLE.value
    }
    assert "active" in MERGE_SOURCE_ARTIFACT_STATUSES
    assert SkillArtifactStatus.ACTIVE.value in MERGE_SOURCE_ARTIFACT_STATUSES


def test_status_enum_in_list_operations():
    """测试枚举值可用于列表操作."""
    # 原代码使用字符串列表
    ACTIVE_SKILL_REFERENCE_STATUSES = [
        SkillArtifactStatus.STAGED.value,
        "rolled_out"  # 这个不在枚举中，保持原样
    ]
    assert "staged" in ACTIVE_SKILL_REFERENCE_STATUSES
