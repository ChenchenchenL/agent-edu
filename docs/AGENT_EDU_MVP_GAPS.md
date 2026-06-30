# agent_edu MVP 缺口

## 文档定位

这份文档只回答一个问题：

> 按当前仓库代码状态，`agent_edu` 如果要被称为一个可交付的 MVP，还差什么。

它不是路线图，也不是全量技术债列表，而是面向“能否称为 MVP”的缺口清单。

若旧文档、阶段规划和当前代码状态不一致，以当前代码状态和本文件的范围定义为准。

---

## 先收口：这里的 MVP 指什么

如果不先定义范围，`agent_edu` 的“MVP 缺口”会被无限放大，因为当前仓库已经同时在做：

- Phase 1：稳定教学 Agent
- Phase 2：最小自主任务系统
- 长期记忆治理
- Reflection / Skill Evolution 治理链路
- Runtime / rollout / curator / worker 基础设施

这些不是同一个 MVP 层级。

本文件采用的 MVP 定义是：

> 一个用户能够实际使用、可以重复验证、具备基本治理能力的教育 Agent。

最小应包含：

- learner profile / goal / session 基础对象可用
- 用户可围绕主题持续对话
- 系统可给出教学型解释、quiz、hint
- session / profile 级记忆能形成最小连续性
- 基础 task / plan 闭环可用，但不要求长期全自动自治
- 关键高风险动作有 audit
- Docker 环境中可以重复验证核心链路
- 默认配置下不会因为后台自治或演进链路失控而破坏主产品路径

因此，以下内容**不应**被当作当前 MVP 阻断项：

- 完整多 agent society
- 通用 DAG/branching tool-plan interpreter
- bundle / global rollout
- 全面 auto skill evolution
- 所有 surface 的 auto-governance
- 长期生产级运维自动化闭环

这些是后续阶段能力，不是当前 MVP 的必要条件。

---

## 当前判断

当前 `agent_edu` 已经不是“未成形后端骨架”。

已真实落地的主链路包括：

- session / message / chat / quiz / hint
- session memory + long-term memory candidate materialization
- learner goal / study plan / daily task / workflow run
- DB-backed autonomy jobs 与 worker baseline
- reflection / curator / skill artifact / governed staging 的最小受控链路
- 审计、metrics、部分 dashboard / alert 基线

但它还不能被准确描述为：

> 一个已经完成收口、可以稳定交付的 MVP。

更准确的状态是：

> 主教学链路和最小任务链路已经打通，但产品表面、稳定验证、运维收口和后台执行边界还没有完全收口。

---

## Must Fix Before Calling It MVP

### 1. 缺少清晰且一致的 MVP 边界定义

严重性：`HIGH`

当前问题：

- 多份文档同时在描述 Phase 1、Phase 2、memory governance、reflection、skill evolution
- 不同文档对“当前已完成什么”与“什么仍算 MVP 范围”口径并不完全一致
- 容易把“路线图中的最小闭环”误写成“产品级 MVP 已完成”

为什么这是阻断项：

- 如果连 MVP 边界都不一致，后续测试、验收、排期、灰度标准都会漂移
- 团队会不断把后续阶段能力错误拉进 MVP，或者反过来把当前必须交付的产品面遗漏掉

直接影响：

- 验收无法收敛
- 文档会持续误导实现优先级
- “是否完成 MVP”会变成口径问题而不是工程问题

建议收口：

- 明确写死当前 MVP 的产品范围
- 明确哪些属于 Phase 2+/roadmap，不纳入 MVP 阻断项
- 用一份文档作为唯一验收基线

相关参考：

- [docs/IMPLEMENTATION_PLAN.md](/home/cl/agent-edu/docs/IMPLEMENTATION_PLAN.md:31)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:26)
- [docs/SYSTEM_DESIGN.md](/home/cl/agent-edu/docs/SYSTEM_DESIGN.md:690)

---

### 2. Web-first 产品表面还没有真正收口成可交付形态

严重性：`HIGH`

当前状态：

- 后端 API 主链路已较完整
- 历史 CLI / TUI baseline 存在
- 文档已经明确产品方向调整为 Web-first

但问题在于：

- 当前仓库更像“后端能力 + 历史终端工作台 + Web-first 方向声明”
- 还不能证明已有一个足够完整的 learner-facing / operator-facing Web 交付面

为什么这是阻断项：

- 如果产品方向是 Web-first，那么 MVP 不能只停在 API 与历史 CLI/TUI 参考资产
- 仅有后端闭环，不等于用户可交付产品闭环

MVP 最少需要的表面能力：

- learner 能创建/进入学习会话
- learner 能连续提问、看解释、做 quiz、拿 hint
- learner 能查看最小任务/复习上下文
- operator 至少能查看关键治理/audit 信息

如果这些仍主要依赖 API 或历史终端资产，则当前更接近“后端 MVP”，不是“产品 MVP”。

相关参考：

- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:26)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:460)
- [docs/SYSTEM_DESIGN.md](/home/cl/agent-edu/docs/SYSTEM_DESIGN.md:690)

---

### 3. 稳定验证基线还没有收口到“可重复交付”

严重性：`HIGH`

当前状态：

- 主链路已经有较多测试和 Docker/live smoke 迹象
- 但文档自己也承认当前更接近“可运行”而非“稳定运营”

问题不在“有没有测试”，而在于：

- 还缺单一、稳定、可重复执行的 MVP 验证清单
- 还缺把教学主链路、任务主链路、记忆主链路串起来的最小回归基线
- 还缺清晰的“通过什么验证就可以发布 MVP”标准

为什么这是阻断项：

- 没有稳定验证基线，MVP 只能靠人工口头确认
- 对包含 LLM、embedding、worker、memory、governed writes 的系统，这种验收方式不成立

MVP 最少应稳定覆盖：

- session -> chat
- session -> hint
- session -> quiz
- message -> memory event -> retrieval
- learner goal -> study plan -> daily task -> execute
- 核心 audit 写入
- Docker compose 下可重复 smoke

相关参考：

- [docs/IMPLEMENTATION_PLAN.md](/home/cl/agent-edu/docs/IMPLEMENTATION_PLAN.md:332)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:81)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:551)

---

### 4. 生产前必需的运维防护还没有补齐

严重性：`HIGH`

当前状态：

- metrics、部分 dashboard 和 alert baseline 已经存在
- 但文档仍明确指出成本治理、限流、熔断和告警通知/自动化闭环未补齐

为什么这是阻断项：

- `agent_edu` 不是纯本地脚本，而是带 LLM、embedding、worker、autonomy job 的长期服务
- 没有成本治理、限流和熔断，MVP 一旦接真实流量就缺乏基本保护
- 有 metrics 不等于有可用的运行保护

MVP 最少需要：

- 基础 rate limit
- provider 超时/失败的明确降级策略
- 成本或调用量 guardrail
- 关键告警至少能通知，而不是只停留在规则文件

相关参考：

- [docs/SYSTEM_DESIGN.md](/home/cl/agent-edu/docs/SYSTEM_DESIGN.md:763)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:878)

---

### 5. 后台任务系统还没有完全收口到稳定的服务边界

严重性：`HIGH`

当前状态：

- 最小 autonomy worker 已落地
- `TaskPlanLifecycleService`、`TaskAutonomySchedulingService`、`TaskRuntimeSkillService` 已做了明显拆分

但关键问题仍然存在：

- `TaskAutonomySchedulingService` 仍通过 callback 协调 legacy core
- `TaskPlanLifecycleService.generate_plan()` 仍依赖 callback 收尾
- `AutonomousTaskService` 仍不是纯委托空壳

为什么这是阻断项：

- 对后台任务系统来说，这不是单纯“代码优雅性”问题
- 边界没收口，意味着 worker / scheduler / retries / side effects 的稳定性和可推理性仍不足
- 一旦进入真实长期运行，排障和变更风险会被放大

这项不一定要求在 MVP 前做完所有重构，但至少要做到：

- 主执行路径的事务边界清楚
- callback 依赖不再影响核心任务稳定性
- 关键后台路径有明确的 reentry / retry / failure 语义

相关参考：

- [docs/REMAINING_TASKS.md](/home/cl/agent-edu/docs/REMAINING_TASKS.md:17)
- [docs/REMAINING_TASKS.md](/home/cl/agent-edu/docs/REMAINING_TASKS.md:63)
- [docs/REMAINING_TASKS.md](/home/cl/agent-edu/docs/REMAINING_TASKS.md:99)

---

## Should Fix Before Merge Or Public MVP Release

### 6. `skills.py` 仍是巨型文件，继续叠功能会放大治理漂移风险

严重性：`MEDIUM`

当前状态：

- `application/services/skills.py` 仍是 4700+ 行巨型文件
- 当前 skill resolution、curator、readiness、recommendation、lifecycle 等多种职责继续堆在一起

为什么有问题：

- 这不是单纯可读性问题
- 对有大量治理规则和状态流转的模块，巨型文件会加速规则漂移和回归风险

这不是唯一的 MVP 阻断项，但如果继续在这里堆 product-critical 功能，风险会持续上升。

相关参考：

- [docs/REMAINING_TASKS.md](/home/cl/agent-edu/docs/REMAINING_TASKS.md:42)

---

### 7. 长期记忆系统已落地最小治理闭环，但还没到生产级回归状态

严重性：`MEDIUM`

当前状态：

- long-term memory governance 主链路已经落地
- candidate materialization / governance / maintenance / audit / observability 都已接上

但文档已明确：

- 动态阈值
- 精细化 topic 对齐
- 长期数据回归集
- 更强生产验证

仍未完成。

为什么这项不是当前 MVP 的硬阻断：

- 对“可交付的教育 Agent”来说，最小记忆连续性已经存在
- 当前缺的是生产级优化，不是“有没有记忆能力”

但它会影响：

- 长期使用质量
- 治理误判率
- 运营可解释性

相关参考：

- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:379)

---

### 8. Reflection / Skill Evolution 已进入受控闭环，但不应被误判为 MVP 已完成项

严重性：`MEDIUM`

当前状态：

- `memory -> reflection -> skill proposal -> sandbox/evaluation/approval -> artifact -> usage -> curator recommendation`
  最小链路已经形成
- 但更深的 auto-governance、staged replacement auto execute、bundle/global rollout 仍未完成

为什么要特别指出：

- 这些不是当前产品 MVP 的硬阻断项
- 但如果文档继续把“最小治理闭环已打通”误写成“动态技能系统已完成”，会误导排期和风险判断

相关参考：

- [docs/MEMORY_REFLECTION_SKILL_ROADMAP.md](/home/cl/agent-edu/docs/MEMORY_REFLECTION_SKILL_ROADMAP.md:67)
- [docs/PROGRESS_STATUS.md](/home/cl/agent-edu/docs/PROGRESS_STATUS.md:806)

---

## 明确不属于当前 MVP 阻断项

以下能力仍未完成，但不应被算作当前 MVP 的缺口：

- 通用多步 tool-plan interpreter
- branching / looping / DAG orchestration
- 所有 runtime surface 的 auto-governance
- staged replacement 的全面 auto activate / replace
- bundle / global rollout
- 完整 connector / plugin 生态
- 多 agent society
- 长期全自动后台自治体

这些都属于后续阶段，不应拖住当前 MVP 的验收。

---

## 当前最小收口建议

如果目标是尽快把 `agent_edu` 收口成一个可信的 MVP，优先级应是：

1. 明确唯一 MVP 范围文档和验收标准。
2. 把 Web-first 最小产品表面补成真正可交付形态。
3. 固化 Docker 下的主链路 smoke/regression 基线。
4. 补齐成本治理、限流、熔断和告警通知的最小运行保护。
5. 收口后台任务系统的关键 callback / transaction / failure 边界。

在这些点没完成之前，更准确的说法应是：

> `agent_edu` 已具备强后端主链路和多个受控最小闭环，但还没有完全收口成一个稳定、可交付、可运营的产品级 MVP。

---

## MVP 验收清单（唯一验收基线）

本文档是 `agent_edu` MVP 的唯一验收基线。所有其他文档（`PROGRESS_STATUS.md`、`IMPLEMENTATION_PLAN.md`、`SYSTEM_DESIGN.md`）中关于"当前进度"的描述，如果与本文档的 MVP 范围定义冲突，以本文档为准。

验收通过标准：**所有 `MUST` 项全部通过，`SHOULD` 项至少完成 80%。**

---

### A. 基础对象层 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| A1 | LearnerProfile 可通过 API 创建、读取 | ✅ 已完成 | `POST /api/v1/profiles` + `GET /api/v1/profiles/{id}` |
| A2 | LearnerGoal 可通过 API 创建、读取、更新状态 | ✅ 已完成 | `POST /api/v1/goals` + `GET` + `PATCH status` |
| A3 | LearningSession 可通过 API 创建、读取、列表、更新状态 | ✅ 已完成 | `POST /api/v1/sessions` + `GET` + `PATCH status` |
| A4 | Session 可绑定 `learner_profile_id` 和 `learner_goal_id` | ✅ 已完成 | `POST /sessions` body 含 profile/goal id |
| A5 | 对象间关联关系正确：goal → plan → task → session | ✅ 已完成 | `test_phase2_profile_goal_plan_task_workflow_chain` |

---

### B. 教学主链路 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| B1 | 用户发消息，系统返回结构化教学回复（非闲聊） | ✅ 已完成 | `POST /sessions/{id}/messages` → 回复含 `skill_trace` + 结构化 payload |
| B2 | 概念讲解输出包含定义/原理/例子/误区/下一步 | ✅ 已完成 | `explain_concept` skill 返回结构化 JSON |
| B3 | 自适应提示返回分层 hint，不直接泄露答案 | ✅ 已完成 | `adaptive_hint` skill + `direct_answer_given=false` 校验 |
| B4 | 练习题生成返回结构化题目，绑定 session | ✅ 已完成 | `POST /quizzes/generate` → 持久化 + 可列表/详情 |
| B5 | 消息历史支持分页读取 | ✅ 已完成 | `before_id` 游标 + `total` + `next_before_id` |
| B6 | 教学回复可走真实 LLM provider（非仅 mock） | ✅ 已完成 | DashScope-compatible provider 已实现，Docker smoke 已验证 |

---

### C. 记忆链路 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| C1 | 每轮对话后写入 session memory event | ✅ 已完成 | `session_memory_events` 表，含 summary/tags/progress/struggle |
| C2 | Memory event 可生成 embedding | ✅ 已完成 | `session_memory_embeddings` 表，DashScope embedding provider |
| C3 | 回复前检索同 session 相关记忆并注入上下文 | ✅ 已完成 | Session memory retrieval → LLM context |
| C4 | 跨 session 聚合 profile 级记忆并注入长期上下文 | ✅ 已完成 | Profile memory retrieval → long-term context |
| C5 | 长期记忆以 `candidate` 状态写入，不直接成为高权重上下文 | ✅ 已完成 | `KnowledgeMemory` / `BehaviorMemory` 默认 `candidate` |
| C6 | 长期记忆支持治理状态流转 | ✅ 已完成 | `candidate → active → stable → compressed/archived/suppressed` |
| C7 | 运营侧可 suppress / annotate / restore 记忆 | ✅ 已完成 | `POST /api/v1/memory/{type}/{id}/suppress|annotate|restore` |
| C8 | 长期记忆检索 API 可用 | ✅ 已完成 | `GET /api/v1/memory/knowledge` + `GET /api/v1/memory/behavior` |

---

### D. 任务链路 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| D1 | LearnerGoal 可生成 StudyPlan | ✅ 已完成 | `POST /api/v1/goals/{id}/plan` |
| D2 | StudyPlan 包含 PlanStage，支持 14 天任务窗口物化 | ✅ 已完成 | `DailyTask` 物化 + timezone 感知 |
| D3 | DailyTask 可查询、可执行 | ✅ 已完成 | `GET /tasks` + `POST /tasks/{id}/execute` |
| D4 | Task 执行时自动创建绑定 goal/task 的 session | ✅ 已完成 | execute → auto session → chat/quiz |
| D5 | Task `completed` 触发 review scheduling | ✅ 已完成 | Autonomy job → review task |
| D6 | Task `failed/skipped` 触发 immutable replan | ✅ 已完成 | Plan version + replan audit |
| D7 | Assessment 任务调度可用 | ✅ 已完成 | Milestone gate + assessment task |
| D8 | 自治控制面可用：pause / resume / manual replan | ✅ 已完成 | `POST /api/v1/goals/{id}/autonomy/*` |

---

### E. 审计与治理 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| E1 | Session / message / quiz 创建写 audit | ✅ 已完成 | `audit_events` 表 |
| E2 | Memory event 写入写 audit | ✅ 已完成 | `memory.event.created` audit type |
| E3 | LLM 调用成功/失败写 audit | ✅ 已完成 | `llm.chat.completed/failed` |
| E4 | Workflow run 失败写 durable audit（不被事务回滚吞掉） | ✅ 已完成 | Durable audit path |
| E5 | Task / goal / profile 关键动作失败写 durable audit | ✅ 已完成 | `test_audit_durability.py` |
| E6 | 反思系统关键动作写 audit | ✅ 已完成 | `reflection.record.created/completed` 等 |
| E7 | Skill artifact lifecycle 写 audit | ✅ 已完成 | `skill.artifact.*` audit types |

---

### F. 运维防护 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| F1 | API 有基础 rate limit | ✅ 已完成 | `RateLimitMiddleware` 按 learner key / IP 限流写接口，`AGENT_EDU_RATE_LIMIT_ENABLED` 控制 |
| F2 | LLM provider 有明确超时配置 | ✅ 已完成 | `timeout_seconds` 已配置，httpx timeout 已设置 |
| F3 | LLM provider 失败有降级策略（非崩溃） | ✅ 已完成 | `CircuitBreaker` 连续失败后自动断开，冷却后半开探测，`AGENT_EDU_LLM_CIRCUIT_BREAKER_ENABLED` 控制 |
| F4 | 成本或调用量有基础 guardrail | ✅ 已完成 | `LLMCallGuard` 滚动窗口计数，`AGENT_EDU_LLM_CALL_LIMIT_ENABLED` 控制，`/guardrails/status` 可查 |
| F5 | 关键告警可通知（不只是规则文件） | ✅ 已完成 | `AlertDispatcher` 写 alert log + 可选 webhook，限流/调用量耗尽时自动触发 |
| F6 | Worker / autonomy job 有 lease 恢复和 retry/backoff | ✅ 已完成 | `memory_maintenance_jobs` + `scheduled_autonomy_jobs` |

---

### G. 验证基线 `MUST`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| G1 | 存在一条端到端 MVP smoke test，串联主链路 | ✅ 已完成 | `tests/test_mvp_acceptance.py`，覆盖 A→B→C→D→E |
| G2 | Docker compose 下可重复执行 smoke | ⚠️ 部分 | `test_docker_blackbox.py` + `test_live_smoke.py` 存在，但未串联完整 MVP 链路 |
| G3 | 单元测试覆盖核心 service | ✅ 已完成 | 38 个测试文件，覆盖 session/chat/quiz/memory/task/goal/reflection/skill |
| G4 | API 集成测试覆盖主要端点和错误路径 | ✅ 已完成 | `test_api_integration.py` 30+ 测试 |
| G5 | `make` 命令可一键执行 MVP 验证 | ✅ 已完成 | `make mvp-check` 构建镜像并执行端到端验收测试 |

---

### H. 后台任务系统边界 `SHOULD`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| H1 | `TaskPlanLifecycleService` 主路径事务边界清楚 | ⚠️ 部分 | callback 仍存在，需收口 |
| H2 | `TaskAutonomySchedulingService` 不再依赖 legacy core 私有方法 | ⚠️ 部分 | callback 桥接中 |
| H3 | `AutonomousTaskService` 收敛为纯委托空壳 | ⚠️ 部分 | 仍有非委托逻辑 |
| H4 | 关键后台路径有明确 reentry / retry / failure 语义 | ✅ 已完成 | lease + retry + durable audit |

---

### I. 产品表面 `SHOULD`

| # | 验收项 | 当前状态 | 验证方式 |
|---|--------|----------|----------|
| I1 | Learner 可通过 Web UI 创建/进入学习会话 | ❌ 未完成 | 需前端实现 |
| I2 | Learner 可通过 Web UI 连续提问、看解释、做 quiz、拿 hint | ❌ 未完成 | 需前端实现 |
| I3 | Learner 可通过 Web UI 查看任务/复习上下文 | ❌ 未完成 | 需前端实现 |
| I4 | Operator 可通过 Web UI 查看关键治理/audit 信息 | ❌ 未完成 | 需前端实现 |

> **注**：I1-I4 是产品级 MVP 的必要条件。如果当前 MVP 定义限定为"后端 MVP"，则 I1-I4 可降级为 `NOT IN MVP`。团队需明确决定。

---

### 明确不属于 MVP 验收项

以下内容**不纳入** MVP 验收清单，无论其当前完成度如何：

| 排除项 | 所属阶段 |
|--------|----------|
| 多 agent society / 多角色协作 | Phase 6 |
| 通用 branching / looping / DAG tool-plan interpreter | Phase 5+ |
| bundle / global rollout | Phase 4+ |
| 全面 auto skill evolution（auto activate / auto replace） | Phase 5 |
| 所有 surface 的 auto-governance | Phase 5 |
| 完整 connector / plugin 生态 | Phase 2+ |
| 长期全自动后台自治体 | Phase 2+ |
| 生产级运维自动化闭环 | 运维 |
| 长期记忆动态阈值 / 精细化 topic 对齐 | Phase 3 增强 |
| 更深的 prompt / workflow optimization | Phase 4 增强 |

---

### 验收执行规则

1. **MUST 项全部通过** = 后端 MVP 技术验收通过
2. **SHOULD 项 80% 通过** = 产品 MVP 验收通过（需团队确认 I1-I4 是否纳入）
3. 每项验证方式列出的测试/命令为推荐验证手段，实际执行时可调整
4. 验收结果应记录在 CI 或手动验收报告中，不可仅口头确认
5. 本文档修改需经团队 review，不可单方面扩大或缩小 MVP 范围
