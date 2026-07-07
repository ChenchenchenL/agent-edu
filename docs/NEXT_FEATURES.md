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

下一阶段优先级应从”运营产品面补全与运行保护收口”切换为”运行保护收口与发布前最终验证”：

1. ~~收口 `skills.py` 巨型服务。~~ ✅ 已完成
2. ~~强化 memory 治理链路拆分与回归保护。~~ ✅ 已完成
3. ~~强化 reflection / skill 之间的安全串联和失败恢复。~~ ✅ 已完成
4. ~~固化 Docker 下可重复的 MVP smoke / regression 验证基线。~~ ✅ 已完成
5. ~~完成 skill runtime binding 逐步动态化。~~ ✅ 已完成
6. ~~补齐 operator 详情页与治理操作。~~ ✅ 已完成
7. 对运行防护、审计、告警和成本 guardrail 做发布前收口。

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

### 4. ~~Memory 质量与回归增强~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- `memory.py` 拆分全部完成（Phase 1-5），原始 ~5250 行单体文件降级为向后兼容 facade。
- 提取 15 个职责单一模块到 `learner_memory/` 子包，总计 ~5369 行：
  - `constants.py`：常量和阈值配置
  - `quality.py`：质量评分和评级
  - `result_types.py`：返回类型定义
  - `catalog.py`：只读 memory 查询
  - `retrieval.py`：memory 检索与排序
  - `interpretation.py`：memory 解释与事实提取
  - `reflection_corpus.py`：反思语料管理
  - `observability.py`：指标刷新
  - `session_events.py`：会话事件记录与学习信号提取
  - `candidate_builders.py`：candidate 构建（knowledge / behavior）
  - `upsert.py`：upsert 编排与 embedding 同步
  - `evidence.py`：evidence 链接管理与稳定性计算
  - `governance.py`：memory 状态治理（suppress/restore/annotate）
  - `conflicts.py`：conflict set 管理
  - `governance_batches.py`：批量维护、压缩、刷新、晋升评估
- 所有 578 个相关测试通过，原有导入路径保持兼容。
- 增强 topic 对齐、memory normalizer 规则、conflict set 端到端覆盖。
- 强化 suppressed / archived 状态 fail-closed 回归保护。
- 增加 memory evidence 质量评分和退化检测。

**详细执行记录**：见 `plan/MEMORY_PY_SPLIT_PLAN.md` 和 `plan/MEMORY_PY_SPLIT_EXECUTION.md`

---

### 5. ~~Reflection outcome 到 skill evolution 的闭环质量~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- 提取 `reflection_outcome_policy.py`（223 行）：纯评估 contract，不持有 repository / audit / db session，输出确定性 status / score / snapshot / note。
- 提取 `reflection_provenance.py`（246 行）：统一 reflection-sourced proposal / recommendation evidence builder，固化 source / ids / metrics / governance_evidence 结构。
- 新增 4 组闭环 fixtures（`tests/fixtures/reflection_skill_evolution/`）：
  - `outcome_evaluation_cases.json`：pending / effective / ineffective / inconclusive 状态转换矩阵
  - `reflection_feedback_cases.json`：apply_outcome_feedback 扇出语义（memory / proposal / materialization）
  - `curator_auto_stage_cases.json`：auto-governance gate matrix（high-risk / non-trusted / rate-limit / savepoint）
  - `governance_evidence_cases.json`：curator evidence 最小字段集与不越权断言
- 新增 `test_reflection_skill_evolution_regression.py`（1215 行）：5 个端到端闭环场景：
  1. effective reflection -> proposal -> sandbox -> approved -> staged replacement
  2. ineffective reflection -> governance evidence only -> no artifact mutation
  3. duplicate but low-priority reflection -> no skill package created
  4. patch_needed recommendation -> patch request -> realization -> trusted auto-stage
  5. auto-stage fail-closed（rate limit / source / approval 缺口阻断）

**验收标准达成**：

- ✅ 低质量 reflection 不会自动推进到 governed artifact staging
- ✅ 高质量 reflection 的受控推进路径可重复执行且有 durable audit
- ✅ recommendation / proposal / staging 的 provenance 字段稳定可查
- ✅ 相关测试默认不依赖真实 provider
- ✅ 后续拆分 skills.py / task.py 时，闭环规则漂移会被回归测试直接打断

**详细执行记录**：见 `plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md`

---

### 6. ~~Skill runtime binding 逐步动态化~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- 提取 `skill/runtime_readiness.py`（59 行）：定义 `RuntimeBindingReadiness` 和 `RuntimeBindingExplainResult` 纯 contract dataclass，统一 source summary、blocked reason、fallback mode、tool-plan status、staged involvement 语义。
- 提取 `skill/runtime_explain.py`（125 行）：`RuntimeExplainService` 提供 goal/surface scoped runtime binding 解释能力，side-effect free，供 operator probe/explain 使用。
- 固化 runtime source precedence contract：
  - artifact_source / directives_source / tool_plan_source 统一出口
  - resolver_status / selection_reason / artifact_status 显式 reason code
  - blocked_reason_codes / fallback_reason_codes 可观测
- 固化 staged 语义隔离：
  - `resolution_mode` 区分 production / shadow / probe
  - `staged_involvement` 区分 none / preview / probe
  - 默认生产路径不依赖 staged artifact
- 固化 surface 分级：
  - 低风险（chat / hint / quiz / plan_generation）：response behavior / directive 为主
  - 中高风险（review_scheduling / assessment_generation / replan）：tool-plan allowlist + failure audit

**验收标准达成**：

- ✅ staged binding 不会在无显式授权下进入生产 runtime
- ✅ 低风险 surface 的动态化先于 autonomy surface 扩面
- ✅ 所有 runtime blocked/fallback 决策都有 explain 和 reason code
- ✅ usage metadata、audit、rollout observation 与 runtime source contract 保持一致
- ✅ 默认测试路径不依赖真实 provider

**详细执行记录**：见 `plan/SKILL_RUNTIME_BINDING_DYNAMICIZATION_PLAN.md`

---

## P1：Operator 产品面补强

### 7. ~~Operator 详情页与治理操作~~ ✅ 已完成（2026-07-02）

**状态**：已完成（2026-07-02）

**执行结果**：

- Operator auth shell：
  - `lib/operator-auth.ts`（24 行）：operator key 存储/读取/清理，支持 localStorage（持久）和 sessionStorage（会话级）
  - `api/client.ts`（99 行）：每次请求自动注入 `X-Operator-Key` header，与 `X-Learner-Key` 并存
  - `OperatorShell`（107 行）：auth gate + 布局壳 + route guard + 登录/登出
  - `require_operator_api_key` 后端依赖：constant-time 校验 + audit trail
- 四类详情页全部落地：
  - Memory detail（`/operator/memory/:type/:id`，258 行）：详情 + evidence links + governance decisions + annotations + suppress/restore/annotate 操作
  - Reflection detail（`/operator/reflections/:id`，195 行）：root cause + proposed action + review history + outcome evaluation + related proposals + resolve 操作
  - Skill artifact detail（`/operator/skills/artifacts/:id`，166 行）：artifact 详情 + usage + suppress 操作
  - Audit event detail（`/operator/audit/events/:id`，116 行）：事件核心字段 + raw payload
- 5 个 operator hooks：`use-operator-auth.ts`（32）、`use-operator-memory.ts`（79）、`use-operator-reflection.ts`（47）、`use-operator-skill.ts`（32）、`use-operator-audit.ts`（9）
- 后端接口补口全部完成：
  - `GET /audit/events/{event_id}` 单条事件详情
  - `GET /reflections/{reflection_id}/outcome-evaluation` outcome 直读
  - `GET /memory/{memory_type}/{memory_id}/conflicts` 按 memory 查 conflict

**验收标准达成**：

- ✅ operator 能从 dashboard drill into 具体治理对象
- ✅ 所有 detail 页面覆盖 loading/empty/error/permission-denied
- ✅ 所有高风险操作继续通过后端鉴权、审计、fail-closed
- ✅ 前端不实现治理判断，只消费后端 contract

**详细执行记录**：见 `plan/OPERATOR_DETAIL_GOVERNANCE_PLAN.md`

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
- `skills.py`、task/autonomy callback、MVP regression、`memory.py` 拆分、reflection/skill 闭环质量、skill runtime binding 动态化、operator 详情页均已收口，后续投入应聚焦运行保护收口和发布前最终验证。

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
2. ~~补 memory / reflection / skill lifecycle 失败路径测试。~~ ✅ Memory + Reflection/Skill 部分已完成（2026-07-02）
3. 补 worker retry / reentry / durable audit 测试。

### 第三阶段：治理增强

1. ~~增强 memory quality regression。~~ ✅ 已完成（2026-07-02）
2. ~~增强 reflection outcome evaluation。~~ ✅ 已完成（2026-07-02）
3. ~~增强 skill runtime binding 动态化。~~ ✅ 已完成（2026-07-02）
4. 增强 skill curator readiness 和 replacement evidence。

### 第四阶段：运营产品面

1. ~~增强 operator drill-down 页面。~~ ✅ 已完成（2026-07-02）
2. ~~增加 governed action 的 UI 操作入口。~~ ✅ 已完成（2026-07-02）
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
