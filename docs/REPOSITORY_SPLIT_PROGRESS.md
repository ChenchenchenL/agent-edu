# Repository拆分进度跟踪

## 状态：部分完成（框架已建立）

## 目标
将 repositories.py (4,268行，44个Repository类) 拆分为6个领域模块

## 分组方案

### 1. skill.py - 技能相关 (3个类)
- SkillArtifactRepository
- SkillUsageEventRepository  
- SkillCuratorRecommendationRepository

### 2. memory.py - 记忆相关 (10个类)
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

### 3. planning.py - 规划相关 (4个类)
- StudyPlanRepository
- PlanStageRepository
- DailyTaskRepository
- WorkflowRunRepository

### 4. reflection.py - 反思相关 (9个类)
- ReflectionRecordRepository
- ReflectionActionRepository
- ReflectionEvidenceSignalRepository
- ReflectionProposalRepository
- ReflectionProposalEvaluationRepository
- ReflectionProposalRolloutRepository
- ReflectionProposalRolloutObservationRepository
- ReflectionProposalRolloutDecisionRepository
- ReflectionOutcomeEvaluationRepository

### 5. learner.py - 学习者相关 (2个类)
- LearnerProfileRepository
- LearnerGoalRepository

### 6. audit.py - 审计相关 (1个类)
- AuditRepository

### 7. session.py - 会话相关 (3个类)
- SessionRepository
- SessionMessageRepository
- SessionQuizRepository

## 已完成
- ✅ 创建 repositories/ 目录
- ✅ 创建测试文件 test_repositories_split.py
- ✅ 设计分组方案

## 待完成
- [ ] 提取每个Repository类到对应模块
- [ ] 创建 __init__.py 统一导出
- [ ] 保留原 repositories.py 作为 re-export 层
- [ ] 运行测试确保向后兼容
- [ ] 更新文档

## 实现建议

由于文件很大，建议：
1. 使用脚本自动提取类定义
2. 逐个模块实施，每个模块单独测试
3. 优先拆分 skill 和 memory（最常用）
4. 使用 git worktree 隔离变更

## 向后兼容策略

原 repositories.py 改为：
```python
# Re-export layer for backward compatibility
from agent_core.infrastructure.db.repositories.skill import *
from agent_core.infrastructure.db.repositories.memory import *
# ... 其他模块
```
