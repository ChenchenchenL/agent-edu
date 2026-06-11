"""
技能相关常量定义

集中管理技能模块使用的常量，使用类型安全的枚举和不可变数据结构
"""
from enum import Enum


class SkillArtifactStatus(str, Enum):
    """技能工件状态枚举"""

    PENDING = "pending"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    DEPRECATED = "deprecated"


class SkillType(str, Enum):
    """技能类型枚举"""

    SYSTEM = "system"
    USER_CREATED = "user_created"
    APPROVED = "approved"


class SkillLifecycleThresholds:
    """技能生命周期阈值配置（不可变）

    使用类属性实现不可变配置，避免 Python 3.6 不支持 dataclasses 的问题
    """

    # 激活阈值
    MIN_SUCCESS_COUNT = 5
    MIN_SUCCESS_RATE = 0.7

    # 停用阈值
    DEACTIVATION_FAILURE_RATE = 0.5
    MIN_EXECUTION_COUNT_FOR_DEACTIVATION = 10

    # 重新激活冷却期（天数）
    REACTIVATION_COOLDOWN_DAYS = 7

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性"""
        raise AttributeError("SkillLifecycleThresholds is immutable")


# 允许在技能包中使用的工具集合（不可变）
ALLOWED_SKILL_PACKAGE_TOOLS: frozenset = frozenset({
    "Read",
    "Write",
    "Edit",
    "Bash",
    "WebSearch",
    "WebFetch",
    "TaskCreate",
    "TaskUpdate",
    "TaskGet",
    "TaskList",
})
