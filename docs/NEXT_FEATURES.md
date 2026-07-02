# agent_edu 后续功能收口建议

## 文档定位

这份文档用于回答一个问题：

> 在 I1-I4 Web 产品表面已经完成后，`agent_edu` 后续最应该继续做哪些功能。

它不是长期路线图，也不是所有技术债清单。它聚焦于当前 MVP 之后、公开发布前最值得投入的功能和工程收口项。

当前判断：

- 不建议继续大规模新增 learner 页面。
- 不建议把每个后端能力都机械映射成单独 Web 页面。
- 应优先让现有后端治理链路更稳定、更可解释、更可回归。

---

## 总体推荐

下一阶段优先级应从“补产品表面”切换为“后端治理链路收口”：

1. 收口 `skills.py` 巨型服务，降低 skill evolution 继续扩展时的回归风险。
2. 强化 memory / reflection / skill 之间的安全串联和失败恢复。
3. 固化 Docker 下可重复的 MVP smoke / regression 验证基线。
4. 补齐 operator 面向治理对象的详情、证据和审核操作，而不是继续扩 learner 页面。
5. 对运行防护、审计、告警和成本 guardrail 做发布前收口。

---

## P0：发布前必须优先收口

### 1. 拆分 `skills.py` ✅ 已完成

**状态**：已完成（2026-07-02）

**执行结果**：

- 原始 `skills.py`（4755 行）已拆分为 `application/services/skill/` 子包，包含 13 个职责单一的模块。
- `skills.py` 降级为 89 行的向后兼容 facade，仅做 re-export。
- 所有 178 个相关测试通过，原有 API/worker/tests 导入路径保持兼容。
- 无循环依赖，模块职责边界清晰。

**拆分后的模块结构**：

- `constants.py`：常量和阈值
- `protocols.py`：跨服务协议定义
- `observability.py`：指标刷新函数
- `catalog.py`：只读 artifact 查询
- `candidates.py`：proposal 到 candidate 的 materialization
- `readiness.py`：replacement readiness 评估
- `lifecycle.py`：artifact 状态流转（唯一入口）
- `replacement_staging.py`：replacement proposal staging 编排
- `recommendations.py`：curator recommendation 管理
- `curator_job.py`：后台 curator job 扫描和推荐生成
- `resolution.py`：运行时 skill resolution
- `usage.py`：usage 事件记录和查询

**详细执行记录**：见 `plan/SKILLS_PY_SPLIT_PLAN.md`

---

### 2. ~~收口 task / autonomy callback 边界~~ ✅ 已完成（2026-07-02）

已完成：

- `GoalStateSyncCallback` 已移除，`TaskPlanLifecycleService` 改用显式 `TaskAutonomyStateCoordinator` 依赖。
- `ProcessAutonomyJobCallback` 已移除，dispatcher 为唯一执行路径，unsupported job type fail closed。
- `failure_reflection_callback` 已移除，`TaskExecutionService` 改用显式 `TaskFailureReflectionCoordinator` 依赖。
- `autonomy_jobs/handlers.py` 不再依赖 `AutonomousTaskService`，不再调用 `_process_*_job` 私有方法。
- `container.py` 不再通过 `core._private` 字段获取 service，全部改用 public accessor properties。
- 所有 16 个 job type 注册到 dispatcher，无 fallback callback。
- 485 tests passed。

执行记录：`plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_EXECUTION_RECORD.md`

---

### 3. ~~固化 MVP 验证基线~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- 新增 `docs/LOCAL_DEV_RUNBOOK.md` 统一 runbook，覆盖启动、验证与排错。
- 固化 6 层 triage order：process → health → logs → browser network → config → DB/worker。
- 补齐 Make 入口：`smoke-api`、`smoke-stack`、`logs-api`、`logs-worker`、`ps`、`frontend-dev-doc`。
- 定义 frontend integration smoke checklist（页面加载、goals、sessions、workspace、operator）。
- 修正 README 文档漂移，清理末尾残留日志。
- 重写 frontend README，从 Vite 模板替换为项目级说明。

**交付物**：

- `docs/LOCAL_DEV_RUNBOOK.md`：统一启动、验证、排错文档
- `README.md`：清理漂移内容，增加 frontend 入口
- `packages/frontend/README.md`：项目级前端说明
- `Makefile`：6 个新增 target

**详细执行记录**：见 `plan/DOCKER_LOCAL_DEV_EXPERIENCE_PLAN.md`

---

## P1：后端治理链路增强

### 4. Memory 质量与回归增强

当前状态：

- long-term memory 已具备最小治理闭环。
- 自动沉淀、candidate、evidence、governance、operator intervention 已形成基础链路。
- `memory.py` 拆分进行中（Phase 1-2 已完成，8 个模块已提取到 `learner_memory/` 子包）。

后续建议：

- 增强 topic 对齐和 memory normalizer 规则。
- 建立长期记忆回归样例集。
- 增加 conflict set 的端到端测试。
- 强化 suppressed / archived 状态不会被自动恢复的回归覆盖。
- 增加 memory evidence 的质量评分和退化检测。
- 继续 `memory.py` 拆分 Phase 3-5（candidate/upsert、evidence/governance/conflicts/batches、facade 瘦身）。

不建议：

- 不要让自动 materialization 直接写入 `active` / `stable`。
- 不要把模型推断直接作为高信任长期记忆。

---

### 5. Reflection outcome 到 skill evolution 的闭环质量

当前状态：

- reflection 可以进入 proposal / sandbox / evaluation / approval / artifact handoff。
- 但完整动态技能系统仍未完成。

后续建议：

- 增强 reflection outcome evaluation 的 replay 覆盖。
- 补齐无效反思、重复反思、低证据反思的拒绝路径。
- 强化 `reflection -> skill_patch_request -> replacement skill_package` 的失败恢复。
- 为 reflection-driven proposal 增加更清晰的 provenance 和 evidence snapshot。

验收标准：

- 低质量 reflection 不会进入 governed skill artifact 路径。
- proposal 创建失败时 recommendation / reflection 状态保持可恢复。
- 所有关键状态变化有 durable audit。

---

### 6. Skill runtime binding 逐步动态化

当前状态：

- `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 已接入 skill resolution 与 usage。
- runtime behavior 仍偏保守，主要依赖 static implementation binding、runtime directives、goal binding 和 resolver gate。

后续建议：

- 先扩展 governed artifact 的 resolution probe 和 readiness 解释能力。
- 再逐步扩大 active / stable artifact 对 runtime behavior 的影响范围。
- 每扩大一个 surface，都必须补齐 allowlist、compatibility contract、audit、fallback 和 failure tests。

不建议：

- 暂时不要做全面 auto activate / auto replace。
- 暂时不要做通用多步 DAG / branching tool-plan interpreter。
- 暂时不要让 unchecked model output 直接驱动 runtime tool execution。

---

## P1：Operator 产品面补强

### 7. Operator 详情页与治理操作

I4 已满足 MVP 级 dashboard，但后续真正运营需要更细的 drill-down。

建议新增或增强：

- memory detail：
  - evidence links
  - governance decisions
  - annotations
  - conflict members
  - suppress / restore / annotate 操作
- reflection detail：
  - source task / workflow / goal
  - root cause
  - proposed action
  - outcome evaluation
  - review history
- skill artifact detail：
  - version / lineage
  - runtime directives
  - readiness status
  - usage metrics
  - curator recommendations
  - activate / replace / suppress / archive 操作
- audit event detail：
  - actor
  - entity
  - event type
  - correlation id
  - failure reason

约束：

- 前端只展示和发起操作，不实现治理判断。
- 所有高风险操作必须后端鉴权、审计、fail closed。
- UI 必须覆盖 loading、empty、error、permission-denied 状态。

---

## P2：运行保护与可运营性

### 8. 成本、限流、熔断与告警通知

当前状态：

- 已有部分 metrics、dashboard、alert baseline。
- 但公开发布前仍需要更明确的运行保护。

建议补齐：

- provider 调用成本或调用量 guardrail。
- LLM / embedding provider timeout 和 fallback 策略。
- sensitive endpoint 的基础 rate limit。
- worker backlog / failure rate 告警通知。
- curator / memory maintenance / reflection job 的卡死检测。

验收标准：

- 超限时系统降级而不是无限重试。
- provider failure 不导致用户界面永久转圈。
- 高风险后台 job failure 有 durable audit 和可见告警。

---

### 9. ~~Docker 与本地开发体验收口~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- 明确唯一推荐开发模式：`backend-docker + frontend-local`。
- 新增 `docs/LOCAL_DEV_RUNBOOK.md`，覆盖：
  - 三种开发模式说明（backend-docker + frontend-local / local-local / full-stack Docker）
  - 环境变量完整说明（backend + frontend）
  - 前端启动与 API 连接配置
  - Smoke 验证步骤（backend + frontend integration）
  - 6 层固定排错顺序
  - 8 个常见问题专项诊断（blank spinner、CORS、migration、worker、skill not enabled、provider key、hot reload）
- 修正 README 文档漂移：
  - 删除末尾残留 API 日志
  - 增加 Frontend Development 入口
  - 指向统一 runbook
- 重写 `packages/frontend/README.md`：
  - 从 Vite 模板替换为项目级说明
  - 增加 API 连接配置、CORS 说明、排错指引
- 补齐 Make 入口：
  - `make logs-api` / `make logs-worker`：分离 API 和 worker 日志
  - `make ps`：查看服务状态
  - `make smoke-api`：API 健康检查
  - `make smoke-stack`：全栈验证
  - `make frontend-dev-doc`：打印前端开发说明
- 明确当前 Docker 模式边界：
  - API 无 `--reload`，worker 无源码挂载
  - 当前模式为"便于复现实验环境"，非"热开发环境"

**验收标准达成**：

- ✅ 新开发者能在一份文档内完成启动、验证和排错
- ✅ Docker 下核心 API、worker、frontend integration 能被重复验证
- ✅ 开发者不会再误以为 `make dev-up` 已包含前端服务
- ✅ blank spinner、migration 失败、worker 未运行、proxy/CORS 错误有明确排查路径

**详细执行记录**：见 `plan/DOCKER_LOCAL_DEV_EXPERIENCE_PLAN.md`

---

## 不建议近期投入

以下功能不建议作为近期重点：

- 新增大量 learner 页面。
- 把所有后端 API 都做成 Web 页面。
- 多 agent society。
- 通用 DAG / branching / looping tool-plan interpreter。
- 完整 connector / plugin 生态。
- 全面 auto skill evolution。
- staged replacement 的自动 activate / replace。
- bundle / global rollout。
- 长期全自动后台自治体。

原因：

- 这些能力会扩大治理面和测试面。
- 当前更缺的是已落地链路的稳定性、边界清晰度和可重复验证。
- 在 `skills.py`、task/autonomy callback、MVP regression 未收口前继续扩功能，会增加后续回归成本。

---

## 推荐执行顺序

### 第一阶段：工程收口

1. ~~拆分 `skills.py`。~~ ✅ 已完成（2026-07-02）
2. ~~收口 task / autonomy callback。~~ ✅ 已完成（2026-07-02）
3. ~~清理过时兼容路径和文档口径。~~ ✅ 已完成（2026-07-02）
   - 修正 README 漂移
   - 重写 frontend README
   - 新增统一 runbook

### 第二阶段：验证收口

1. ~~建立 MVP smoke / regression 命令。~~ ✅ 已完成（2026-07-02）
   - `make smoke-api` / `make smoke-stack` 已补齐
   - Frontend integration smoke checklist 已文档化
2. 补 memory / reflection / skill lifecycle 失败路径测试。
3. 补 worker retry / reentry / durable audit 测试。

### 第三阶段：治理增强

1. 增强 memory quality regression。
2. 增强 reflection outcome evaluation。
3. 增强 skill curator readiness 和 replacement evidence。

### 第四阶段：运营产品面

1. 增强 operator drill-down 页面。
2. 增加 governed action 的 UI 操作入口。
3. 增加 audit / failure / recovery 的可视化入口。

---

## 完成定义

后续功能收口不能只按“功能已能跑”判断，应同时满足：

- 有明确服务边界。
- 有清晰事务和失败语义。
- 有 audit / provenance。
- 有 permission / approval / readiness gate。
- 有 loading / empty / error 或 worker failure 的可见状态。
- 有最小回归测试。
- Docker 环境能重复验证核心链路。

满足这些条件后，`agent_edu` 才能从“功能已经很多”进入“可稳定交付和持续演进”的状态。
