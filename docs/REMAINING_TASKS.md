# 剩余未完成任务清单

## 文档定位

这份文档只回答一个问题：

> 按当前仓库代码状态，哪些重构任务已经真正完成，哪些只是部分迁移，哪些仍未开始。

它不是历史记录，也不是愿景文档。若与旧总结冲突，以当前代码为准。

---

## 当前总体判断

当前最需要避免的误判有两个：

1. 不要把 `TaskPlanLifecycleService` 已实迁，误读成整个任务服务体系已经完成解耦。
2. 不要把 `TaskAutonomySchedulingService` 的方法迁移完成，误写成 `AutonomousTaskService` 已经退出主舞台。

实际状态是：

- `TaskPlanLifecycleService`：主路径已经真实迁移
  - `get/list plan`
  - `get/list task`
  - `update_task_status()`
  - `generate_plan()`
- `TaskAutonomySchedulingService`：已有较多真实逻辑，但仍通过 callback 协调 legacy core
- `TaskRuntimeSkillService`：已完全完成拆解与清理收口 (移除 `core` 注入、清理容器接线、同步文档与注释)
- `AutonomousTaskService`：仍然存在，且仍是大类兼容核心，不是空壳委托层
- `skills.py`：仍是 4700+ 行巨型文件，Task #8 没动

---

## 任务状态

### #7 - 拆分 repositories.py ✅ 已完成

- 已按 7 个领域拆分到 `infrastructure/db/repositories/`
- `repositories.py` 保留为 re-export 兼容层
- 当前判断：完成

### #8 - 拆分 skills.py ❌ 未开始

- 当前文件规模：`application/services/skills.py` 约 4710 行
- 目标状态：拆为多个聚焦服务模块，旧入口保留兼容层
- 当前判断：未开始，不应被包装成“接近完成”

### #9 - 拆分领域实体文件 ✅ 已完成

- `domain/entities/` 已按 7 个领域拆为子包
- 旧导入路径通过 `__init__.py` facade 保持兼容
- 当前判断：完成

### #12 / #17 - TaskPlanLifecycleService 迁移 🔄 部分完成

已完成：

- 只读 plan/task/workflow 查询已迁移
- `update_task_status()` 已迁移到 `TaskPlanLifecycleService`
- `update_task_status()` 的 attempt/mastery/post-update 已抽到 support service
- `generate_plan()` 已迁移到 `TaskPlanLifecycleService`

未完成：

- `generate_plan()` 仍依赖 callback 协调：
  - goal state sync
  - rollout observation
  - workflow failure reflection
- `AutonomousTaskService` 中仍保留旧实现和对照路径
- 服务边界尚未完全收口

当前判断：

- 不能再把这块写成“待迁移”
- 也不能写成“完全完成”

### #13 - TaskExecutionService ✅ 基本完成

- 执行逻辑已独立为专门服务
- 仍可能保留少量与 legacy core 的兼容协作，但主责任已独立
- 当前判断：按当前 Phase 3 目标，基本完成

### #14 - TaskAutonomySchedulingService 🔄 部分完成

已真实迁移的方法包括：

- `get_goal_autonomy_state()`
- `get_goal_availability()`
- `update_goal_availability()`
- `list_goal_mastery()`
- `pause_goal_autonomy()`
- `resume_goal_autonomy()`
- `list_autonomy_jobs()`
- `materialize_today()`
- `manual_replan_goal()`
- `run_periodic_goal_reflection()`
- `run_due_autonomy_jobs()`

但未完成点很明确：

- 复杂副作用仍通过 callback 回调到 legacy core
- 容器仍把关键协调逻辑绑定回 `AutonomousTaskService._...`
- `AutonomousTaskService` 仍不是纯委托空壳

当前判断：

- 方法迁移层面可以视为完成
- 架构解耦层面不能视为完成

### #15 - TaskRuntimeSkillService ✅ 已完全完成

当前状态：

- 以下方法均已具备独立实现，不再调用 `AutonomousTaskService` 私有方法：
  - `resolve_autonomy_execution_plan()`
  - `execute_runtime_tool_plan()`
  - `build_tool_plan_execution_context()`
  - `resolve_review_skill_for_runtime()`
  - `resolve_replan_skill_for_runtime()`
  - `resolve_assessment_skill_for_runtime()`
  - `schedule_surface_rollout_observation()`
  - `schedule_runtime_failure_rollout_observation()`
  - `get_rollout_overlay_payload()`
  - `get_skill_binding()`
  - `review_intervals()`

已完成：
- 构造器已支持独立依赖注入
- Container 已完成 wire-up
- 去除 `TaskRuntimeSkillService.__init__()` 中未使用的 `core` 参数
- 去除 `container.py` 中传给 `TaskRuntimeSkillService(...)` 的 `core` 传参
- 修正文档和文件头中仍残留的 facade/迁移中表述

### #16 - 最终清理和文档 🔄 持续进行

已完成：

- Repository 拆分后的文档和测试同步已做
- 若干状态文档已开始回收过时结论

未完成：

- 多份迁移文档仍带有历史阶段口径
- 文档与代码的完成度数字尚未完全统一

### #18 - generate_plan 迁移主路径 ✅ 已完成，边界清理未完成

已完成：

- `TaskPlanLifecycleService.generate_plan()` 已接管主流程
- 已注入 `planner_service` / `workflow_run_service` / `memory_service`

未完成：

- 仍通过 callback 协调跨服务副作用
- 旧 core 中仍保留旧实现

当前判断：

- 不应再作为“待启动的主迁移任务”
- 后续工作应改为“边界清理和 legacy 收口”

---

## 下一步优先级

### 高优先级

1. 收口 `TaskPlanLifecycleService.generate_plan()` 的 callback 边界
2. 收口 `TaskAutonomySchedulingService` 对 legacy core 的 callback 依赖
3. 拆分 `skills.py`

### 中优先级

1. 清理 `AutonomousTaskService` 中已迁移但仍保留的对照实现
2. 统一架构文档、进度文档和历史迁移文档口径

### 低优先级

1. 再做新的“完成度百分比”汇报

在 `skills.py` 和 task/autonomy callback 边界这两块没动之前，继续堆百分比没有意义。

---

## 风险提醒

当前最容易误导后续实现的不是代码，而是文档口径：

- 有的文档把“方法迁移”写成“服务解耦完成”
- 有的文档把“主路径已迁移”写成“仍待迁移”
- 有的文档仍把历史方案当现状描述

后续排期和设计讨论应优先引用：

- 当前服务代码
- `container.py` 的真实接线
- 这份 `REMAINING_TASKS.md`
