# Skill Runtime Binding 逐步动态化执行计划

## 1. 文档定位

本文档用于指导 `agent-edu` 当前 skill runtime binding 链路从“保守静态兼容”逐步走向“受治理的动态运行时绑定”。

目标不是重写整个 runtime system，也不是提前完成完整动态技能平台，而是在保持当前 MVP 治理路径、artifact lifecycle、worker 语义和现有 surface 行为兼容的前提下，把 runtime binding 收口成一套：

- 可解释
- 可灰度
- 可回归
- fail-closed
- 不易因 `skills.py` / `task.py` 后续拆分而漂移

本文档只负责 runtime binding 的渐进式动态化。

与其他计划的关系：

- 结构拆分以 [plan/SKILLS_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/SKILLS_PY_SPLIT_PLAN.md) 为主。
- task/autonomy 边界以 [plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md](/home/cl/agent-edu/plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md) 为主。
- MVP 验证入口以 [plan/MVP_VALIDATION_BASELINE_PLAN.md](/home/cl/agent-edu/plan/MVP_VALIDATION_BASELINE_PLAN.md) 为主。
- reflection outcome 到 skill evolution 的质量闭环以 [plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md](/home/cl/agent-edu/plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md) 为主。

优先级：

1. 不绕过 artifact lifecycle、rollout、binding、readiness 和 audit 治理门。
2. 不让 staged / suppressed / incompatible artifact 静默进入生产 runtime。
3. 不让 unchecked tool-plan 或未解释的 binding precedence 改变生产行为。
4. 每扩大一个 surface，都必须有 explain、fallback、audit、usage 和 regression baseline。
5. 默认验证路径不依赖真实外部 provider。

## 2. 当前状态判断

当前 runtime binding 并非未开始，已经有 V1 基线。

已落地事实：

- [packages/agent_core/src/agent_core/application/services/dynamic_runtime_registry.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/dynamic_runtime_registry.py) 已能解析 `RuntimeSkillExecutionPlan`，并给出：
  - `contract_summary`
  - `source_summary`
  - `implementation_binding / execution_kind / artifact_id / artifact_status`
  - `binding_id / rollout_id / dynamic_registry_version / tool_plan_enabled`
- [packages/agent_core/src/agent_core/application/services/goal_skill_binding_resolver.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/goal_skill_binding_resolver.py) 已能基于：
  - `topic_keys`
  - `task_types`
  - `trigger_sources`
  - `required_root_causes`
  做 deterministic first-match binding 选择。
- [packages/agent_core/src/agent_core/application/services/skills.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/skills.py) 中的 `SkillResolver` / `SkillUsageService` 已能：
  - 对 suppressed artifact fail-closed blocking
  - 对 incompatible compatibility contract fail-closed blocking
  - 对 missing artifact 使用 static fallback
  - 基于 artifact + binding 生成 `SkillExecutionPlan`
- [packages/agent_core/src/agent_core/application/services/chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py)、
  [packages/agent_core/src/agent_core/application/services/planner.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/planner.py)、
  [packages/agent_core/src/agent_core/application/services/task.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task.py)、
  [packages/agent_core/src/agent_core/application/services/task_runtime_skill.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_runtime_skill.py)
  已接入 runtime plan consumption。
- 当前已覆盖的 surface：
  - `chat`
  - `hint`
  - `quiz`
  - `plan_generation`
  - `review_scheduling`
  - `assessment_generation`
  - `replan`
- [packages/agent_core/src/agent_core/application/services/tool_plan_runtime.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/tool_plan_runtime.py) 已支持 internal-only tool-plan runtime executor，并具备：
  - payload template 校验
  - prior-step output 引用
  - step 级 audit
  - failure durable audit
  - sandbox/runtime 同构的 dry-run 预览能力
- operator 当前已有：
  - `/skill-resolution` resolution probe
  - `/skill-artifacts/{artifact_id}/replacement-readiness` readiness API

当前测试基础也存在：

- [tests/test_skill_service.py](/home/cl/agent-edu/tests/test_skill_service.py) 已覆盖 suppressed / incompatible / static fallback / readiness / curator recommendation 等关键路径。
- [tests/test_task_runtime_skill.py](/home/cl/agent-edu/tests/test_task_runtime_skill.py) 已覆盖 runtime registry fallback、tool-plan execution、rollout observation 调度。
- [tests/test_tool_plan_runtime.py](/home/cl/agent-edu/tests/test_tool_plan_runtime.py) 已覆盖 runtime tool-plan 执行和 fail-closed 规则。
- [tests/test_chat_service.py](/home/cl/agent-edu/tests/test_chat_service.py) 已覆盖 runtime metadata 注入的部分行为。
- [tests/test_api_integration.py](/home/cl/agent-edu/tests/test_api_integration.py) 已覆盖 replacement readiness route 等 operator API。

但当前状态更准确地说是：

> runtime 已能消费 governed execution plan，但 active artifact 还不是完整动态 runtime source，binding 解释、staged 语义、surface 分级和更深 orchestration 仍未收口。

当前最重要的现实问题：

1. runtime binding 规则分散在 `SkillResolver`、`DynamicRuntimeRegistryService`、`GoalSkillBindingResolver`、`chat/planner/task` 调用点中。
2. `include_staged` 在不同 surface 上使用并不一致，存在治理语义风险。
3. active/stable artifact 对 runtime behavior 的影响仍偏保守，很多地方本质上还是 static implementation binding + overlay。
4. 当前只有 artifact replacement readiness，没有“goal/surface 级 runtime binding explain/readiness”。
5. tool-plan 已可运行，但 surface 级允许范围、升级顺序和 fallback 还不够显式。
6. 运行时 source precedence 仍缺少统一 contract，容易在后续拆分中漂移。
7. 回归覆盖很多，但还没有形成 runtime binding 专项 regression baseline。

## 3. 目标与非目标

### 3.1 目标

本次计划应达成：

1. 把 runtime binding 的 source precedence、eligibility、fallback、blocked reason 变成显式 contract。
2. 先补 explain/probe/readiness，再逐步扩大 governed artifact 对 runtime behavior 的真实影响范围。
3. 让每个 surface 的动态化能力有清晰分级，而不是一次性放开。
4. 对 staged / rolled_out / active / stable artifact 在 runtime 中的语义做明确隔离。
5. 为 tool-plan runtime、binding overlay、rollout overlay、usage metadata 建立专项 regression 基线。

### 3.2 非目标

本次不应做：

- 不做 auto activate / auto replace。
- 不把 staged artifact 直接变成默认生产 runtime source。
- 不引入通用 DAG / branching / looping tool-plan interpreter。
- 不开放外部任意工具执行。
- 不让 unchecked model output 直接改 runtime behavior。
- 不在本计划中重写 `SkillResolver`、`TaskRuntimeSkillService`、`task.py` 全部结构。
- 不把 bundle / global rollout 拉进当前范围。

## 4. 关键边界

### 4.1 Runtime Source 边界

当前 runtime 可能受这些来源影响：

1. static registry 默认 handler
2. selected artifact 的 compatibility contract
3. artifact runtime directives
4. goal skill binding overlay
5. rollout overlay
6. governed tool-plan

这几类来源必须有明确 precedence，不能靠调用方顺序碰运气。

### 4.2 Governed Status 边界

- `suppressed` artifact 必须 fail-closed 阻断。
- `archived / rejected / deprecated` 不得作为正常 selectable runtime source。
- `staged` 不应默认进入生产 runtime；即使保留读取能力，也必须显式区分：
  - probe/shadow
  - include_staged preview
  - production selection
- `active / stable` 才是默认可选生产状态。

### 4.3 Surface 风险边界

不同 surface 风险不同，不能同一策略推进：

- 低风险：
  - `chat`
  - `hint`
  - `quiz`
  - `plan_generation`
- 中高风险：
  - `review_scheduling`
  - `assessment_generation`
  - `replan`

原因：

- autonomy surface 可能产生真实 task/materialization side effect。
- chat/hint/quiz/plan_generation 更多是 response behavior / plan drafting 级影响。

### 4.4 Tool-plan 执行边界

- 只允许 internal-only tool。
- 只允许 allowlisted surface 使用 tool-plan。
- tool-plan 模板变量和 prior-step output 必须强校验。
- tool-plan failure 必须留下 durable audit，不得静默 fallback 为“好像成功了”。
- runtime tool-plan 不应绕过原有 internal tool 的权限/治理语义。

### 4.5 Audit 与 Usage 边界

- runtime resolution blocked/incompatible/missing-artifact 必须可观测。
- usage metadata 必须稳定包含 runtime source contract 摘要。
- rollout observation 不应在没有真实 source anchor 时伪造成功信号。
- 关键 runtime failure 必须有 usage + audit，而不仅是日志。

### 4.6 Operator Explain 边界

- operator 需要能解释当前某个 goal/surface 为什么命中了某个 artifact/binding/tool-plan。
- explain/probe 是只读能力，不应在 probe 时偷偷改变 lifecycle 状态。
- runtime explain 和 artifact replacement readiness 是两类不同 contract，不能混用。

## 5. 需要增强的核心问题

### 5.1 Resolution / Binding Policy 分散

当前 runtime selection 逻辑跨多个对象：

- `SkillResolver.resolve()`
- `SkillResolver.build_execution_plan()`
- `GoalSkillBindingResolver.get_active_binding()`
- `DynamicRuntimeRegistryService.resolve_runtime_plan()`
- `chat/planner/task` 各自的 fallback 调用路径

问题：

- source precedence 不集中。
- blocked/fallback 语义不集中。
- usage metadata contract 由多个调用点拼接，容易漂移。

### 5.2 `include_staged` 语义存在风险

当前仓库中，多个 runtime 路径会传 `include_staged=True`，而 `GoalSkillBindingRepository.list_active_by_goal_and_surface()` 会把 `staged` 与 `rolled_out` 一起返回。

这说明当前系统已经具备“staged binding 可被 runtime 看到”的机制。

问题在于：

- 哪些路径只是为了 probe/preview？
- 哪些路径已经会影响生产 runtime？
- 各 surface 为什么有的传 `True`，有的传 `False`？

如果不先收口这层语义，后续继续动态化时很容易把 staged candidate 误带入生产路径。

### 5.3 Binding Match 仍偏简单

当前 binding 匹配主要依赖：

- `topic_keys`
- `task_types`
- `trigger_sources`
- `required_root_causes`

且采用 deterministic first-match。

缺口：

- specificity/priority 的冲突解释不足。
- overlap/ambiguity 缺乏 operator explain。
- 同 surface 多 binding 的 precedence contract 尚不清晰。
- 还没有对“绑定命中了，但 artifact/runtime contract 不兼容”的统一解释输出。

### 5.4 Runtime Explain / Readiness 缺失

当前 operator 有：

- resolution probe
- replacement readiness

但缺少：

- goal/surface scoped runtime binding explain
- runtime tool-plan readiness
- binding overlay / rollout overlay 的 explain
- fallback decision explain

结果是：

- 当前为何用了 static fallback，不够透明。
- 当前为何没命中 binding，不够透明。
- 当前为何 tool-plan 没启用，不够透明。

### 5.5 Dynamic Artifact Sourcing 仍偏保守

当前 active/stable artifact 已参与 resolution，但还不是“完整动态 runtime source”。

现实表现：

- 很多 surface 仍主要依赖 static implementation binding。
- runtime directives 可以覆盖，但 source precedence 不够显式。
- tool-plan 只在部分 autonomy surface 形成真实行为差异。
- governed artifact 对 runtime behavior 的作用范围还没有按 surface 分阶段放大。

### 5.6 Tool-plan Orchestration 需要更稳的边界

当前已支持受控 multi-step 样板，但仍有明显边界：

- 仅保守白名单。
- 当前主要落在 `replan` 的 `partial_replan -> review_scheduling`。
- 通用多步 interpreter 尚未实现。

问题不是“能力不够”，而是“升级边界还没写死”。

如果没有 surface-by-surface 升级计划，后续很容易把 runtime tool-plan 变成难以治理的混合执行层。

### 5.7 Fallback / Kill Switch / Observability 不够成体系

当前已有：

- blocked/incompatible fail-closed
- missing artifact static fallback
- usage metadata source summary
- metrics/alert baseline

但还缺：

- 每个 surface 对 fallback 的明确策略。
- staged shadow/probe 与 production path 的隔离。
- fallback 频率、binding miss、tool-plan failure 的专项 runtime 观测基线。
- operator 可直接读取的 runtime explain 读 API。

### 5.8 回归基线不成体系

当前测试很多，但主要分散在：

- resolver
- task runtime service
- tool plan runtime
- chat/task API

缺少的是：

- 一套 `surface x source x status x fallback` 的 runtime binding regression matrix。

## 6. 推荐技术实现

### 6.1 总体策略

原则是：

1. 先解释。
2. 再固化 readiness/eligibility。
3. 再做 shadow/probe。
4. 再放大低风险 surface 的动态作用范围。
5. 最后才扩到 autonomy surface 和更深的 tool-plan orchestration。

不要反过来先继续扩 runtime behavior，再补 explain 和 gate。

### 6.2 推荐最小重构

为了让 runtime binding 可以长期维护，建议只做窄提取，不先大拆 orchestration。

稳态目标建议与 [plan/SKILLS_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/SKILLS_PY_SPLIT_PLAN.md) 对齐，后续优先落在：

```text
packages/agent_core/src/agent_core/application/services/skill/
  resolution.py
  runtime_policy.py
  runtime_readiness.py
  runtime_explain.py
  usage.py
```

职责建议：

- `resolution.py`
  - 承载 `SkillResolver`
  - 承载 `SkillUsageService`
- `runtime_policy.py`
  - 承载纯 runtime eligibility / precedence / fallback 规则
  - 不持有 repository / session / audit
- `runtime_readiness.py`
  - 承载 runtime-binding 专用 dataclass 与 reason code 计算
- `runtime_explain.py`
  - 承载 explain payload builder
  - 统一 source summary / fallback reason / blocked reason
- `usage.py`
  - 继续承载 usage metadata contract 的稳定出口

以下模块继续保留 orchestration owner 身份：

- `dynamic_runtime_registry.py`
- `goal_skill_binding_resolver.py`
- `tool_plan_runtime.py`
- `task_runtime_skill.py`

原因：

- runtime binding 的风险主要在纯 policy 漂移。
- 先抽纯 policy/explain，风险最低，收益最高。
- 这样后续 `skills.py` 拆分和 `task.py` 边界收口时有回归基线可依赖。

### 6.3 推荐显式 contract

建议目标新增 runtime-binding 专用 contract 对象，例如：

```python
@dataclass(frozen=True)
class RuntimeBindingReadiness:
    skill_name: str
    surface: str
    learner_goal_id: str | None
    resolution_mode: str
    selected_artifact_id: str | None
    selected_binding_id: str | None
    selected_rollout_id: str | None
    blocked_reason_codes: list[str]
    fallback_mode: str | None
    tool_plan_status: str
    staged_involvement: str
```

```python
@dataclass(frozen=True)
class RuntimeBindingExplainResult:
    skill_name: str
    surface: str
    source_summary: dict[str, object]
    resolution_summary: dict[str, object]
    binding_summary: dict[str, object] | None
    rollout_summary: dict[str, object] | None
    tool_plan_summary: dict[str, object] | None
    blocked_reason_codes: list[str]
    fallback_reason_codes: list[str]
```

这些 contract 的目的不是“多造对象”，而是让：

- operator explain
- regression baseline
- future API response
- usage metadata

都可以围绕同一套语义稳定演进。

### 6.4 推荐 fixtures 目录

建议目标新增：

```text
tests/fixtures/runtime_binding/
  resolution_cases.json
  binding_match_cases.json
  source_precedence_cases.json
  fallback_cases.json
  tool_plan_readiness_cases.json
  surface_matrix_cases.json
```

说明：

- 这些是目标新增，不代表当前仓库已存在。
- 默认仅使用 fake repository / stub provider / mock internal tool registry。

### 6.5 推荐验证入口

建议目标形成以下聚焦入口：

```bash
python3 -m pytest tests/test_skill_service.py -q
python3 -m pytest tests/test_task_runtime_skill.py -q
python3 -m pytest tests/test_tool_plan_runtime.py -q
python3 -m pytest tests/test_chat_service.py -q
python3 -m pytest tests/test_api_integration.py -q
```

后续若专门补专项回归文件，建议进一步收口为：

```bash
python3 -m pytest tests/test_skill_runtime_binding_regression.py -q
```

## 7. 推荐执行阶段

### Phase 0：冻结当前 V1 事实

目标：先把现有真实行为冻结成基线。

执行：

1. 搜索并列出所有 runtime path 的 `include_staged` 使用点。
2. 冻结当前 `resolver_status / selection_reason / source_summary` 取值集合。
3. 列出当前 surface 矩阵：
   - 哪些 surface 只消费 directives
   - 哪些 surface 消费 tool-plan
   - 哪些 surface 调度 rollout observation
4. 记录当前 missing-artifact fallback 行为与 blocked/incompatible 行为。

完成标准：

- 有一份当前 runtime V1 行为基线表。
- staged/rolled_out 语义差异已在文档中显式写明。

### Phase 1：补 runtime explain / probe 能力

目标：先让系统能解释“为什么当前是这个 runtime 行为”。

执行：

1. 增加 goal/surface scoped runtime explain service。
2. explain 结果至少包含：
   - selected artifact
   - selected binding
   - selected rollout
   - source summary
   - blocked reasons
   - fallback reasons
   - tool-plan status
   - include_staged 是否参与
3. 为 operator 增加只读 explain API。
4. 把 explain contract 固化为可测试 response shape。

完成标准：

- operator 不再只能看 `/skill-resolution` 的静态结果。
- 可以解释 current runtime 是否来自 artifact、binding overlay、static fallback。
- explain 路径不修改 governed state。

### Phase 2：固化 runtime eligibility / fallback policy

目标：把 runtime 决策规则从散落实现提升为统一 policy。

执行：

1. 提取纯 policy：
   - selectable artifact status
   - staged 是否允许参与
   - compatibility contract 校验
   - binding overlay precedence
   - rollout overlay precedence
   - missing-artifact fallback
2. 明确 fallback 模式：
   - `static_fallback`
   - `artifact_only`
   - `binding_overlay`
   - `blocked`
3. 固化 blocked reason code 与 fallback reason code。
4. 统一 usage metadata contract 出口。

完成标准：

- 所有 runtime 决策都能落到显式 reason code。
- `SkillResolver` / `DynamicRuntimeRegistryService` / 调用方不再各自发明一套语义。

### Phase 3：收口 `include_staged` 语义，先引入 shadow/probe

目标：先解决 staged 参与 runtime 的治理风险。

执行：

1. 将 `include_staged` 语义拆成两类：
   - `probe/shadow`
   - `production resolution`
2. 默认生产路径只看 `rolled_out` binding。
3. 若确有 staged 参与需求，应改为：
   - 只读 shadow compare
   - dry-run preview
   - operator explain
4. 对仍需保留 staged runtime 可见性的调用点，逐一补 reason 和 audit。

完成标准：

- staged candidate 不会因默认调用参数直接影响生产 runtime。
- shadow/probe 有清晰边界，不再混在主执行路径中。

### Phase 4：低风险 surface 动态化

目标：先扩大低风险 surface 的 governed runtime 影响范围。

范围：

- `chat`
- `hint`
- `quiz`
- `plan_generation`

执行：

1. 先允许 governed artifact 更稳定地覆盖 runtime directives。
2. 保持 static implementation binding 仍为底座，不立即放开任意 execution kind。
3. 对每个 surface 建立：
   - explain contract
   - fallback contract
   - usage metadata contract
   - blocked/incompatible regression
4. `chat / hint / quiz` 继续以 response behavior / directive 为主，不急于引入复杂 tool-plan。

完成标准：

- 低风险 surface 的动态化可解释、可回退、可观测。
- 失败时仍能落回静态默认路径，而不是进入未知状态。

### Phase 5：autonomy surface 动态化

目标：再扩到有 side effect 的 surface。

范围：

- `review_scheduling`
- `assessment_generation`
- `replan`

执行：

1. 收口 `TaskRuntimeSkillService` 与 `task.py` 的 runtime plan 语义。
2. 对 autonomy surface 明确：
   - tool-plan allowlist
   - runtime directives 生效范围
   - rollout observation anchor
   - failure rollback / retry contract
3. 继续保持 tool-plan 为 internal-only。
4. `replan` 的 multi-step 仍保持 bounded linear chain，不提前做 DAG。

完成标准：

- autonomy surface 的动态化不会破坏 retry、idempotency、workflow anchor 和 audit。
- runtime failure 有可定位的 usage / audit / observation 证据。

### Phase 6：binding match / precedence 强化

目标：把 binding 从简单 first-match 提升为稳定可解释的 deterministic 选择。

执行：

1. 固化 binding precedence：
   - status
   - priority_score
   - specificity
   - created/update ordering
2. 为 overlap/ambiguity 提供 explain。
3. 对“命中 binding 但 contract 不兼容”的情况补单独 reason code。
4. repository 层补充明确排序，而不是依赖内存顺序。

完成标准：

- 同 goal/surface 下多个 binding 的选择可预测、可解释。
- 运行时不再依赖“碰巧先取到谁”。

### Phase 7：tool-plan 动态化升级

目标：在已有保守 executor 上做受控增强，而不是一次性做通用 interpreter。

执行：

1. 每个 surface 单独维护 tool-plan allowlist。
2. 继续以线性两步链为主，不扩 branching/looping。
3. 扩前先补：
   - sandbox preview
   - runtime explain
   - usage sequence metadata
   - failure durable audit
4. prior-step output 引用保持白名单，不开放任意字段透传。

完成标准：

- tool-plan 的每次扩展都有独立 contract 和 regression。
- 不会因为一条 proposal 的 tool-plan 增强而影响所有 surface。

### Phase 8：operator / observability / regression 收口

目标：把动态 runtime 做成可运营能力。

执行：

1. 补 operator 读能力：
   - runtime explain
   - source precedence
   - staged shadow diff
   - fallback frequency
2. 补 observability：
   - fallback rate
   - blocked rate
   - incompatible rate
   - tool-plan failure rate
   - staged shadow drift
3. 补专项 regression matrix。

完成标准：

- runtime 动态化不再只能靠代码阅读排障。
- operator 能看懂当前 runtime 为什么这样运行。

## 8. 关键难点与应对

### 8.1 Source precedence 漂移风险高

难点：

- artifact、binding、rollout overlay、tool-plan 都会影响 runtime。
- 如果 precedence 不集中，改一处很容易改变生产行为。

应对：

- 先提取纯 policy。
- 所有 source precedence 走同一 contract。
- usage metadata 和 explain 共享同一语义来源。

### 8.2 `include_staged` 最容易造成治理误伤

难点：

- staged 在治理语义上不应等价于 rolled_out。
- 当前多个 runtime 调用点确实能把 staged 带进 binding 查询。

应对：

- 先把 staged 语义改成 shadow/probe。
- 默认生产 resolution 只读 rolled_out。
- 必须保留 staged 可见性时，也只允许 explain/dry-run/对比路径。

### 8.3 Autonomy surface 的 side effect 更重

难点：

- `review_scheduling / assessment_generation / replan` 不是纯展示面，会产生真实任务与 workflow 行为。

应对：

- 后扩 autonomy surface。
- 每个 surface 单独补 failure/retry/idempotency 回归。
- tool-plan 扩展必须逐面 allowlist。

### 8.4 `skills.py` 仍是大文件

难点：

- runtime binding 相关逻辑仍与 curator / readiness / lifecycle 共居大文件，后续继续叠功能风险很高。

应对：

- 本计划先固化 policy/explain/readiness。
- 再按 `SKILLS_PY_SPLIT_PLAN.md` 把 resolution/usage 拆出。

### 8.5 Explain 不足会放大运营成本

难点：

- 动态化一旦扩面，没有 explain API，operator 很难判断是 artifact、binding、rollout 还是 fallback 在起作用。

应对：

- 把 explain 放在第一阶段。
- 先补只读解释，再补行为扩展。

## 9. 边界与依赖关系

本计划与其他计划的边界如下：

- 与 `SKILLS_PY_SPLIT_PLAN.md`
  - 本文档不负责 `skills.py` 的拆分阶段顺序。
  - 但会为 `SkillResolver` / `SkillUsageService` / runtime policy 拆分提供边界基线。
- 与 `TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md`
  - 本文档不负责 task/autonomy callback 清理。
  - 但会定义 runtime plan 在 autonomy surface 上应保持的行为基线。
- 与 `REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md`
  - replacement proposal / staged artifact 的治理路径仍由反思与 skill evolution 文档约束。
  - 本文档只负责这些 governed artifact 如何逐步影响 runtime。
- 与 `MVP_VALIDATION_BASELINE_PLAN.md`
  - runtime binding regression 场景后续应纳入 MVP smoke。

## 10. 交付条件

完成本计划，至少应交付：

1. 一份 runtime binding V1 行为基线表。
2. 一套显式 runtime policy / readiness / explain contract。
3. 一条 operator 可用的 runtime explain 读路径。
4. 一套 `surface x source x status x fallback` regression matrix。
5. 一套 staged shadow/probe 与 production resolution 的隔离规则。
6. 一套 autonomy surface 的 tool-plan allowlist 与 failure baseline。

验收标准：

- staged binding 不会在无显式授权下进入生产 runtime。
- 低风险 surface 的动态化先于 autonomy surface 扩面。
- 所有 runtime blocked/fallback 决策都有 explain 和 reason code。
- usage metadata、audit、rollout observation 与 runtime source contract 保持一致。
- 默认测试路径不依赖真实 provider。
- 后续拆分 `skills.py` / `task.py` 时，runtime binding 语义漂移会被回归测试直接打断。

## 11. 推荐实施顺序

推荐顺序：

1. Phase 0：冻结当前事实。
2. Phase 1：先补 explain/probe。
3. Phase 2：固化 policy/fallback。
4. Phase 3：收口 staged 语义。
5. Phase 4：低风险 surface 动态化。
6. Phase 5：autonomy surface 动态化。
7. Phase 6：binding precedence 强化。
8. Phase 7：tool-plan 受控升级。
9. Phase 8：operator/observability/regression 收口。

不要先做：

- 直接把 staged candidate 放进生产 runtime。
- 直接做通用 DAG tool-plan interpreter。
- 在 `skills.py` 还未拆分前继续堆新的 product-critical runtime 分支。
- 在 explain/readiness 还没补齐前扩大 autonomy surface 的动态行为。
