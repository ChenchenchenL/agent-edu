"""
测试常量模块
"""
import pytest
from agent_core.domain.constants.skill_constants import (
    SkillArtifactStatus,
    SkillType,
    SkillLifecycleThresholds,
    ALLOWED_SKILL_PACKAGE_TOOLS,
)


class TestSkillArtifactStatus:
    """测试技能工件状态枚举"""

    def test_all_statuses_exist(self):
        """验证所有必需的状态都存在"""
        assert hasattr(SkillArtifactStatus, "PENDING")
        assert hasattr(SkillArtifactStatus, "ACTIVE")
        assert hasattr(SkillArtifactStatus, "DEACTIVATED")
        assert hasattr(SkillArtifactStatus, "DEPRECATED")

    def test_status_values(self):
        """验证状态值正确"""
        assert SkillArtifactStatus.PENDING.value == "pending"
        assert SkillArtifactStatus.ACTIVE.value == "active"
        assert SkillArtifactStatus.DEACTIVATED.value == "deactivated"
        assert SkillArtifactStatus.DEPRECATED.value == "deprecated"

    def test_status_immutability(self):
        """验证枚举不可变"""
        with pytest.raises(AttributeError):
            SkillArtifactStatus.PENDING = "modified"


class TestSkillType:
    """测试技能类型枚举"""

    def test_all_types_exist(self):
        """验证所有必需的类型都存在"""
        assert hasattr(SkillType, "SYSTEM")
        assert hasattr(SkillType, "USER_CREATED")
        assert hasattr(SkillType, "APPROVED")

    def test_type_values(self):
        """验证类型值正确"""
        assert SkillType.SYSTEM.value == "system"
        assert SkillType.USER_CREATED.value == "user_created"
        assert SkillType.APPROVED.value == "approved"


class TestSkillLifecycleThresholds:
    """测试技能生命周期阈值"""

    def test_thresholds_are_frozen(self):
        """验证阈值配置不可变"""
        instance = SkillLifecycleThresholds()
        with pytest.raises(AttributeError):
            instance.MIN_SUCCESS_COUNT = 999

    def test_threshold_values(self):
        """验证阈值数值正确"""
        assert SkillLifecycleThresholds.MIN_SUCCESS_COUNT == 5
        assert SkillLifecycleThresholds.MIN_SUCCESS_RATE == 0.7
        assert SkillLifecycleThresholds.DEACTIVATION_FAILURE_RATE == 0.5
        assert SkillLifecycleThresholds.MIN_EXECUTION_COUNT_FOR_DEACTIVATION == 10
        assert SkillLifecycleThresholds.REACTIVATION_COOLDOWN_DAYS == 7


class TestAllowedSkillPackageTools:
    """测试允许的技能包工具集"""

    def test_is_frozenset(self):
        """验证工具集是 frozenset 类型"""
        assert isinstance(ALLOWED_SKILL_PACKAGE_TOOLS, frozenset)

    def test_contains_expected_tools(self):
        """验证包含预期的工具"""
        expected_tools = {"Read", "Write", "Edit", "Bash", "WebSearch"}
        assert expected_tools.issubset(ALLOWED_SKILL_PACKAGE_TOOLS)

    def test_immutability(self):
        """验证工具集不可变"""
        with pytest.raises(AttributeError):
            ALLOWED_SKILL_PACKAGE_TOOLS.add("NewTool")
