"""
测试常量模块
"""
import pytest
from agent_core.domain.constants.skill_constants import (
    SkillArtifactStatus,
    SkillType,
    SkillLifecycleThresholds,
    SkillEvaluationConstants,
    ALLOWED_SKILL_PACKAGE_TOOLS,
)


class TestSkillArtifactStatus:
    """测试技能工件状态枚举"""

    def test_all_statuses_exist(self):
        """验证所有必需的状态都存在"""
        assert hasattr(SkillArtifactStatus, "CANDIDATE")
        assert hasattr(SkillArtifactStatus, "STAGED")
        assert hasattr(SkillArtifactStatus, "ACTIVE")
        assert hasattr(SkillArtifactStatus, "STABLE")
        assert hasattr(SkillArtifactStatus, "DEPRECATED")
        assert hasattr(SkillArtifactStatus, "ARCHIVED")

    def test_status_values(self):
        """验证状态值正确"""
        assert SkillArtifactStatus.CANDIDATE.value == "candidate"
        assert SkillArtifactStatus.STAGED.value == "staged"
        assert SkillArtifactStatus.ACTIVE.value == "active"
        assert SkillArtifactStatus.STABLE.value == "stable"
        assert SkillArtifactStatus.DEPRECATED.value == "deprecated"
        assert SkillArtifactStatus.ARCHIVED.value == "archived"

    def test_status_immutability(self):
        """验证枚举不可变"""
        with pytest.raises(AttributeError):
            SkillArtifactStatus.CANDIDATE = "modified"


class TestSkillType:
    """测试技能类型枚举"""

    def test_all_types_exist(self):
        """验证所有必需的类型都存在"""
        assert hasattr(SkillType, "LEARNING")
        assert hasattr(SkillType, "MEMORY")
        assert hasattr(SkillType, "REFLECTION")
        assert hasattr(SkillType, "PLANNING")

    def test_type_values(self):
        """验证类型值正确"""
        assert SkillType.LEARNING.value == "learning"
        assert SkillType.MEMORY.value == "memory"
        assert SkillType.REFLECTION.value == "reflection"
        assert SkillType.PLANNING.value == "planning"


class TestSkillLifecycleThresholds:
    """测试技能生命周期阈值"""

    def test_thresholds_are_frozen(self):
        """验证阈值配置不可变"""
        instance = SkillLifecycleThresholds()
        with pytest.raises(AttributeError):
            instance.CANDIDATE_MIN_SCORE_DELTA = 999

    def test_threshold_values(self):
        """验证阈值数值正确"""
        assert SkillLifecycleThresholds.CANDIDATE_MIN_SCORE_DELTA == 0.1
        assert SkillLifecycleThresholds.STABLE_MIN_SUCCESSFUL_USAGE == 5
        assert SkillLifecycleThresholds.STABLE_MAX_NEGATIVE_RATE == 0.2
        assert SkillLifecycleThresholds.STABLE_MIN_OBSERVATION_COUNT == 10
        assert SkillLifecycleThresholds.STAGING_MIN_USAGE_COUNT == 3
        assert SkillLifecycleThresholds.STAGING_MAX_FAILURE_RATE == 0.3
        assert SkillLifecycleThresholds.DEPRECATION_NEGATIVE_RATE_THRESHOLD == 0.5
        assert SkillLifecycleThresholds.DEPRECATION_MIN_NEGATIVE_COUNT == 3
        assert SkillLifecycleThresholds.ARCHIVE_STALE_DAYS == 90


class TestSkillEvaluationConstants:
    """测试技能评估常量"""

    def test_constants_are_frozen(self):
        """验证评估常量配置不可变"""
        instance = SkillEvaluationConstants()
        with pytest.raises(AttributeError):
            instance.MIN_USAGE_FOR_EVALUATION = 999

    def test_constant_values(self):
        """验证评估常量数值正确"""
        assert SkillEvaluationConstants.MIN_USAGE_FOR_EVALUATION == 5
        assert SkillEvaluationConstants.EVALUATION_LOOKBACK_DAYS == 30
        assert SkillEvaluationConstants.SUCCESS_RATE_THRESHOLD == 0.7


class TestAllowedSkillPackageTools:
    """测试允许的技能包工具集"""

    def test_is_frozenset(self):
        """验证工具集是 frozenset 类型"""
        assert isinstance(ALLOWED_SKILL_PACKAGE_TOOLS, frozenset)

    def test_contains_expected_tools(self):
        """验证包含预期的工具"""
        expected_tools = {
            "Read",
            "Write",
            "Edit",
            "Bash",
            "WebFetch",
            "WebSearch",
            "Agent",
            "AskUserQuestion",
        }
        assert ALLOWED_SKILL_PACKAGE_TOOLS == expected_tools

    def test_immutability(self):
        """验证工具集不可变"""
        with pytest.raises(AttributeError):
            ALLOWED_SKILL_PACKAGE_TOOLS.add("NewTool")
