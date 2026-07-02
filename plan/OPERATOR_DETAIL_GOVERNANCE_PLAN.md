# Operator 详情页与治理操作执行计划

## 1. 文档定位

本文档用于指导 `agent-edu` 在现有 I4 `operator dashboard` 基础上，扩展为可运营的 drill-down 工作台。

目标不是重做整套前端，也不是把所有后端对象都机械映射成页面，而是在保持现有治理边界、鉴权路径、审计契约和 Web-first 方向兼容的前提下，把 operator 侧体验收口成一套：

- 可钻取
- 可解释
- 可审计
- fail-closed
- 适合高频治理操作

本文档只负责 `operator 详情页与治理操作`。

与其他计划的关系：

- MVP 验证基线以 [plan/MVP_VALIDATION_BASELINE_PLAN.md](/home/cl/agent-edu/plan/MVP_VALIDATION_BASELINE_PLAN.md) 为主。
- memory 质量边界以 [plan/MEMORY_QUALITY_REGRESSION_PLAN.md](/home/cl/agent-edu/plan/MEMORY_QUALITY_REGRESSION_PLAN.md) 为主。
- reflection 到 skill 的治理闭环以 [plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md](/home/cl/agent-edu/plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md) 为主。
- runtime binding explain/readiness 以 [plan/SKILL_RUNTIME_BINDING_DYNAMICIZATION_PLAN.md](/home/cl/agent-edu/plan/SKILL_RUNTIME_BINDING_DYNAMICIZATION_PLAN.md) 为主。

优先级：

1. 前端只展示和发起操作，不实现治理判断。
2. 所有高风险操作必须继续走后端鉴权、审计、fail-closed。
3. 先补 operator auth shell 与 read contract，再补复杂 drill-down。
4. 先做 evidence/decision/history 可见性，再做更多操作入口。
5. 每个详情页都必须覆盖 `loading / empty / error / permission-denied`。

## 2. 设计对象与单一任务

本页组的产品对象是：

> 教育 Agent 的 operator / curator / reviewer 治理工作台。

目标用户：

- 运营侧 operator
- reflection reviewer
- skill curator
- memory governor

单一任务：

> 从 dashboard 上的风险信号或待处理对象，快速钻取到具体治理对象，完成“看证据 -> 看历史 -> 发起受控操作 -> 验证结果”的闭环。

建议延续现有 UI 视觉语言，而不是另起一套新主题。

建议的信息架构方向：

- 保持当前 dashboard 的 workbench 气质与信息密度。
- 详情页采用“主详情区 + 右侧治理轨道”的桌面式布局。
- 统一使用一个可复用的“证据脊柱”结构：
  - 证据
  - 决策
  - 历史
  - 操作

这样做的原因：

- 这些详情页不是阅读型内容页，而是取证和治理页。
- operator 真正需要的是稳定的扫描路径和后果清晰的操作面，而不是更花的页面样式。

## 3. 当前状态判断

当前 I4 已满足 MVP 级 operator dashboard，但还不是运营工作台。

### 3.1 当前前端事实

现有 Web operator 路由只有：

- [packages/frontend/src/App.tsx](/home/cl/agent-edu/packages/frontend/src/App.tsx)
  - `/operator`

当前页面只有：

- [packages/frontend/src/pages/operator/operator-dashboard-page.tsx](/home/cl/agent-edu/packages/frontend/src/pages/operator/operator-dashboard-page.tsx)

当前 dashboard 只展示：

- guardrails 状态
- reflection review queue
- proposal review queue
- curator recommendations
- recent audit events

当前 operator 前端类型与 hook 也只覆盖这些列表型能力：

- [packages/frontend/src/hooks/use-operator.ts](/home/cl/agent-edu/packages/frontend/src/hooks/use-operator.ts)
- [packages/frontend/src/types/operator.ts](/home/cl/agent-edu/packages/frontend/src/types/operator.ts)

更关键的是，当前前端 API client 默认只会带 learner key：

- [packages/frontend/src/api/client.ts](/home/cl/agent-edu/packages/frontend/src/api/client.ts)
- [packages/frontend/src/lib/learner-auth.ts](/home/cl/agent-edu/packages/frontend/src/lib/learner-auth.ts)

现状结论：

1. 当前前端没有 operator auth shell。
2. 当前前端没有 operator detail routes。
3. 当前前端没有 operator mutation feedback/confirm flow。
4. 当前 `/operator` 页面即使存在，也缺少明确的 `X-Operator-Key` 浏览器侧接入壳。

这不是细节问题，而是详情页落地前必须先补的基础能力。

### 3.2 当前后端事实：Memory

memory 相关 operator 路由已具备较多基础：

- [packages/agent_core/src/agent_core/api/routes/memory.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/routes/memory.py)
  - browse
  - detail
  - evidence-links
  - governance-decisions
  - annotations
  - conflicts list / conflict detail
  - suppress / restore / annotate

现状判断：

- `memory detail` 的大部分后端基础已在。
- 但“按 memory 直接查看 conflict memberships”还不是一跳直达。
- detail 页如果只靠现有 API，需要多请求 fan-out。

### 3.3 当前后端事实：Reflection

reflection 相关 operator 路由也已有基础：

- [packages/agent_core/src/agent_core/api/routes/reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/routes/reflection.py)
  - reflection detail
  - review history
  - review / resolve / override-root-cause / override-action
  - related proposals
  - proposal queue / proposal detail / sandbox runs / approval decisions / rollouts / bindings

但有一个关键缺口：

- 当前 schema 有 [packages/agent_core/src/agent_core/domain/schemas/reflection_v2.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/domain/schemas/reflection_v2.py) 中的 `ReflectionOutcomeEvaluationResponse`
- 但当前 route 没有 `GET /reflections/{reflection_id}/outcome-evaluation` 或等价 detail 聚合

现状结论：

- reflection detail 已能展示 root cause、actions、review history、source ids。
- `outcome evaluation` 仍缺 operator 直读接口。

### 3.4 当前后端事实：Skill Artifact

skill operator API 已相对完整：

- [packages/agent_core/src/agent_core/api/routes/skills.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/routes/skills.py)
  - artifact list / detail
  - lineage
  - usage
  - replacement readiness
  - curator recommendations list / detail / accept / dismiss
  - activate / replace / suppress / restore / archive / stabilize / deactivate
  - resolution probe

现状结论：

- `skill artifact detail` 的大部分 mutation backend 已在。
- 但前端仍缺 detail route、聚合 hook、confirm flow、usage summary 与 explain 面板。
- 当前 skill artifact detail 如果完全依赖前端拼多个 read API，页面复杂度会迅速抬升。

### 3.5 当前后端事实：Audit

audit 当前只有列表读取：

- [packages/agent_core/src/agent_core/api/routes/audit.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/routes/audit.py)
  - `GET /audit/events`

当前 `AuditRepository` 也只有：

- [packages/agent_core/src/agent_core/infrastructure/db/repositories/audit.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/db/repositories/audit.py)
  - `list_recent(...)`

当前 `AuditEvent` model/schema 只有：

- `id`
- `event_type`
- `resource_type`
- `resource_id`
- `actor`
- `event_data`
- `created_at`

没有一等字段：

- `correlation_id`
- `failure_reason`
- `actor_type`
- `entity label`

现状结论：

- “audit event detail” 不是纯前端问题。
- 如果要稳定展示 `correlation id`，当前后端 contract 不够。

## 4. 目标与非目标

### 4.1 目标

本次计划应达成：

1. 建立 operator auth shell，使 browser 能安全读取受保护 operator API。
2. 为 memory / reflection / skill artifact / audit 建立 drill-down route 和稳定的详情 view model。
3. 把高风险 mutation 收口为标准确认流、可恢复反馈和 audit 可见结果。
4. 让 operator 能从 dashboard 列表一跳进入对象详情，而不是手动拼 ID。
5. 让 UI 只承担展示和发起，不承担治理判断。

### 4.2 非目标

本次不应做：

- 不在前端重写任何 memory / reflection / skill lifecycle state machine。
- 不在浏览器端判断某个操作是否合法或是否该显示为“治理通过”。
- 不新增不受治理保护的快捷操作。
- 不为了详情页一次性重做整个 Web layout。
- 不把 CLI/TUI 的所有调试字段原样暴露给 Web。

## 5. 页面范围与最低交付

### 5.1 Memory Detail

最低必须支持：

- 基本详情
- evidence links
- governance decisions
- annotations
- conflict members
- suppress / restore / annotate

### 5.2 Reflection Detail

最低必须支持：

- source task / workflow / goal
- root cause
- proposed action
- outcome evaluation
- review history
- review / resolve / override-root-cause / override-action

### 5.3 Skill Artifact Detail

最低必须支持：

- version / lineage
- runtime directives
- readiness status
- usage metrics
- curator recommendations
- activate / replace / suppress / archive

### 5.4 Audit Event Detail

最低必须支持：

- actor
- entity
- event type
- correlation id
- failure reason
- raw/structured event payload

## 6. 关键边界

### 6.1 前端边界

- 前端只调用 API，不做治理判定。
- 前端可以根据后端返回状态隐藏/禁用按钮，但这只是 usability 层，不是授权层。
- 所有 detail 页面都要把 read contract 映射为明确 view model，不能直接把原始 API payload 散落到多个组件。

### 6.2 后端边界

- routes 只做鉴权、参数校验、调用 service、提交事务、映射 response。
- 聚合 detail 逻辑应放到应用服务或显式 read service，不应塞进前端或 route。
- 高风险 mutation 必须继续由既有 service owner 承载。

### 6.3 安全边界

- `X-Operator-Key` 必须继续作为真实 authority。
- 浏览器中的 operator key 只是 transport credential，不等于前端拥有治理权。
- 所有 protected path 要继续 fail closed。
- 所有 mutation 失败不得在 UI 上表现成成功。

### 6.4 审计边界

- 任何 suppress / restore / annotate / review / resolve / activate / replace / archive 类操作，都必须保留 durable audit。
- 页面只展示 audit 与 object state，不能伪造“已成功”。

## 7. 需要增强的核心问题

### 7.1 Operator Auth Shell 缺失

这是当前最先要补的基础缺口。

问题：

- `packages/frontend/src/api/client.ts` 只会自动附带 learner key。
- `/operator` 页面当前没有 operator key 输入、存储、清理、permission-denied 引导。
- detail 页如果直接开始写，会先死在认证壳上。

建议：

- 单独建立 `operator-auth` client state。
- API client 支持按上下文附带 `X-Operator-Key`。
- operator route 增加 gate，而不是让每个页面自己处理“无 key 时如何报错”。

### 7.2 Detail Read Contract 不统一

当前 detail 能力分散：

- memory：已有 detail + 多个子资源
- reflection：detail + reviews，但缺 outcome evaluation
- skill：detail + lineage + usage + readiness + recommendations
- audit：只有 list

问题：

- 前端如果直接拼接所有 read API，会出现：
  - hooks 膨胀
  - 页面状态管理复杂
  - 请求扇出过多
  - 同步/刷新时容易状态不一致

建议：

- 先允许复用现有 API。
- 但对扇出过重或字段缺失的对象，补“聚合 read service / 聚合 response”。

### 7.3 Audit Detail Contract 明显不足

这是当前最明确的后端短板。

问题：

- 只有 `GET /audit/events`
- 无 `GET /audit/events/{id}`
- 无 `resource_id` / `actor` / `time range` / `correlation id` 级过滤
- 当前 model/schema 没有 first-class `correlation_id`

如果直接做 audit detail 页：

- 只能 best-effort 展示 `event_data`
- 无法稳定支持“按 correlation chain drill-down”

建议：

- Phase 1 先补 `GET /audit/events/{id}` 和更完整 list filter。
- 若要稳定满足 `correlation id` 要求，建议补一等 contract：
  - response field
  - repository filter
  - 必要时 schema/index 增补

如果不做这一步，就不要把“审计详情可按 correlation 追踪”写成已交付能力。

### 7.4 Reflection Outcome Evaluation 缺读路径

当前 reflection detail 页的最大字段缺口不是 root cause，而是 outcome evaluation。

问题：

- schema 有 `ReflectionOutcomeEvaluationResponse`
- route 没有 detail read API

建议：

- 增加 `GET /reflections/{reflection_id}/outcome-evaluation`
- 或者把它聚合进 reflection detail envelope

### 7.5 Memory Conflict Members 不是 memory detail 一跳直达

当前 conflict detail 是按 conflict set 查，不是按 memory 查。

问题：

- 页面如果从 memory detail 出发，要找到当前 memory 所属 conflict，需要额外拼路径。

建议：

- 两个可选方案二选一：
  - 在 memory detail 聚合当前 memory 的 open conflict summary / conflict members
  - 新增 `GET /memory/{memory_type}/{memory_id}/conflicts`

推荐第二种：

- ownership 清晰
- 避免把 `describe_*_memory()` 继续做成更大的 god payload

### 7.6 Skill Detail 缺“可运营视图”，不是缺 mutation API

skill API 已相对齐全，但 detail 页仍未成形。

问题：

- 只有底层 read API，没有面向 operator 的 detail 视图层
- `usage` 当前是 event list，不是 summary
- `runtime directives`、`tool_plan`、`lineage`、`readiness`、`recommendations` 还没有统一 detail 结构

建议：

- 先做 page-level 聚合 hook。
- 如果前端需要重复计算 usage summary 或 readiness badge 逻辑超过三处，再补 backend read summary。

### 7.7 UI Route / State 仍停留在 dashboard 级

当前前端只有 `/operator`。

建议详情 routes：

- `/operator/memory/knowledge/:memoryId`
- `/operator/memory/behavior/:memoryId`
- `/operator/reflections/:reflectionId`
- `/operator/skills/artifacts/:artifactId`
- `/operator/audit/events/:eventId`

可选：

- drawer/modal route for action confirmations
- query-param based subpanels

### 7.8 详情页状态覆盖必须被当作一等要求

当前要求已经明确：

- loading
- empty
- error
- permission-denied

这里不能做 happy-path-only UI。

尤其 operator 页是高频故障排查面：

- API 403
- 404
- partial data missing
- mutation failed

都必须有明确落点。

## 8. 推荐技术实现

### 8.1 前端信息架构

建议保留现有 `/operator` 作为总览入口。

推荐工作台结构：

1. dashboard
2. object detail
3. mutation confirm
4. post-action verification

每个 detail 页统一使用三段式结构：

- 顶部：对象身份、状态、breadcrumbs、最近动作
- 主区：证据/详情 tabs
- 右栏：治理轨道

建议 detail 页统一 tabs：

- `Overview`
- `Evidence`
- `History`
- `Actions`

其中 memory / reflection / skill 可以按对象裁剪，但结构尽量统一。

### 8.2 共享前端基础设施

建议新增：

```text
packages/frontend/src/pages/operator/
  components/
    operator-shell.tsx
    operator-page-header.tsx
    operator-state-panel.tsx
    operator-action-rail.tsx
    operator-timeline.tsx
    operator-json-drawer.tsx
    permission-state.tsx
    loading-state.tsx
    empty-state.tsx
    error-state.tsx
```

建议新增 hooks：

```text
packages/frontend/src/hooks/
  use-operator-auth.ts
  use-operator-memory.ts
  use-operator-reflection.ts
  use-operator-skill.ts
  use-operator-audit.ts
```

建议新增 types：

```text
packages/frontend/src/types/
  operator-memory.ts
  operator-reflection.ts
  operator-skill.ts
  operator-audit.ts
```

原则：

- page 负责组装
- hook 负责取数与 mutation
- presentational component 不自行 fetch

### 8.3 Operator Auth Shell

建议新增：

- operator key local storage/volatile storage
- operator route guard
- operator credential form
- clear credential action

API client 建议支持：

- learner context
- operator context
- no-auth public context

而不是只有 learner key 一条路径。

### 8.4 后端 read contract 策略

推荐原则：

- 现有 API 足够时，前端直接复用。
- 现有 API 扇出过重或缺关键字段时，补聚合 read API。

推荐新增或增强的 backend read contract：

1. `GET /memory/{memory_type}/{memory_id}/conflicts`
2. `GET /reflections/{reflection_id}/outcome-evaluation`
3. `GET /audit/events/{event_id}`
4. `GET /audit/events` 增加：
   - `resource_id`
   - `actor`
   - `from`
   - `to`
5. 如果要稳定满足 correlation 追踪：
   - `correlation_id` first-class response/filter contract

### 8.5 高风险 mutation 交互标准

对以下操作统一采用：

- confirm modal / side sheet
- reason code + reason note
- pending state
- success toast + detail refetch
- failure toast + error body
- audit-visible result

适用对象：

- memory suppress / restore / annotate
- reflection review / resolve / override
- skill activate / replace / suppress / restore / archive
- curator recommendation accept / dismiss

### 8.6 推荐 UI 视图模型

#### Memory Detail View Model

建议页面视图模型聚合：

- detail
- evidence_links
- governance_decisions
- annotations
- open_conflicts
- available_actions

#### Reflection Detail View Model

建议聚合：

- detail
- outcome_evaluation
- review_history
- related_proposals
- source_links
- available_actions

#### Skill Artifact Detail View Model

建议聚合：

- artifact
- lineage
- readiness
- usage_summary
- recent_usage
- curator_recommendations
- runtime_explain_summary
- available_actions

#### Audit Event Detail View Model

建议聚合：

- event core
- parsed entity label
- parsed failure reason
- correlation chain summary
- raw payload

## 9. 推荐执行阶段

### Phase 0：冻结当前事实与 IA

目标：先把现状和真实缺口写死。

执行：

1. 记录当前 `/operator` 只有 dashboard。
2. 记录 frontend client 缺 operator header。
3. 记录四类对象的现有 API 清单和缺口。
4. 定义 detail routes 与 breadcrumbs。

完成标准：

- 有一份 operator IA 与 API gap matrix。
- 不再把“页面没做”和“API 也没做”混为一谈。

### Phase 1：补 operator auth shell

目标：让 browser 端真正能访问 operator API。

执行：

1. 新增 operator credential state。
2. API client 支持 `X-Operator-Key`。
3. `/operator` 及子路由接入 route guard。
4. permission-denied / invalid-key 状态有明确 UI。

完成标准：

- operator dashboard 与后续 detail 页可在浏览器中正常读取受保护 API。
- invalid key fail closed，且不会误导用户成“空数据”。

### Phase 2：Memory Detail

目标：先落 memory detail，验证 detail+mutation 模式。

执行：

1. 新增 memory detail routes。
2. 聚合：
   - detail
   - evidence links
   - governance decisions
   - annotations
   - conflicts
3. 增加 suppress / restore / annotate flow。
4. 若后端未补 per-memory conflicts route，则先补该 route。

完成标准：

- operator 可从 memory list/dashboard drill into detail。
- 可查看 evidence/decision/history。
- mutation 后 detail 会稳定刷新。

### Phase 3：Reflection Detail

目标：落 reflection 详情与审核操作。

执行：

1. 新增 reflection detail route。
2. 聚合：
   - detail
   - review history
   - related proposals
   - outcome evaluation
3. 增加：
   - review
   - resolve
   - override root cause
   - override action
4. 若后端缺 outcome evaluation read route，则补它。

完成标准：

- reflection detail 能完整解释 source、root cause、proposed action、review history。
- outcome evaluation 可直读，不再需要 operator 猜测。

### Phase 4：Skill Artifact Detail

目标：把 skill operator surface 从列表页升级为可运营 detail。

执行：

1. 新增 skill artifact detail route。
2. 聚合：
   - artifact detail
   - lineage
   - replacement readiness
   - recent usage
   - curator recommendations
3. 增加：
   - activate
   - replace
   - suppress
   - restore
   - archive
4. 如果 usage summary 纯前端聚合过重，再补 backend summary read contract。

完成标准：

- operator 能在一页内完成“看 readiness -> 看 usage -> 发起治理动作”。
- 前端不自行推断治理合法性，只消费后端 contract。

### Phase 5：Audit Event Detail

目标：补齐 audit drill-down，形成治理闭环可追踪面。

执行：

1. 新增 audit event detail route。
2. 后端补：
   - `GET /audit/events/{id}`
   - 更细 list filter
3. 若目标要求是稳定 correlation trace：
   - 评估并落一等 `correlation_id` contract
4. detail 页支持：
   - parsed core fields
   - failure reason
   - raw payload drawer

完成标准：

- audit 不再只有时间倒序列表。
- operator 能定位单条事件的对象、失败原因和关联链。

### Phase 6：共享组件与交互标准化

目标：避免四个 detail 页各自长成一套。

执行：

1. 提取共享状态组件。
2. 提取 action rail / timeline / json drawer。
3. 统一 confirm flow、toast、mutation invalidation。

完成标准：

- 页面结构一致。
- 状态处理一致。
- 后续新增 detail 对象不会重复造轮子。

### Phase 7：测试与回归收口

目标：让 operator 工作台不靠人工点点看验收。

前端至少覆盖：

- loading
- empty
- error
- permission-denied
- mutation pending / success / failure

后端至少覆盖：

- auth rejected
- permission denied
- not found
- repeated operation / idempotent path
- audit write present
- failure-path rollback

## 10. 关键难点与应对

### 10.1 当前 frontend auth 壳不成立

难点：

- 没有 operator key 注入，detail 页会先卡死在 protected API。

应对：

- 先补 auth shell，再做 drill-down 页面。

### 10.2 Audit detail 不是纯前端功能

难点：

- 当前缺少 `GET /audit/events/{id}` 和 first-class correlation contract。

应对：

- 文档中明确区分：
  - minimum detail
  - reliable correlation trace
- 不用前端硬凑出“看起来像 correlation”的伪能力。

### 10.3 多对象 detail 极易演变成页面各自堆逻辑

难点：

- 如果没有统一 view model 和组件基线，很快会出现四套不同的 detail 架构。

应对：

- 统一 route/hook/component 分层。
- 共享 action rail、timeline、state panels。

### 10.4 高风险操作容易被做成前端判断

难点：

- 前端很容易为了省事，自己判断按钮是否可点击、状态是否“ready”。

应对：

- 按 contract 返回 capability/readiness。
- 前端只读 contract，不重演治理规则。

## 11. 边界与依赖关系

本计划与其他计划的边界如下：

- 与 `MEMORY_QUALITY_REGRESSION_PLAN.md`
  - 本文档只处理 memory operator detail 与操作面，不定义 memory quality 规则。
- 与 `REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md`
  - reflection / proposal / curator 的治理语义仍由该文档定义。
  - 本文档只负责 operator 如何查看和触发它们。
- 与 `SKILL_RUNTIME_BINDING_DYNAMICIZATION_PLAN.md`
  - skill detail 中的 runtime explain/readiness 若扩展，语义应服从该文档。
- 与 `MVP_VALIDATION_BASELINE_PLAN.md`
  - operator detail/mutation smoke 应后续纳入 MVP 验证基线。

## 12. 交付条件

完成本计划，至少应交付：

1. operator auth shell。
2. 四类 detail routes：
   - memory
   - reflection
   - skill artifact
   - audit event
3. 每类 detail 的稳定 view model 与 hook。
4. 高风险 mutation 的统一 confirm + feedback 流。
5. 缺失的 backend read contract 补口清单与实现。
6. 前后端回归测试覆盖。

验收标准：

- operator 能从 dashboard drill into 具体治理对象。
- 所有 detail 页面都覆盖 loading/empty/error/permission-denied。
- 所有高风险操作都继续通过后端鉴权、审计、fail-closed。
- 前端不实现治理判断。
- audit detail 至少可查看单条事件；若宣称支持 correlation trace，则后端必须提供稳定 contract。

## 13. 推荐实施顺序

推荐顺序：

1. Phase 0：冻结 IA 与缺口矩阵。
2. Phase 1：先补 operator auth shell。
3. Phase 2：memory detail。
4. Phase 3：reflection detail。
5. Phase 4：skill artifact detail。
6. Phase 5：audit detail。
7. Phase 6：共享交互标准化。
8. Phase 7：测试与回归收口。

不要先做：

- 在没有 operator auth shell 的情况下直接堆 detail 页面。
- 在没有 audit detail contract 的情况下承诺 correlation drill-down 已可用。
- 在前端复刻 readiness / governance 决策逻辑。
