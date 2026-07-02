# 成本、限流、熔断与告警通知执行计划

## 1. 文档定位

本文档用于指导 `agent-edu` 在公开发布前，把 `P2：运行保护与可运营性` 中的“成本、限流、熔断与告警通知”收口成可执行的发布前基线。

本计划不是单独补几条 Prometheus 规则，也不是把所有 provider failure 都改成“自动重试直到成功”，而是要把 request path、worker path、provider path、operator 可观测性四条线一起收口成一套统一运行保护：

- 超限时可降级或失败关闭
- provider 故障时不无限重试
- 后台 job 故障有 durable audit
- 运营侧可以看到 backlog、失败率、卡死和熔断状态

本文档只负责：

- provider 调用成本或调用量 guardrail
- LLM / embedding provider timeout 与 fallback 策略
- sensitive endpoint 基础 rate limit
- worker backlog / failure rate 告警通知
- curator / memory maintenance / reflection job 卡死检测

与其他计划的关系：

- MVP 验证基线以 [plan/MVP_VALIDATION_BASELINE_PLAN.md](/home/cl/agent-edu/plan/MVP_VALIDATION_BASELINE_PLAN.md) 为主。
- task / autonomy job 行为边界以 [plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md](/home/cl/agent-edu/plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md) 为主。
- memory 质量与维护边界以 [plan/MEMORY_QUALITY_REGRESSION_PLAN.md](/home/cl/agent-edu/plan/MEMORY_QUALITY_REGRESSION_PLAN.md) 与 [plan/MEMORY_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/MEMORY_PY_SPLIT_PLAN.md) 为主。
- reflection -> skill evolution 闭环以 [plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md](/home/cl/agent-edu/plan/REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md) 为主。
- operator 后续如何查看告警与故障对象，以 [plan/OPERATOR_DETAIL_GOVERNANCE_PLAN.md](/home/cl/agent-edu/plan/OPERATOR_DETAIL_GOVERNANCE_PLAN.md) 为主。

优先级：

1. 先保证 fail-closed 与有限退化，不追求“永不失败”。
2. 先建立稳定 contract，再扩更多 dashboard。
3. 先补 request / worker / provider 的真实保护，再补视觉展示。
4. alert 不替代 audit；告警可丢时，保护路径不能假成功。
5. 默认验证路径不依赖真实外部 provider。

## 2. 当前状态判断

当前仓库不是没有运行保护，而是“已经有一部分 guardrail 和 observability baseline，但缺统一 runtime protection 收口”。

### 2.1 已有 metrics / dashboard / alert baseline

当前已有基础观测能力：

- [packages/agent_core/src/agent_core/api/app.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/app.py)
  - `metrics_enabled` 时暴露 `/metrics`
  - 接入 `PrometheusHttpMiddleware`
- [packages/agent_core/src/agent_core/infrastructure/observability/metrics.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/observability/metrics.py)
  - 已有 HTTP、LLM、embedding、audit、workflow、memory、skill curator 等指标
- [ops/prometheus/alerts.yml](/home/cl/agent-edu/ops/prometheus/alerts.yml)
  - 已有 memory / skill 相关告警基线
- [ops/grafana/dashboards/agent-edu-overview.json](/home/cl/agent-edu/ops/grafana/dashboards/agent-edu-overview.json)
  - 已有 overview dashboard

现状结论：

1. 观测基础存在。
2. 现有告警更偏 memory / skill 质量与 backlog。
3. 针对公开发布前 runtime protection 的 provider 成本、超时退化、job 卡死、敏感接口分级限流，还没有形成统一方案。

### 2.2 已有 request path guardrail

当前已有基础 request guardrail：

- [packages/agent_core/src/agent_core/api/rate_limit.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/rate_limit.py)
  - 仅对 `/api/v1` 下 `POST / PATCH / DELETE` 做全局 fixed-window rate limit
- [packages/agent_core/src/agent_core/infrastructure/config/settings.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/config/settings.py)
  - 已有：
    - `AGENT_EDU_RATE_LIMIT_ENABLED`
    - `AGENT_EDU_RATE_LIMIT_PER_MINUTE`
    - `AGENT_EDU_LLM_CALL_LIMIT_ENABLED`
    - `AGENT_EDU_LLM_CALL_LIMIT_PER_HOUR`
    - `AGENT_EDU_LLM_CIRCUIT_BREAKER_*`
    - `AGENT_EDU_ALERT_*`
- [packages/agent_core/src/agent_core/application/services/llm_guard.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/llm_guard.py)
  - 已有 `LLMCallGuard`
- [packages/agent_core/src/agent_core/api/routes/health.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/api/routes/health.py)
  - 已暴露 `/guardrails/status`

现状结论：

1. 当前已有“调用量”级别保护，但只覆盖 LLM 调用次数，不覆盖成本。
2. 当前限流是全局写请求限流，不是按敏感路由等级分层。
3. 当前 guardrail 是进程内内存态，不适合多实例或多 worker 真实发布。
4. 当前 rate limit alert message 和 details 直接带 raw learner/operator key，违反长期安全边界。

最后一点是当前最明确的安全缺口之一。

### 2.3 已有 provider timeout / retry / fallback

当前 provider 侧并非空白：

- [packages/agent_core/src/agent_core/infrastructure/llm/dashscope_compatible_provider.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/llm/dashscope_compatible_provider.py)
  - LLM 已有：
    - timeout
    - bounded retry
    - circuit breaker 接入
- [packages/agent_core/src/agent_core/infrastructure/embedding/dashscope_compatible_provider.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/embedding/dashscope_compatible_provider.py)
  - embedding 只有 timeout
  - 没有 breaker
  - 没有 fallback
- [packages/agent_core/src/agent_core/application/services/planner.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/planner.py)
  - `study_plan` 失败后已有 deterministic fallback draft
- [packages/agent_core/src/agent_core/application/services/chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py)
- [packages/agent_core/src/agent_core/application/services/quiz.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/quiz.py)
  - chat / quiz 失败时已有 metrics + durable audit
  - 但没有统一 surface fallback matrix

现状结论：

1. fallback 目前是局部存在，不是系统策略。
2. planner 已有 fallback，但 chat / quiz / embedding retrieval 没有统一退化 contract。
3. 现有 LLM breaker 文案和所有权仍写死为 `LLM provider`，不利于扩展到 embedding。

### 2.4 前端已具备基础超时，但错误契约还不够统一

当前前端不是“天然会无限转圈”：

- [packages/frontend/src/api/client.ts](/home/cl/agent-edu/packages/frontend/src/api/client.ts)
  - 已有 `AbortController`
  - 默认请求超时 `60s`
  - timeout 时抛 `ApiError(504, ...)`
- [packages/frontend/src/App.tsx](/home/cl/agent-edu/packages/frontend/src/App.tsx)
  - `TanStack Query` 默认 `retry: 1`

现状结论：

1. transport 层已经有基础超时兜底。
2. “provider failure 不导致前端永久转圈”并非完全未做。
3. 但 429 / 503 / 504 / budget exhausted / circuit open 还没有统一成稳定 error contract 与页面级降级约定。

### 2.5 已有 job failure audit，但 job health 观测仍不完整

当前后台 job 失败已有不少 durable audit：

- [packages/agent_core/src/agent_core/application/services/memory_maintenance.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/memory_maintenance.py)
  - `memory_maintenance.job.retry_scheduled`
  - `memory_maintenance.job.failed`
- [packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py)
  - `autonomy.job.failed`
  - `long_term_memory.materialization.replay_retry_scheduled`
  - `long_term_memory.materialization.replay_exhausted`
- [packages/agent_core/src/agent_core/application/services/chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py)
  - `llm.chat.failed`
  - `embedding.query.failed`
- [packages/agent_core/src/agent_core/application/services/quiz.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/quiz.py)
  - `llm.quiz.failed`

但当前 job health 观测仍然不完整：

- `memory maintenance`
  - 有 duration metric
  - 但没有 first-class overdue / stuck metric
- `skill curator`
  - 有 pending backlog、job duration 与 alert baseline
- `reflection skill evolution curator`
  - 只有 `agent_edu_reflection_skill_evolution_total`
  - 没有独立 job duration / heartbeat / last success / backlog 告警
- `autonomy jobs`
  - 有 durable audit
  - 但没有一组独立的 backlog / failure-rate / overdue metrics baseline

现状结论：

1. “失败可追溯”已经部分具备。
2. “卡死可见”仍然不足。
3. 当前反而更擅长事后看 audit，不擅长提前靠 alert 发现 worker 已卡住或 backlog 已失控。

### 2.6 已有 alert dispatcher，但仍是最小实现

- [packages/agent_core/src/agent_core/infrastructure/observability/alerts.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/observability/alerts.py)
  - 当前 `AlertDispatcher` 只负责：
    - 追加日志文件
    - 可选 webhook

现状结论：

1. 这足以作为 MVP baseline。
2. 但还不够支撑公开发布前的分级告警、去重、归因和 operator 可见性。

## 3. 目标与非目标

### 3.1 目标

本计划应达成：

1. 为 LLM / embedding / sensitive endpoint / worker job 建立一套可解释的 runtime protection matrix。
2. provider 超限、超时、熔断、失败时，系统表现为“有界重试 + 受控降级 / fail-closed”，而不是无限重试。
3. 后台高风险 job failure 保持 durable audit，并且能够触发可见告警。
4. 对 backlog、failure rate、lease overdue、run missing 建立至少一层 Prometheus alert baseline。
5. 前端和 API 之间形成稳定错误契约，避免用户界面长期停留在 spinner。

### 3.2 非目标

本次不应做：

- 不做复杂的 FinOps 计费平台。
- 不把所有 provider 数据都写成一套新的重型账单系统。
- 不在前端自行推断是否该熔断、是否该降级。
- 不把所有失败都“自动 fallback”成看起来成功。
- 不为了运行保护继续把 `task.py`、`skills.py`、`memory.py` 变得更大。

## 4. 关键边界

### 4.1 前端边界

- 前端只消费错误契约和状态，不做运行治理判定。
- 前端可以区分 `timeout / rate limit / provider unavailable / permission denied`，但不能自行决定是否继续重试。
- “不永久转圈”依赖后端 timeout / error contract 与前端 error UI 共同实现，不是单边职责。

### 4.2 后端边界

- routes 只做鉴权、参数校验、调用 service、commit/rollback、映射 response。
- provider retry / breaker / fallback 策略应收口在 provider adapter 或显式 runtime protection service，不应散落在各个 route。
- job health 与 alert 决策应由应用服务或观测层统一输出，不应由前端猜测。

### 4.3 安全边界

- sensitive endpoint 的限流 key 必须使用安全派生标识，不得记录 raw learner/operator key。
- 所有保护失败必须 fail closed。
- 高风险路径的 audit 写入失败不得被表现成成功。

### 4.4 审计与告警边界

- audit 是 durable evidence。
- alert 是可见通知。
- alert 可以依赖 audit 或 metrics，但不能替代 audit。

## 5. 需要增强的核心问题

### 5.1 成本 guardrail 仍然缺位

当前只有 `LLMCallGuard` 的调用次数限制，没有真正的 provider 成本或 token 预算治理。

更具体地说：

- [packages/agent_core/src/agent_core/infrastructure/llm/dashscope_compatible_provider.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/llm/dashscope_compatible_provider.py) 已能解析 provider response 中的 `usage`
- 但当前并未把 `usage` 映射成统一 token / cost contract
- [packages/agent_core/src/agent_core/domain/entities/skill/usage.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/domain/entities/skill/usage.py) 虽有 `cost_units`
- 但它属于 skill runtime usage 语义，不应被直接冒充为系统总 provider 花费账本

结论：

- 当前系统能数“调用次数”，但还不能稳定管“花费规模”。

### 5.2 当前 rate limit 太粗，而且泄露 raw credential

当前 rate limit 问题不是“没有”，而是“过于粗糙且有安全问题”：

1. 只区分写请求，不区分高风险程度。
2. 不区分 operator 高风险 mutation 与普通 learner 写入。
3. 只做单阈值，不支持 burst + sustained。
4. 使用原始 access key 作为 key 与 alert details，后续日志链路有泄露风险。

这项必须在公开发布前收口。

### 5.3 breaker 只覆盖 LLM，不覆盖 embedding

当前最直接的 provider gap：

- LLM 有 breaker
- embedding 没有 breaker
- embedding failure 可能直接把 retrieval / materialization 路径拖成慢失败

如果继续保持这样，`provider failure 不导致用户界面永久转圈` 只能部分满足。

### 5.4 fallback 策略按 surface 漂移

当前 fallback 行为是分散的：

- `study_plan` 有 deterministic fallback
- `chat` / `quiz` 失败主要是 audit + 抛错
- embedding retrieval 失败后的 degrade 语义没有固化成系统规则

问题不是某个点不能工作，而是：

- 同一种 provider 故障，在不同 surface 上表现完全不同
- 后续继续扩功能时，很容易再次出现无限 retry 或 silent degrade

### 5.5 worker backlog / failure alert baseline 仍不完整

当前已有 memory / skill 相关告警，但还缺：

- autonomy job backlog / failure rate
- reflection curator run missing / failed
- memory maintenance overdue claimed jobs
- provider circuit open / budget exhausted
- repeated provider timeout

如果这些不补，公开发布后最容易出现的问题是：

- 用户界面报错了
- audit 里也有失败
- 但 operator 不会被及时通知

### 5.6 job 卡死检测尚未成为一等 contract

当前 repository 层虽然已有 lease 字段：

- `ScheduledAutonomyJobModel.lease_owner / lease_expires_at`
- `MemoryMaintenanceJobModel.lease_owner / lease_expires_at`

但还没有稳定的：

- overdue gauge
- last success timestamp
- job heartbeat
- run missing alert

这意味着“任务其实已经卡住，但表面上没有 failed”时，当前系统不够敏感。

### 5.7 前后端错误契约还没有把运行保护闭环起来

当前前端 transport timeout 已有，但 API error contract 还没把这些场景稳定区分：

- `rate_limit_exceeded`
- `provider_budget_exhausted`
- `provider_timeout`
- `provider_unavailable`
- `circuit_open`
- `background_job_overloaded`

这会导致：

- 有些页面能显示 error
- 但 operator 和 learner 看不到一致的恢复动作与可理解提示

## 6. 推荐技术实现

### 6.1 是否需要重构

需要，但应是定向小规模重构，不应继续往现有大文件里堆逻辑。

推荐新增一个明确所有权的 runtime protection 边界，例如：

```text
packages/agent_core/src/agent_core/application/services/runtime_protection/
  budgets.py
  provider_guard.py
  job_health.py
  error_contract.py
```

原则：

- provider guardrail 不塞进 `task.py`
- job stuck detection 不塞进 `skills.py`
- 成本 guardrail 不直接复用 `SkillUsageEvent.cost_units` 冒充系统账单

### 6.2 成本 / 调用量 guardrail

推荐建立两层 provider budget contract：

1. `call volume`
2. `cost units / token usage`

推荐最小 contract：

- `scope`
  - `global`
  - `provider`
  - `model`
  - `surface`
  - `actor_kind`
- `window`
  - `minute`
  - `hour`
  - `day`
- `usage`
  - `request_count`
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - `estimated_cost_units`
- `decision`
  - `allow`
  - `warn`
  - `degrade`
  - `reject`

推荐实施方式：

1. 在 LLM provider adapter 中提取 `usage`，统一映射为内部 usage snapshot。
2. embedding provider 若上游返回 usage，则读取真实值；否则至少记录 `request_count` 与 `input_size` 近似量。
3. guard counter 不使用进程内 list 作为生产真实基线，生产环境改为 Redis 或 DB-backed rolling counter。
4. 仍保留当前 in-memory guard 作为 dev fallback。
5. 超限时：
   - 交互式 surface 优先返回 typed error
   - 可确定性 fallback 的 surface 允许降级
   - 高风险后台 job 直接 fail closed 或转 replay / retry-scheduled

不建议直接做：

- 用 `SkillUsageEvent.cost_units` 覆盖所有 LLM / embedding 成本。

原因：

- skill usage 是 runtime artifact 视角，不是全系统 provider 账本视角。

### 6.3 LLM / embedding timeout、retry、breaker、fallback 策略

建议把 provider 保护固化为 surface policy matrix，而不是“哪里报错了就哪里补一段 except”。

推荐矩阵：

1. `chat / hint`
   - LLM timeout：短超时 + bounded retry
   - embedding failure：允许跳过 long-term retrieval，继续无 memory context 应答
   - LLM failure：返回 typed `provider_unavailable` / `provider_timeout`
   - 不做“伪成功答案” fallback
2. `quiz`
   - LLM timeout：bounded retry
   - 失败：返回 typed error，不本地伪造题目
3. `study_plan / replan / assessment_generation`
   - LLM timeout：bounded retry
   - 失败：允许 deterministic fallback 或转后台 retry-scheduled
   - fallback 必须记录 audit、metric、`fallback_used`
4. `memory retrieval / materialization`
   - embedding timeout / breaker open：降级为无 embedding retrieval，或 replay / retry-scheduled
   - 不得把不完整 embedding 结果写成已成功状态

技术建议：

1. 将现有 `CircuitBreaker` 泛化为 provider-scoped breaker，而不是 LLM 专用文案。
2. 为 embedding provider 增加同级 breaker。
3. 为 breaker open、retry exhausted、fallback used 输出统一 metrics 与 audit event。
4. provider retry 保持有界，禁止在 route/service 层叠加第二轮无限 retry。

### 6.4 sensitive endpoint 分级限流

推荐从“全局写请求单阈值”升级到“按路由族 + 身份类型”的基线分层。

建议分层：

1. learner 交互写入
   - 例如 session message、quiz submit
2. operator 高风险 mutation
   - suppress / restore / review / activate / replace / archive
3. auth / credential-sensitive path
4. background callback / internal path

推荐能力：

- `burst limit`
- `sustained per-minute limit`
- `scope key`
  - learner hashed id
  - operator hashed id
  - client IP fallback
- `Retry-After` header
- typed `rate_limit_exceeded` error body
- limit exceed event alert

强制要求：

- rate-limit key 与 alert details 使用安全派生标识，不记录 raw access key。

生产建议：

- production 使用 Redis-backed limiter
- local/dev 保留 current fixed-window limiter

### 6.5 worker backlog / failure rate / stuck detection 指标

推荐新增一组真正面向运行保护的指标，而不是只看业务质量指标。

最低建议新增：

- `agent_edu_provider_guardrail_events_total`
  - `provider`
  - `surface`
  - `event`
- `agent_edu_provider_budget_remaining`
  - `provider`
  - `window`
  - `scope`
- `agent_edu_provider_circuit_state`
  - `provider`
  - `state`
- `agent_edu_autonomy_jobs_backlog`
  - `job_type`
  - `status`
- `agent_edu_autonomy_job_runs_total`
  - `job_type`
  - `status`
- `agent_edu_autonomy_job_duration_seconds`
  - `job_type`
  - `status`
- `agent_edu_autonomy_job_lease_overdue`
  - `job_type`
- `agent_edu_memory_maintenance_jobs_overdue`
  - `job_type`
- `agent_edu_job_last_success_timestamp`
  - `job_family`
- `agent_edu_job_last_failure_timestamp`
  - `job_family`

其中 `job_family` 至少包括：

- `memory_maintenance`
- `skill_curator`
- `reflection_skill_evolution_curator`
- `autonomy_dispatch`

### 6.6 告警与通知策略

推荐分两层：

1. metrics-based alert
2. application-level alert dispatch

#### Metrics-based alert

建议新增或增强 Prometheus 规则：

- `ProviderBudgetNearExhaustion`
- `ProviderBudgetExhausted`
- `ProviderCircuitOpen`
- `EmbeddingFailureRateHigh`
- `AutonomyJobBacklogHigh`
- `AutonomyJobFailureRateHigh`
- `AutonomyJobLeaseOverdue`
- `MemoryMaintenanceJobsOverdue`
- `ReflectionCuratorRunMissing`
- `SkillCuratorRunMissing`

#### Application-level alert

建议在以下事件上直接触发 `AlertDispatcher.dispatch(...)`：

- provider budget exhausted
- provider circuit opened
- autonomy job failed after retries exhausted
- memory maintenance job failed after retries exhausted
- reflection curator pass failed
- repeated rate limit exceed on protected operator paths

这样做的原因：

- Prometheus 适合看趋势与阈值
- application alert 适合第一时间把单次高风险故障打到 webhook

### 6.7 job 卡死检测 contract

建议建立统一 `JobHealthService` 或等价 contract，负责：

- `record_started(job_family, run_id, started_at)`
- `record_progress(job_family, run_id, cursor, heartbeat_at)`
- `record_completed(job_family, run_id, completed_at)`
- `record_failed(job_family, run_id, failed_at, error_code)`

对 queue-backed job：

- backlog 从 repository 统计
- overdue 依据 `due_at / lease_expires_at / status / attempt_count` 计算

对 periodic `run_once` 类 job：

- 必须更新 `last_success_timestamp`
- 告警规则按“超过预期窗口未成功运行”判断

这一步是“卡死检测”的核心，没有它就只能看失败日志，不能看 run missing。

### 6.8 前端非永久 spinner 的契约化收口

当前前端已有 60 秒 transport timeout，但仍需把运行保护错误显式契约化。

推荐后端统一错误码：

- `rate_limit_exceeded`
- `provider_budget_exhausted`
- `provider_timeout`
- `provider_unavailable`
- `provider_circuit_open`
- `background_job_overloaded`

推荐前端统一行为：

1. query error 时停止 spinner，进入 error state。
2. 对 429 / 503 / 504 展示可恢复提示与 retry action。
3. 对长任务型动作，显示 `pending -> failed` 或 `pending -> retry-scheduled`，不维持无界 loading。

这不是让前端决定运行保护，而是让前端正确消费运行保护结果。

## 7. 推荐执行阶段

### Phase 0：冻结运行保护矩阵

目标：先把现有保护与缺口写死，避免边做边改语义。

执行：

1. 列出所有 LLM / embedding surface。
2. 列出所有 sensitive endpoint 路由族。
3. 列出所有后台 job family。
4. 明确每一类对象的：
   - timeout
   - retry
   - breaker
   - fallback
   - alert
   - audit

完成标准：

- 有一份 runtime protection matrix。
- 不再把“有 timeout”误当成“已有完整运行保护”。

### Phase 1：补 provider usage 与 budget guardrail

目标：先把调用量 / token / cost contract 建起来。

执行：

1. LLM provider 抽取 usage snapshot。
2. embedding provider 抽取 request usage 近似值或真实 usage。
3. 引入 budget counter storage。
4. 输出：
   - metrics
   - audit
   - guard decision

完成标准：

- 系统能回答“哪个 provider / model / surface 正在消耗多少预算”。
- 超限时返回明确 decision，而不是继续无限重试。

### Phase 2：补 provider timeout / breaker / fallback matrix

目标：让各 surface 对 provider 故障的行为稳定下来。

执行：

1. 泛化现有 breaker。
2. embedding provider 接 breaker。
3. 固化 `chat / quiz / study_plan / replan / memory retrieval` 的 degrade matrix。
4. 输出统一 error code。

完成标准：

- provider failure 不再依赖调用方各自处理。
- planner fallback、chat fail-fast、embedding degrade 都有明确边界。

### Phase 3：升级 sensitive endpoint rate limit

目标：从粗粒度全局写限流升级为分级限流。

执行：

1. 按路由族定义 limit policy。
2. key 改为安全派生 actor id。
3. production 路径使用 Redis-backed limiter。
4. 保留 dev fixed-window fallback。

完成标准：

- operator 高风险 mutation、learner 高频写入、auth 相关路径有不同保护强度。
- alert 与日志不再暴露 raw credential。

### Phase 4：补 job backlog / overdue / run-missing 指标与告警

目标：让 worker 故障不再只靠人工翻 audit。

执行：

1. autonomy job 指标补全。
2. memory maintenance overdue gauge 补全。
3. reflection curator last-success / run-missing contract 补全。
4. 更新 Prometheus alert rules 与 Grafana dashboard。

完成标准：

- backlog、failure-rate、lease-overdue、run-missing 至少各有一层 alert baseline。

### Phase 5：补 application-level alert 与通知落点

目标：把高风险单次故障推送到可见渠道。

执行：

1. 关键 guardrail breach 直接触发 `AlertDispatcher`。
2. 高风险 job exhausted failure 直接触发 `AlertDispatcher`。
3. 明确 webhook payload contract。

完成标准：

- 严重 provider / job 故障不仅留在 audit，还能主动通知。

### Phase 6：前端错误消费、回归与运行手册收口

目标：让“保护生效”在用户和 operator 侧都可见。

执行：

1. 前端统一消费 typed error。
2. learner / operator 页面不再因 provider failure 长时间 spinner。
3. 更新 runbook 与 baseline 文档。

完成标准：

- UI 可稳定退出 loading。
- 运维可根据 runbook 识别：限流、熔断、预算超限、job backlog、job stuck。

## 8. 关键难点与应对

### 8.1 provider usage 数据不稳定

难点：

- 不同 provider 的 usage 字段不一致。
- embedding 甚至可能没有真实计费字段。

应对：

- 先建立统一 snapshot contract。
- 有真实 usage 时记录真实值。
- 没有真实 usage 时记录近似 usage，并明确标记 `estimated`。

### 8.2 进程内 guardrail 无法支撑多实例

难点：

- 当前 `LLMCallGuard` 与 `CircuitBreaker` 都是本地内存态。

应对：

- dev 保留本地内存态。
- production 引入 Redis-backed counter / breaker state。
- health / operator 面继续展示同一套抽象状态。

### 8.3 限流保护与密钥安全冲突

难点：

- 当前实现直接把 raw key 放进限流 key 和 alert。

应对：

- 统一使用安全派生 actor id。
- 限流存储、日志、alert details 都只写派生值。

### 8.4 过度 fallback 会制造“假成功”

难点：

- 如果所有 provider failure 都 fallback，看起来更平滑，但会掩盖真实故障和质量退化。

应对：

- 只对 deterministic fallback 合法的 surface 使用 fallback。
- 其余路径 typed fail-fast。
- 所有 fallback 必须记录 audit / metrics。

### 8.5 卡死检测容易误报

难点：

- 周期 job 有不同执行窗口。
- worker 暂时无流量时，不应被误报为 failed。

应对：

- 采用 `last_success + expected cadence + grace window`。
- queue-backed 与 periodic run-once 分开定义规则。
- 先从 warning 级别落地，再根据真实数据调阈值。

## 9. 边界与依赖关系

本计划与其他计划的边界如下：

- 与 `MVP_VALIDATION_BASELINE_PLAN.md`
  - 本计划定义运行保护能力。
  - 后续应把这些 guardrail / alert / fail-closed path 纳入 MVP baseline。
- 与 `TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md`
  - autonomy job 的业务边界由该文档定义。
  - 本文档只定义这些 job 的 runtime protection 与 observability。
- 与 `MEMORY_QUALITY_REGRESSION_PLAN.md`
  - memory 质量判定不在本文档内。
  - 但 memory maintenance 的 backlog、overdue、failed alert 在本文档内。
- 与 `REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md`
  - reflection / curator / rollout 语义由该文档定义。
  - 本文档只收口其运行保护与告警。
- 与 `OPERATOR_DETAIL_GOVERNANCE_PLAN.md`
  - 本文档产出的告警与故障对象，后续可作为 operator detail / dashboard 的可见输入。

## 10. 交付条件

完成本计划，至少应交付：

1. 一套 runtime protection matrix。
2. provider usage / budget guardrail contract。
3. LLM + embedding 的统一 timeout / breaker / fallback 策略。
4. sensitive endpoint 的分级 rate limit。
5. autonomy / memory maintenance / curator / reflection job 的 backlog / failure / overdue / run-missing 指标与告警。
6. 高风险后台 job failure 的 durable audit + visible alert。
7. 前端对 429 / 503 / 504 / circuit-open / budget-exhausted 的稳定错误消费。

验收标准：

- 超限时系统降级而不是无限重试。
- provider failure 不导致用户界面永久转圈。
- 高风险后台 job failure 有 durable audit 和可见告警。
- rate limit / alert 不记录 raw learner/operator key。
- 运行保护逻辑不继续堆进现有大文件。

## 11. 推荐实施顺序

推荐顺序：

1. Phase 0：冻结运行保护矩阵。
2. Phase 1：补 provider usage 与 budget guardrail。
3. Phase 2：补 provider breaker / fallback matrix。
4. Phase 3：升级 sensitive endpoint rate limit。
5. Phase 4：补 job health 指标与告警。
6. Phase 5：补 application-level alert。
7. Phase 6：补前端错误消费与回归基线。

不要先做：

- 在进程内内存 guardrail 之上继续堆更多阈值，假装已经具备 production 保护。
- 在 embedding 没有 breaker / degrade contract 的情况下承诺 provider failure 已收口。
- 在限流仍暴露 raw key 的情况下把它视为可发布实现。
- 在没有 run-missing / overdue 指标的情况下宣称 job stuck 已可运营检测。
