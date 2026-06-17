# Repository拆分进度跟踪

## 状态：✅ 已完成（2026-06-14）

## 目标
将 repositories.py (4,268行，44个Repository类) 拆分为7个领域模块

## 分组方案

### 1. skill.py - 技能相关 (3个类)
- SkillArtifactRepository
- SkillUsageEventRepository  
- SkillCuratorRecommendationRepository

### 2. memory.py - 记忆相关 (11个类)
- MemoryEventRepository
- MemoryEmbeddingRepository
- KnowledgeMemoryRepository
- KnowledgeMemoryEmbeddingRepository
- BehaviorMemoryRepository
- BehaviorMemoryEmbeddingRepository
- MemoryEvidenceLinkRepository
- MemoryGovernanceDecisionRepository
- MemoryAnnotationRepository
- MemoryConflictRepository
- MemoryMaintenanceJobRepository

### 3. planning.py - 规划相关 (4个类)
- StudyPlanRepository
- PlanStageRepository
- DailyTaskRepository
- WorkflowRunRepository

### 4. reflection.py - 反思相关 (15个类)
- ReflectionRecordRepository
- ReflectionActionRepository
- ReflectionEvidenceSignalRepository
- ReflectionProposalRepository
- ReflectionProposalEvaluationRepository
- ReflectionProposalRolloutRepository
- ReflectionProposalRolloutObservationRepository
- ReflectionProposalRolloutDecisionRepository
- ReflectionOutcomeEvaluationRepository
- ReflectionReviewDecisionRepository
- LearnerGoalStrategyCardRepository
- ReflectiveMemoryRepository
- ReflectionProposalSandboxRunRepository
- ReflectionProposalApprovalDecisionRepository
- GoalSkillBindingRepository

### 5. learner.py - 学习者相关 (7个类)
- LearnerProfileRepository
- LearnerGoalRepository
- GoalAutonomyStateRepository
- ScheduledAutonomyJobRepository
- LearnerAvailabilityRepository
- LearnerTopicMasteryRepository
- TaskAttemptRepository

### 6. audit.py - 审计相关 (1个类)
- AuditRepository

### 7. session.py - 会话相关 (3个类)
- SessionRepository
- SessionMessageRepository
- SessionQuizRepository

## 完成结果

| 步骤 | 状态 |
|------|------|
| 创建 repositories/ 目录 | ✅ |
| 创建测试文件 test_repositories_split.py | ✅ |
| 设计分组方案 | ✅ |
| 提取所有44个Repository类到对应模块 | ✅ |
| 创建 __init__.py 统一导出 | ✅ |
| 保留原 repositories.py 作为 re-export 层（65行） | ✅ |
| 所有文件 AST 语法验证通过 | ✅ |
| 52处调用方向后兼容，无需改动 | ✅ |

## 文件规模对比

| 文件 | 行数 |
|------|------|
| 原 repositories.py（拆分前） | 4,268行 |
| 新 repositories.py（re-export层） | 65行 |
| repositories/session.py | 3个类 |
| repositories/skill.py | 3个类 |
| repositories/audit.py | 1个类 |
| repositories/learner.py | 7个类 |
| repositories/planning.py | 4个类 |
| repositories/memory.py | 11个类 |
| repositories/reflection.py | 15个类 |
| repositories/__init__.py | 统一导出 |

## 向后兼容性

原 repositories.py 已改为：
```python
# Re-export layer for backward compatibility.
from agent_core.infrastructure.db.repositories.skill import *
from agent_core.infrastructure.db.repositories.memory import *
# ... 其他模块
```

所有52处现有 `from agent_core.infrastructure.db.repositories import ...` 导入**无需任何修改**即可继续正常工作。
