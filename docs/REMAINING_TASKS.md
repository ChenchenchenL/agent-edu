# 剩余未完成任务清单

## ⏳ 待完成任务总览

**已完成**: 11/19 (58%)  
**待完成**: 8/19 (42%)

> 运行时修正（2026-06-12）：
> `TaskPlanLifecycleService` 的 6 个读方法、`update_task_status()` 主路径、`generate_plan()`
> 主流程都已真实迁移；其中 attempt/mastery/post-update 已抽到独立 support service。
> 当前剩余问题不再是 `generate_plan()` 兼容委托，而是 autonomy/runtime-skill 两个 façade
> 仍未真实下沉，以及部分深层协作逻辑仍通过 callback 与 legacy core 协调。

---

## Phase 2: 大文件拆分 (0/3) - 建议延后 ⏸️

### #7 - 拆分 repositories.py
**现状**: 4,268行，44个Repository类  
**目标**: 拆分为6个模块（skill, memory, planning, reflection, learner, audit, session）  
**复杂度**: HIGH  
**预计时间**: 8-12小时  
**状态**: 框架已建立，测试准备完成  
**建议**: 使用自动化工具或新会话处理

### #8 - 拆分 skills.py
**现状**: 4,678行  
**目标**: 拆分为8个模块  
**复杂度**: HIGH  
**预计时间**: 10-15小时  
**状态**: 未开始  
**建议**: 延后到Phase 3完成后

### #9 - 拆分领域实体文件
**复杂度**: MEDIUM  
**预计时间**: 3-5小时  
**状态**: 未开始

---

## Phase 3: 架构重构 (5/10) - 继续推进 🔄

### #14 - TaskAutonomySchedulingService ⭐⭐⭐
**方法清单** (12个):

✅ **简单方法** (可快速迁移 - 1-2小时):
- `get_goal_autonomy_state()` - 获取自主状态
- `get_goal_availability()` - 获取学习者可用性
- `list_goal_mastery()` - 列出主题掌握度

⚠️ **中等方法** (需要验证和审计 - 3-4小时):
- `update_goal_availability()` - 更新可用性
- `pause_goal_autonomy()` - 暂停自主
- `resume_goal_autonomy()` - 恢复自主
- `list_autonomy_jobs()` - 列出自主任务
- `materialize_today()` - 物化今日工作窗口
- `manual_replan_goal()` - 手动重新规划

🔴 **复杂方法** (需要集成 - 建议callback):
- `run_periodic_goal_reflection()` - 定期反思
- `run_due_autonomy_jobs()` - 运行到期任务

**总预计**: 4-6小时  
**建议**: 先迁移3个简单方法（1-2小时），中等方法用callback

---

### #15 - TaskRuntimeSkillService ❌
**方法清单**: 18个复杂内部方法

**包括**:
- `resolve_autonomy_execution_plan()`
- `execute_runtime_tool_plan()`
- `build_tool_plan_execution_context()`
- `resolve_review_skill_for_runtime()`
- ... 等18个

**特点**: 
- 所有方法都是内部辅助方法
- 调用core的私有方法
- 高度耦合skill binding、runtime registry等模块

**复杂度**: VERY HIGH  
**建议**: **不适合当前迁移**，需要先重构skill相关模块

---

### #16 - 最终清理和文档 ⭐⭐⭐
**任务**:
- 清理临时代码
- 更新ARCHITECTURE.md
- 创建迁移完成报告
- 性能测试和benchmark
- API集成测试补充

**复杂度**: LOW  
**预计时间**: 2-3小时  
**价值**: 高（总结和文档化）

---

### #18 - 迁移 generate_plan ⭐⭐
**现状**: ✅ **主流程已迁移完成**
- `TaskPlanLifecycleService.generate_plan()` 已接管主流程
- 已显式注入 `planner_service` / `workflow_run_service` / `memory_service`
- goal state 同步、rollout 观测、workflow failure reflection 目前通过 callback 协调

**依赖**:
- planner_service (核心)
- workflow_run_service (工作流管理)
- memory_service (可选，记忆解读)
- audit_service (审计日志)
- rollout_observation_scheduler (可选，rollout观测)

**复杂性**:
- 仍存在协作边界: goal state 同步 / rollout 观测 / failure reflection
- 这些副作用尚未形成独立服务，目前通过 callback 维持边界
- `AutonomousTaskService` 中仍保留旧实现，可作为对照，但不再是 API 主路径依赖

**状态**: 已完成主迁移，剩余为清理/收口  
**建议**: 不再单列为头号任务；后续在 Task 16 中收口文档和 callback 边界

---

## 📊 完成度统计

| 类别 | 完成 | 待完成 | 总计 | 进度 |
|------|------|--------|------|------|
| Phase 1 | 6 | 0 | 6 | 100% ✅ |
| Phase 2 | 0 | 3 | 3 | 0% ⏸️ |
| Phase 3 | 5 | 5 | 10 | 50% 🔄 |
| **总计** | **11** | **8** | **19** | **58%** |

---

## 🎯 优先级建议

### 🥇 高优先级（下次会话推荐）

#### 1. Task 14部分 - 简单方法迁移
- **内容**: 迁移3个简单get方法
- **预计**: 1-2小时
- **价值**: 快速增加完成度，积累经验
- **难度**: LOW

#### 2. Task 16 - 清理和文档
- **内容**: 更新架构文档，创建迁移报告
- **预计**: 2-3小时
- **价值**: 总结当前成果，为后续工作准备
- **难度**: LOW

**合计**: 3-5小时，完成后进度→68%

---

### 🥈 中优先级（需要规划）

#### 3. Task 14完整 - TaskAutonomySchedulingService
- **内容**: 迁移中等复杂度方法
- **预计**: 4-6小时
- **需要**: 回调模式处理状态同步
- **难度**: MEDIUM

#### 4. Task 18 - generate_plan迁移
- **内容**: 完整迁移generate_plan方法
- **预计**: 8-12小时（独立会话）
- **价值**: 完成TaskPlanLifecycleService
- **难度**: VERY HIGH

**合计**: 12-18小时，完成后进度→79%

---

### 🥉 低优先级（建议延后）

#### 5. Task 15 - TaskRuntimeSkillService
- **原因**: 不适合当前迁移
- **需要**: 先重构skill模块
- **建议**: Phase 4独立处理

#### 6. Task 7-9 - 大文件拆分
- **原因**: 机械性工作，价值相对较低
- **建议**: 使用自动化工具或批量处理

---

## 💡 完成路径建议

### 方案A: 快速收尾（推荐）✅
**目标**: 完成Phase 3核心任务，达到70%总进度

**步骤**:
1. Task 14部分（1-2h）
2. Task 16（2-3h）
3. 创建Phase 4规划

**结果**: 13/19 = **68%**，Phase 3完成 **60%**  
**投入**: 3-5小时  
**性价比**: ⭐⭐⭐⭐⭐

---

### 方案B: 完整Phase 3
**目标**: 完成所有可迁移的Phase 3任务

**步骤**:
1. Task 14完整（4-6h）
2. Task 18（8-12h，独立会话）
3. Task 16（2-3h）

**结果**: 15/19 = **79%**，Phase 3完成 **80%**（跳过Task 15）  
**投入**: 15-20小时（2-3个会话）  
**性价比**: ⭐⭐⭐⭐

---

### 方案C: 全面完成
**目标**: 完成所有任务

**步骤**:
1. Phase 3剩余任务（15-20h）
2. Phase 2大文件拆分（20-30h）

**结果**: 19/19 = **100%**  
**投入**: 35-50小时（5-8个会话）  
**性价比**: ⭐⭐

**评估**: 投入产出比较低，不推荐

---

## 🎯 我的推荐

### 推荐策略：方案A + 部分方案B

#### 第一步：快速收尾（下次会话）
- ✅ Task 14部分（3个简单方法）
- ✅ Task 16（清理和文档）
- **预计**: 3-5小时
- **进度**: 58% → 68%

#### 第二步：中期规划（独立会话）
- 📋 Task 18（generate_plan迁移）
- 📋 Task 14完整（中等复杂度方法）
- **预计**: 12-18小时
- **进度**: 68% → 79%

#### 第三步：延后处理
- ⏸️ Task 15（需要skill模块重构）
- ⏸️ Task 7-9（大文件拆分，使用工具）

---

## ✅ 推荐理由

1. **快速达到70%完成度** - 体现阶段性成果
2. **完成Phase 3核心价值** - 架构重构主要目标达成
3. **为后续工作建立清晰基础** - 文档和测试完善
4. **避免陷入低价值工作** - 跳过机械性拆分任务
5. **保持灵活性** - 可根据实际需求调整优先级

---

## 📅 时间规划示例

### 下次会话（3-5小时）
- 0-1h: Task 14部分 - get_goal_autonomy_state
- 1-2h: Task 14部分 - get_goal_availability + list_goal_mastery
- 2-4h: Task 16 - 更新文档、测试、报告
- 4-5h: 提交、总结

### 后续会话（8-12小时）
- 独立处理Task 18 - generate_plan迁移

---

**总结**: 建议先完成**方案A**（3-5小时），快速达到68%完成度，然后评估是否继续方案B。
