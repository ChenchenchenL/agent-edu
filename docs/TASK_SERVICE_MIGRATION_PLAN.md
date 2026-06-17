# Task Service 真实迁移方案

> 状态说明（2026-06-15）：
> 这份文档保留为迁移阶段的历史方案和分析基线，不再代表当前代码现状。
> 当前真实状态请优先参考：
>
> - `docs/REMAINING_TASKS.md`
> - `docs/PROGRESS_STATUS.md`
> - `ARCHITECTURE.md`
> - `packages/agent_core/src/agent_core/application/services/task_plan_lifecycle.py`
> - `packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py`
> - `packages/agent_core/src/agent_core/application/services/task_runtime_skill.py`
>
> 具体偏差：
>
> - 文档开头描述的“4 个服务都是 facade”已经不成立
> - `TaskPlanLifecycleService.generate_plan()` 已经不是简单委托
> - `TaskAutonomySchedulingService` 已迁入多项真实逻辑，但仍处于 callback 协调的过渡态
> - `TaskRuntimeSkillService` 仍然基本符合本文档描述的 facade 状态

## 历史起点

### ❌ 当时的问题：假迁移（Facade层）
以下描述的是这份方案编写时的起始状态，不代表当前代码：
```python
class TaskPlanLifecycleService:
    def __init__(self, *, core: AutonomousTaskService):
        self._core = core
    
    async def generate_plan(self, ...):
        return await self._core.generate_plan(...)  # 直接委托
```

### ✅ 当时目标：真实迁移
将业务逻辑从 `AutonomousTaskService` 移到4个专注服务，保留旧类作为兼容层。

---

## 依赖分析

### 1. TaskPlanLifecycleService 依赖

#### 方法清单
- `generate_plan()` - 生成学习计划
- `list_plans()` - 列出计划
- `get_plan()` - 获取单个计划
- `list_tasks()` - 列出任务
- `get_task()` - 获取单个任务
- `update_task_status()` - 更新任务状态
- `list_workflow_runs()` - 列出工作流运行
- `get_workflow_run()` - 获取工作流运行

#### 依赖项（通过分析 generate_plan 推导）

**Repositories (7个):**
- `goal_repository: LearnerGoalRepository` - 获取目标
- `study_plan_repository: StudyPlanRepository` - 计划CRUD
- `plan_stage_repository: PlanStageRepository` - 计划阶段
- `daily_task_repository: DailyTaskRepository` - 任务CRUD
- `workflow_run_repository: WorkflowRunRepository` - 工作流记录
- `goal_autonomy_state_repository: GoalAutonomyStateRepository` - 自主状态
- `autonomy_job_repository: ScheduledAutonomyJobRepository` - 调度任务

**Services (5个 - 通过Protocol):**
- `planner_service: PlannerServiceProtocol` - 计划生成核心
- `workflow_run_service: WorkflowRunServiceProtocol` - 工作流管理
- `memory_service: MemoryServiceProtocol | None` - 记忆解读
- `rollout_observation_scheduler: RolloutObservationSchedulerProtocol | None` - Rollout观测
- `audit_service: AuditService` - 审计日志

**Infrastructure:**
- `db_session: AsyncSession` - 数据库会话

---

### 2. TaskExecutionService 依赖

#### 方法清单
- `execute_task()` - 执行任务
- `_execute_quiz_task()` - 执行测验任务
- `_execute_chat_task()` - 执行聊天任务
- `_execute_workflow_task()` - 执行工作流任务

#### 依赖项（需要进一步分析）

**Repositories (估计8+):**
- `daily_task_repository` - 任务状态管理
- `goal_repository` - 目标信息
- `task_attempt_repository` - 任务尝试记录
- `study_plan_repository` - 计划信息
- `workflow_run_repository` - 工作流执行
- 其他...

**Services (估计10+):**
- `session_service: SessionServiceProtocol` - 会话管理
- `chat_service: ChatServiceProtocol` - 聊天服务
- `quiz_service: QuizServiceProtocol` - 测验服务
- `reflection_service: ReflectionServiceProtocol` - 反思服务
- `reflection_evidence_service` - 证据收集
- `tool_plan_runtime_executor` - 工具执行
- `skill_usage_service` - 技能使用
- `runtime_registry` - 运行时注册
- 其他...

---

### 3. TaskAutonomySchedulingService 依赖

#### 方法清单
- `schedule_next_autonomy_task()` - 调度下一个自主任务
- `get_learner_availability()` - 获取学习者可用性
- `update_learner_availability()` - 更新可用性
- `get_autonomy_state()` - 获取自主状态
- `trigger_manual_replan()` - 手动触发重新规划

#### 依赖项（需分析）

**Repositories:**
- `goal_autonomy_state_repository`
- `learner_availability_repository`
- `learner_topic_mastery_repository`
- `autonomy_job_repository`
- `daily_task_repository`

**Services:**
- `autonomy_job_service: AutonomyJobServiceProtocol`
- `planner_service` - 重新规划
- 其他...

---

### 4. TaskRuntimeSkillService 依赖

#### 方法清单
- `resolve_skill_for_task()` - 解析任务技能
- `build_execution_plan()` - 构建执行计划

#### 依赖项

**Services:**
- `goal_skill_binding_resolver: GoalSkillBindingResolverProtocol`
- `runtime_registry: DynamicRuntimeRegistryProtocol`
- `rollout_resolver: RolloutResolverProtocol`

**Repositories:**
- `goal_repository`
- `daily_task_repository`

---

## 架构反转设计

### 当前架构（错误）
```
Facade Services (4个)
    ↓ 依赖
AutonomousTaskService (39参数 God Class)
    ↓ 依赖
Repositories + Services
```

### 目标架构（正确）
```
AutonomousTaskService (兼容层, 0业务逻辑)
    ↓ 委托
Facade Services (4个, 包含真实业务逻辑)
    ↓ 依赖
Repositories + Protocol Services
```

---

## 迁移策略

### Phase 1: 创建迁移测试保护网
```python
# tests/test_task_migration.py
async def test_generate_plan_behavioral_compatibility():
    """确保新旧实现输出一致."""
    # 使用相同输入
    # 对比 AutonomousTaskService 和 TaskPlanLifecycleService
    # 验证返回值、数据库变更、副作用一致
```

### Phase 2: 单方法迁移（TDD）

#### Step 1: 选择最简单方法开始
- `get_plan(plan_id)` - 只读，无副作用，最安全

#### Step 2: 重构 TaskPlanLifecycleService
```python
class TaskPlanLifecycleService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        plan_stage_repository: PlanStageRepository,
        # ... 其他必要依赖
    ):
        self._db_session = db_session
        self._goal_repository = goal_repository
        # ...
    
    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        """真实实现，从 task.py 迁移过来."""
        plan = await self._study_plan_repository.get(plan_id)
        if plan is None:
            raise NotFoundError(f"Plan {plan_id} not found")
        stages = await self._plan_stage_repository.list_by_plan(plan.id)
        return StudyPlanResponse(...)  # 真实构造逻辑
```

#### Step 3: 更新 AutonomousTaskService 为兼容层
```python
class AutonomousTaskService:
    def __init__(
        self,
        *,
        plan_lifecycle: TaskPlanLifecycleService,
        execution: TaskExecutionService,
        autonomy_scheduling: TaskAutonomySchedulingService,
        runtime_skill: TaskRuntimeSkillService,
        # 只保留未迁移方法需要的依赖
    ):
        self._plan_lifecycle = plan_lifecycle
        self._execution = execution
        self._autonomy_scheduling = autonomy_scheduling
        self._runtime_skill = runtime_skill
    
    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        """兼容层：委托给新服务."""
        return await self._plan_lifecycle.get_plan(plan_id)
```

#### Step 4: 更新 Container
```python
class RequestScopeContainer:
    def task_services(self) -> TaskServiceBundle:
        if self._task_services is None:
            # 先构建4个专注服务（真实实现）
            plan_lifecycle = TaskPlanLifecycleService(
                db_session=self._session,
                goal_repository=LearnerGoalRepository(self._session),
                study_plan_repository=StudyPlanRepository(self._session),
                # ...
            )
            
            execution = TaskExecutionService(...)
            autonomy_scheduling = TaskAutonomySchedulingService(...)
            runtime_skill = TaskRuntimeSkillService(...)
            
            # 再构建兼容层（委托）
            core = AutonomousTaskService(
                plan_lifecycle=plan_lifecycle,
                execution=execution,
                autonomy_scheduling=autonomy_scheduling,
                runtime_skill=runtime_skill,
            )
            
            self._task_services = TaskServiceBundle(
                core=core,
                plan_lifecycle=plan_lifecycle,
                execution=execution,
                autonomy_scheduling=autonomy_scheduling,
                runtime_skill=runtime_skill,
            )
        return self._task_services
```

#### Step 5: 运行测试
```bash
pytest tests/test_task_migration.py::test_get_plan_behavioral_compatibility -v
pytest tests/test_api_integration.py -v  # 确保API不受影响
```

#### Step 6: 提交单方法迁移
```bash
git add -A
git commit -m "refactor: migrate get_plan to TaskPlanLifecycleService"
```

#### Step 7: 重复 Step 1-6，迁移下一个方法

### Phase 3: 渐进式迁移顺序

#### TaskPlanLifecycleService（简单→复杂）
1. ✅ `get_plan()` - 只读，最简单
2. ✅ `list_plans()` - 只读
3. ✅ `get_task()` - 只读
4. ✅ `list_tasks()` - 只读，有过滤条件
5. ✅ `update_task_status()` - 写操作，但逻辑简单
6. ✅ `generate_plan()` - 最复杂，最后迁移

#### TaskExecutionService
1. `execute_task()` - 主方法，调用其他3个
2. `_execute_quiz_task()`
3. `_execute_chat_task()`
4. `_execute_workflow_task()`

#### TaskAutonomySchedulingService
1. `get_learner_availability()`
2. `update_learner_availability()`
3. `get_autonomy_state()`
4. `trigger_manual_replan()`
5. `schedule_next_autonomy_task()` - 最复杂

#### TaskRuntimeSkillService
1. `resolve_skill_for_task()`
2. `build_execution_plan()`

---

## 风险管理

### High Risk
- **迁移 `generate_plan()` 时漏掉副作用**（如审计日志、状态同步）
- **循环依赖**（如 execute_task 调用 generate_plan）
- **Container builder 中的依赖注入顺序错误**

### Mitigation
- 每个方法迁移前写测试
- 使用 `git worktree` 隔离迁移工作
- 迁移后运行全量集成测试
- Code review 检查所有数据库副作用

---

## 完成标准

### Task 12-15 完成定义
- [ ] 所有方法从 `task.py` 迁移到4个facade服务
- [ ] `AutonomousTaskService` 只包含委托代码（< 200行）
- [ ] 迁移测试全部通过
- [ ] API集成测试全部通过
- [ ] `dependencies.py` 中的builder完成重构
- [ ] Container正确构建反转后的依赖

### 成功指标
- `task.py` 从 3623行 → < 200行
- 4个facade服务每个 < 800行
- 高风险路径具备充分的风险驱动测试覆盖
- 无性能回归
- 向后兼容（旧代码仍可通过 `AutonomousTaskService` 调用）

---

## 下一步行动

### 立即执行
1. ✅ **创建迁移测试框架** - `tests/test_task_migration.py`
2. ✅ **迁移第一个方法** - `get_plan()` 作为示范
3. ✅ **验证测试通过**
4. ✅ **提交第一个迁移**
5. 🔄 **重复流程，逐方法迁移**

### 时间估算
- 测试框架: 1小时
- 单方法迁移（简单）: 30分钟
- 单方法迁移（复杂如generate_plan）: 2-3小时
- 总计: Task 12-15 预计 15-20小时

---

## 参考

- 原God Class: `packages/agent_core/src/agent_core/application/services/task.py`
- 当前Facade: `packages/agent_core/src/agent_core/application/services/task_*.py`
- Container: `packages/agent_core/src/agent_core/infrastructure/container.py`
- API Routes: `packages/agent_core/src/agent_core/api/routes/*.py`
