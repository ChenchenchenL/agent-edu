# Task 12: TaskPlanLifecycleService 真实迁移总结

## 迁移状态：部分完成

### ✅ 已完成迁移的方法（真实业务逻辑）

#### 只读方法（低风险）
1. **`get_plan(plan_id)`** - 获取单个学习计划
   - 从 `task.py:313-317` 迁移
   - 依赖：study_plan_repository, plan_stage_repository
   - 包含：查询计划、获取阶段、构造响应

2. **`list_plans(goal_id)`** - 列出目标的所有计划
   - 从 `task.py:308-311` 迁移
   - 依赖：goal_repository, study_plan_repository, plan_stage_repository
   - 包含：验证目标存在、查询计划列表、构造响应

3. **`get_task(task_id)`** - 获取单个任务
   - 从 `task.py:341-345` 迁移
   - 依赖：daily_task_repository
   - 包含：查询任务、NotFoundError处理

4. **`list_tasks(goal_id, filters)`** - 列出任务（带过滤）
   - 从 `task.py:319-339` 迁移
   - 依赖：goal_repository, daily_task_repository
   - 包含：验证目标、条件过滤、日期转换

#### 只读辅助方法（迁移完成）
5. **`list_workflow_runs(goal_id)`** - 列出工作流运行记录
   - 依赖：goal_repository, workflow_run_repository
   
6. **`get_workflow_run(run_id)`** - 获取单个工作流运行

#### 私有辅助方法（迁移完成）
- **`_require_goal(goal_id)`** - 验证目标存在
- **`_to_plan_response(plan)`** - 构造计划响应（含阶段）
- **`_to_datetime(date)`** - 日期转datetime

---

### ⏳ 待迁移方法（复杂逻辑，标记为NotImplementedError）

1. **`generate_plan()`** - 生成学习计划
   - 复杂度：HIGH（200+行）
   - 依赖：planner_service, workflow_run_service, memory_service, audit_service
   - 副作用：创建计划、更新状态、审计日志、工作流

2. **`update_task_status()`** - 更新任务状态
   - 复杂度：MEDIUM（50+行）
   - 依赖：audit_service, 可能需要状态转换逻辑
   - 副作用：更新任务、记录审计

---

## 架构变化

### Before（假迁移 - Facade层）
```python
class TaskPlanLifecycleService:
    def __init__(self, *, core: AutonomousTaskService):
        self._core = core  # 39个参数的God Class
    
    async def get_plan(self, plan_id):
        return await self._core.get_plan(plan_id)  # 直接委托
```

### After（真实迁移）
```python
class TaskPlanLifecycleService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        plan_stage_repository: PlanStageRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
    ):
        # 只注入需要的6个依赖，不是39个
        self._db_session = db_session
        self._goal_repository = goal_repository
        # ...
    
    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        """Real implementation from task.py."""
        plan = await self._study_plan_repository.get_by_id(plan_id)
        if plan is None:
            raise NotFoundError(f"Study plan '{plan_id}' not found.")
        return await self._to_plan_response(plan)
```

---

## 依赖注入变化

### Container.task_services() 更新

```python
# Before: 所有facade都依赖core
plan_lifecycle = TaskPlanLifecycleService(core=core)

# After: 专注服务有真实依赖
plan_lifecycle = TaskPlanLifecycleService(
    db_session=self._session,
    goal_repository=LearnerGoalRepository(self._session),
    study_plan_repository=StudyPlanRepository(self._session),
    plan_stage_repository=PlanStageRepository(self._session),
    daily_task_repository=DailyTaskRepository(self._session),
    workflow_run_repository=WorkflowRunRepository(self._session),
)

# Legacy core仍然存在，供其他facade使用（逐步迁移）
core = self._task_core_builder(self._session)
```

---

## 统计数据

| 指标 | 数值 |
|------|------|
| TaskPlanLifecycleService代码行数 | 305行（from 89行） |
| 真实实现的方法 | 6个公开方法 + 3个私有方法 |
| NotImplementedError占位 | 2个方法（复杂逻辑待迁移） |
| 构造函数参数 | 6个（from 1个core） |
| Repository依赖 | 5个 |
| Service依赖 | 0个（只读操作不需要） |
| 代码中的repository调用 | 7处 |
| 代码中的core委托 | 0处（真实迁移） |

---

## 向后兼容性

### AutonomousTaskService保持不变
- 仍然是39参数的God Class
- 仍然包含所有原有方法实现
- API routes仍然可以使用

### 新旧服务共存
- 新代码使用 `TaskPlanLifecycleService`（真实实现）
- 旧代码仍可使用 `AutonomousTaskService.get_plan()`
- 逐步迁移，无破坏性变更

---

## 风险评估

### LOW - 已迁移方法
- 只读操作，无副作用
- 逻辑简单，易于测试
- 无依赖服务，只依赖repositories

### HIGH - 待迁移方法
- `generate_plan()`: 200+行，多服务依赖，复杂副作用
- `update_task_status()`: 审计日志、状态转换逻辑

---

## 下一步行动

### 立即可做
1. ✅ **测试已迁移方法** - API integration测试
2. ✅ **提交部分迁移** - 保存阶段性成果

### 后续迁移
3. **迁移 `update_task_status()`** - 需要audit_service依赖
4. **分析 `generate_plan()` 依赖** - 识别所有必要服务
5. **迁移 `generate_plan()`** - 最复杂，最后处理

### 预计工作量
- 当前部分迁移：2小时 ✅
- `update_task_status()`: 1小时
- `generate_plan()`: 3-4小时
- **Task 12总计**: 6-7小时（当前完成约30%）

---

## 成功标准

### 已达成 ✅
- [x] TaskPlanLifecycleService有真实依赖注入
- [x] 不再只是facade层（0处core委托）
- [x] 迁移了简单只读方法（6个）
- [x] Container正确构建真实依赖
- [x] 代码行数增长（89→305行）

### 待达成 ⏳
- [ ] 所有方法迁移完成
- [ ] AutonomousTaskService作为兼容层（委托给专注服务）
- [ ] 迁移测试全部通过
- [ ] API集成测试无回归

---

## 参考

- 原God Class: `task.py` (3623行)
- 迁移后服务: `task_plan_lifecycle.py` (305行)
- 容器: `container.py`
- 迁移测试: `tests/test_task_migration.py`
- 完整方案: `docs/TASK_SERVICE_MIGRATION_PLAN.md`
