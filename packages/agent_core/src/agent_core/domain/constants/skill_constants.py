"""
技能相关常量定义

集中管理技能模块使用的常量，使用类型安全的枚举和不可变数据结构
"""
from enum import Enum


class SkillArtifactStatus(str, Enum):
    """技能工件状态枚举"""

    CANDIDATE = "candidate"
    STAGED = "staged"
    ACTIVE = "active"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SkillType(str, Enum):
    """技能类型枚举"""

    LEARNING = "learning"
    MEMORY = "memory"
    REFLECTION = "reflection"
    PLANNING = "planning"


class SkillLifecycleThresholds:
    """技能生命周期阈值配置（不可变）

    使用类属性实现不可变配置，避免 Python 3.6 不支持 dataclasses 的问题
    """

    CANDIDATE_MIN_SCORE_DELTA: float = 0.1
    STABLE_MIN_SUCCESSFUL_USAGE: int = 5
    STABLE_MAX_NEGATIVE_RATE: float = 0.2
    STABLE_MIN_OBSERVATION_COUNT: int = 10
    STAGING_MIN_USAGE_COUNT: int = 3
    STAGING_MAX_FAILURE_RATE: float = 0.3
    DEPRECATION_NEGATIVE_RATE_THRESHOLD: float = 0.5
    DEPRECATION_MIN_NEGATIVE_COUNT: int = 3
    ARCHIVE_STALE_DAYS: int = 90
    # Rollout observation counts required before artifact can be stabilised or
    # a staged replacement considered ready.  Kept separate from the generic
    # STABLE_MIN_OBSERVATION_COUNT so each gate can be tuned independently.
    STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT: int = 2
    REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN: int = 2

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性"""
        raise AttributeError("SkillLifecycleThresholds is immutable")


class SkillEvaluationConstants:
    """技能评估常量配置（不可变）

    使用类属性实现不可变配置，避免 Python 3.6 不支持 dataclasses 的问题
    """

    MIN_USAGE_FOR_EVALUATION: int = 5
    EVALUATION_LOOKBACK_DAYS: int = 30
    SUCCESS_RATE_THRESHOLD: float = 0.7

    def __setattr__(self, name, value):
        """禁止修改属性，确保不可变性"""
        raise AttributeError("SkillEvaluationConstants is immutable")


# 允许在技能包中使用的工具集合（不可变）
ALLOWED_SKILL_PACKAGE_TOOLS: frozenset = frozenset({
    "Read",
    "Write",
    "Edit",
    "Bash",
    "WebFetch",
    "WebSearch",
    "Agent",
    "AskUserQuestion",
})
