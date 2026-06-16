# PROGRESS_STATUS.md

## 文档定位

这份文档用于描述 `agent-edu` 当前实际实现进度。

它回答的问题不是“项目最终想做什么”，而是：

> 截至当前代码状态，哪些能力已经完成，哪些只完成了一部分，哪些还没有开始。

本状态判断基于以下内容：

- `README.md`
- `ARCHITECTURE.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `packages/agent_core` 下现有 API、service、repository、schema、LLM provider、embedding provider 实现
- `alembic` 迁移
- `tests` 下现有测试

---

## 当前总体判断

项目当前处于：

> Phase 1（稳定教学 Agent）已基本打通主链路，并进入 Phase 2（自主任务系统）的最小落地阶段；当前产品表面方向已调整为 Web-first，既有 CLI / TUI baseline 仅作为历史实现与参考资产保留。

更具体地说：

- 后端骨架已经完成
- 学习会话、教学对话、概念讲解、练习题生成、session memory retrieval 的主链路已经落地
- long-term memory governance v2（知识 / 行为双通道 + 治理状态 + 运营干预）已经落地到最小完整版本
- long-term memory governance 已进一步补齐动态强化 / 衰减刷新、证据链同步和反思语料导出
- 长期记忆自动沉淀链路已接入 chat / task outcome / reflection outcome，并支持 upsert / dedupe 与 provenance 追踪
- `LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun` 的最小闭环已经落地
- Phase 2.1 的最小自治层和 worker baseline 已落地
- Reflection System v1 已落地，v2 增强版已部分落地
- 架构重构已完成 `repositories.py` 拆分 (Task #7) 与领域实体文件拆分 (Task #9)。
- TaskRuntimeSkillService 已完成拆解与清理 (Task #15 完成)：runtime-plan resolution、tool-plan execution、execution context 构建、runtime skill resolution、rollout observation 调度、overlay 查询、skill binding 查询与 review interval 解析均已独立实现；未使用的 `core` 注入已移除、容器接线已清理，且注释和文件头描述已同步更新。
- 这轮已进一步补齐：
  - review queue 聚合优先级主链
  - outcome evaluation 真正闭环
  - strategy card 更深作用到 planner
  - periodic goal reflection 最小入口
  - proposal queue / replay-eval 最小闭环
  - prompt / workflow proposal v1 的 sandbox / approval / evaluation read API
  - proposal rollout / rollback v1 扩展到 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan`
  - rollout overlay 进入 chat / planner / task runtime
  - skill evolution 最小治理闭环已部分落地：
    - `skill_package` proposal 类型
    - `SkillArtifact` 版本化资产
    - `SkillUsageEvent` 使用记账
- `SkillCuratorRecommendation` 治理建议承载层与 operator review API
- `SkillCuratorJob` MVP 周期性治理建议生成
- `patch_needed` recommendation accept 已接入 `skill_patch_request` proposal 创建路径
- approved / effective `skill_patch_request` 已可 realization 为新的 replacement `skill_package` proposal
- `merge_candidate` recommendation accept 已可创建 merge-sourced replacement `skill_package` proposal
- artifact overlap / duplicate detection 已接入 `SkillCuratorJob`，可生成 `merge_candidate / none` recommendation，且不直接修改 artifact
- curator governance evidence v1 已接入 memory conflict summary、reflection outcome evaluation 和 resolver health trend，可生成或增强 `flag_for_review / none` recommendation，且不直接修改 artifact
- surface / topic coverage regression 已接入 `SkillCuratorJob`，可基于声明外 topic demand 与 governed binding gap 生成 `patch_needed / none` recommendation，且不直接修改 artifact
- approved / effective replacement `skill_package` proposal 已可通过 operator-protected staging API 生成 `staged` replacement artifact
- artifact lifecycle：candidate / staged / active / stable / deprecated / suppressed / archived
- suppress / restore runtime kill switch
- rollout rollback 联动 artifact deprecate
- dynamic runtime registry V1 已统一 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 的 execution-plan resolution / usage metadata sourcing，并把 registry/source 摘要写入 usage metadata
- `chat / quiz / plan_generation` 已与 task/autonomy 侧对齐到同一套 runtime usage metadata helper，不再各自维护分散的 execution-plan metadata 拼装
- task/autonomy 已不再在 service 本地重复拼 runtime/source metadata；fallback path 也统一复用 runtime registry contract builder
- `review_scheduling / assessment_generation / replan` 已在 task/autonomy 端端到端保留 `RuntimeSkillExecutionPlan`
- task/autonomy usage attribution 已统一收口到公共 helper；`review_scheduling / assessment_generation / replan` 不再各自维护分散的 usage metadata 拼装
- `chat / hint / quiz / plan_generation` 的 rollout observation 已在成功路径接通；`chat / hint` 使用 assistant message id，`quiz` 使用 quiz id，`plan_generation` 使用成功 workflow run id，并且 `plan_generation` 的 observation 只会在 plan/task 持久化成功之后调度
- allowlisted autonomy workflow surface 的 rollout observation 已对 `review_scheduling / assessment_generation / replan` 接通成功路径，并对有真实 workflow run anchor 的 runtime failure 接通失败路径；`skipped` 与 validation / precondition failure 仍不进入 observation
- rollout auto-governance V1 已落地独立 decision job，并对 allowlisted workflow surfaces 自动执行 rollout `promote / rollback`
- 历史 CLI/TUI 资产（dual-mode client、workspace summary API、TUI baseline）已落地并保留为参考实现
- 真实 LLM / embedding 的接入已经不是“配置层预留”，而是“代码层可执行”
- 但长期记忆治理仍属于“最小完整落地”，第二阶段定时调度与更强自治仍未完成；skill evolution 也仍是“最小治理闭环部分落地”，`SkillCuratorRecommendation` 与周期性 `SkillCuratorJob` MVP 已落地，`archive_candidate` accept 已接入 archive lifecycle，`patch_needed` accept 已能创建 reference-only `skill_patch_request` proposal，approved / effective `skill_patch_request` 已能 realization 为新的 replacement `skill_package` proposal，artifact overlap / duplicate detection 已能生成 `merge_candidate` 输入，`merge_candidate` accept 已能创建 merge-sourced replacement `skill_package` proposal，curator governance evidence v1 已能消费 memory conflict summary / reflection outcome evaluation / resolver health trend，surface / topic coverage regression 已能基于声明外 topic demand 与 governed binding gap 生成 `patch_needed` 输入，skill observability 已有 Prometheus / Grafana / alert 基线，approved / effective replacement proposal 已能 operator staging 为 `staged` replacement artifact，且 staged governed replacement 已补齐 readiness API、strict source-anchor gate、curator ready recommendation 与 activate / replace 证据硬化；dynamic runtime registry V1 已扩到 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 的 execution-plan consumption，tool-plan orchestration V2/V3 已补 internal-only、sandbox/runtime 同构的受控执行器，并支持最多 2 步的 linear chain 与 prior-step output 引用；rollout auto-governance V1 已补独立 decision job、配置化开关与 surface allowlist、Prometheus / Grafana / alert 基线，并默认只对 `review_scheduling / assessment_generation / replan` 自动执行 promote / rollback；但更高阶 orchestration、更多跨 surface 组合、更广覆盖的 auto-governance 和 staged replacement 自动执行仍未完成；长期记忆告警规则基线已落地，动态阈值、告警通知和生产回归还在继续增强

当前代码状态更接近：

> 真实教学链路已打通，正在从“可运行”走向“可稳定验证”，并开始具备最小学习任务组织能力。

---

## 已完成

### 1. 基础工程骨架

已完成内容：

- FastAPI 应用装配
- 基础路由注册
- 配置加载
- 数据库与 Redis 依赖注入骨架
- Alembic 迁移骨架

说明：

- API 服务已经可以作为独立后端运行
- 工程结构基本符合 `apps / packages / docs` 分层思路

---

### 2. 第一阶段核心数据模型

已完成内容：

- `LearningSession`
- `SessionMessage`
- `MemoryEvent`
- `MemoryEmbeddingRecord`
- `AuditEvent`
- `SessionQuiz`
- `SessionQuizQuestion`

数据库层已建表：

- `learning_sessions`
- `session_messages`
- `session_memory_events`
- `session_memory_embeddings`
- `session_quizzes`
- `session_quiz_questions`
- `audit_events`

说明：

- 第一阶段需要的最小数据承载结构已经存在
- `message_count`、`last_activity_at`、`summary` 也已补充到 session 模型中
- quiz 与 memory embedding 的持久化承载都已经就位

---

### 3. 学习会话功能

已完成内容：

- 创建学习会话
- 获取单个学习会话
- 列出学习会话
- 更新会话状态

说明：

- 会话已经成为消息、记忆和练习题的承载单元
- `active / archived / completed` 状态控制已存在

---

### 4. 基础消息历史读取能力

已完成内容：

- 在 session 下写入消息
- 按 session 读取消息历史
- 支持 `before_id` 分页游标
- 返回 `total` 与 `next_before_id`
- assistant message 已支持结构化 `content_payload`

说明：

- 这部分已经具备连续会话的基础读取能力
- 历史记录已经能保留结构化教学回复

---

### 5. 技能注册最小闭环

已完成内容：

- 技能白名单配置入口
- `SkillRegistry`
- mode 到 skill 的映射

当前已接入技能名：

- `explain_concept`
- `create_quiz`
- `adaptive_hint`
- `plan_study_path`
- `schedule_review`

说明：

- 目前的 skill 已经可以真实参与链路
- `skill_trace` 会落到消息和 quiz 记录中

---

### 6. 真实模型与 embedding 接入

已完成内容：

- LLM provider 配置已正式进入 `settings`
- per-capability model override 已支持
- embedding provider 配置已正式进入 `settings`
- DashScope 兼容聊天接口与 embedding 接口均已有 provider 实现
- `.env.example` 已补齐真实 API 与 embedding 的示例配置

说明：

- 当前代码已经不再只支持 mock 配置
- 真实 API 接入已经从“文档预留”变成“代码支持”

---

### 7. 概念讲解功能

已完成内容：

- `chat` 模式会映射到 `explain_concept`
- 回复会明确走“解释型”教学提示词，而不是普通闲聊
- 已接入真实模型调用，不再只依赖模板回复
- 已返回结构化 assistant payload
- 结构字段已经覆盖 `定义 / 原理 / 例子 / 常见误区 / 下一步`

说明：

- 概念讲解已经不是模板拼接，而是结构化教学输出链路
- 这条链路已经可以在 mock 和真实 provider 下工作

---

### 8. 练习题生成功能

已完成内容：

- 已有 `/quizzes/generate` 接口
- 支持 `topic / difficulty / question_count`
- 能返回结构化题目和参考答案
- `create_quiz` 已能出现在 `skill_trace`
- 已支持使用真实 LLM provider 生成 quiz JSON
- 已支持 session 绑定、持久化、列表和详情读取

说明：

- 练习题已经不是一次性草稿，而是 session 内的可追踪对象
- 生成、存储、查询三条链路都已经接通

---

### 9. 教学对话功能

已完成内容：

- 用户可以在 session 下提交消息
- 系统会返回 assistant 回复
- 每轮对话会保存 user message 与 assistant message
- assistant message 会记录 `skill_trace`
- 已支持使用真实 LLM provider 生成回复
- 已会读取最近 session message history
- 已会注入 retrieval 得到的 memory context
- 已形成 session 内 learner profile 与跨 session long-term profile 的最小注入链路
- 已加入 gated live smoke test
- 已在 Docker 环境中跑通真实 chat / hint / quiz smoke
- `turn_metrics` 已可回传并记录 history、memory、cross-session、latency、shape 状态

说明：

- 这条链路已经从“能跑”推进到“能在 Docker 里重复验证”

---

### 10. 自适应提示功能

已完成内容：

- `hint` 模式链路已存在
- `hint` 会映射到 `adaptive_hint`
- 回复风格与普通 `chat` 模式有明显区分
- 已支持真实模型下的 hint 提示词链路
- 返回的是结构化 hint payload
- 已支持基于 quiz 题目、学习者错误答案、历史 hint 次数做自适应调整
- 已形成 `conceptual / scaffolded / targeted` 三层提示策略
- 已显式校验 `direct_answer_given=false`，用于约束“不直接泄露答案”
- 已在 Docker live smoke 中验证真实 hint 链路

说明：

- 现在的 hint 已经不是单纯换一种措辞，而是会根据教学上下文切换提示粒度

---

### 11. 基础学习记忆功能

已完成内容：

- 每轮消息交互后会写入 session memory event
- memory event 可关联 `session_id`
- memory event 可关联 `learner_profile_id`
- memory event 可关联来源 `message_id`
- 已写入摘要、标签、`progress_note`、`struggle_note`、`concept_focus`
- 已形成 `session/episodic` 与 `profile/semantic` 两层记忆写入
- 写入 memory event 时可同步生成 embedding
- 当前消息回复前会进行 session memory query embedding
- 当前消息回复前也会进行 profile memory query embedding
- 已能在同 session 内做相似度检索并把结果注入教学上下文
- 已能跨 session 聚合 learner profile 级记忆并注入 long-term context
- 已落地 knowledge memory / behavior memory 双实体
- 已落地独立检索 API、治理状态、运营干预接口与异步治理 / 压缩维护
- 正常对话后会基于 profile `MemoryEvent` 自动生成或刷新长期记忆 candidate
- 已在 Docker live smoke 中验证真实记忆链路

说明：

- 记忆系统已经不再只是规则化的一条 session note，而是具备最小的分层、双通道、自动候选沉淀和跨 session 组织能力

---

### 12. 长期记忆系统（治理增强版）

已完成内容：

- `knowledge_memories` / `behavior_memories` 已扩展治理字段
- `status` 已扩展为：
  - `candidate`
  - `active`
  - `stable`
  - `compressed`
  - `archived`
  - `suppressed`
- 长期记忆默认写入 `candidate`，默认检索只使用 `active / stable`
- 已新增 `LongTermMemoryMaterializationService`：
  - chat turn：从 profile-scoped `MemoryEvent` 自动生成或刷新 `KnowledgeMemory` / `BehaviorMemory` candidate
  - task outcome：仅处理 `completed / failed / skipped` 终态，写入 `task_attempt` evidence，必要时补建 candidate
  - reflection outcome：仅处理 `effective / ineffective` evaluation，写入 `reflection_outcome` evidence，必要时补建 candidate
- 已支持长期记忆 upsert / dedupe：
  - knowledge 按 `profile_id + goal_id/null + knowledge_key + semantic_category`
  - behavior 按 `profile_id + goal_id/null + behavior_key + behavior_category`
  - `candidate / active / stable` 会刷新证据与评分，`suppressed` 不会被自动恢复
- provenance 已明确区分：
  - `SessionMessage.id -> MemoryEvent.source_message_id`
  - `MemoryEvent.id -> long-term memory source_event_ids / provenance_source_id`
  - `TaskAttempt.id -> task_attempt evidence / provenance_source_id`
  - `ReflectionOutcomeEvaluation.id -> reflection_outcome evidence / provenance_source_id`
- embedding 记录已同步治理状态和治理分数字段
- 已新增：
  - `memory_evidence_links`
  - `memory_governance_decisions`
  - `memory_annotations`
  - `memory_conflict_sets`
  - `memory_conflict_members`
  - `memory_maintenance_jobs`
- 已集中长期记忆抽取与归一规则：
  - `MemoryNormalizer` 统一 topic key、semantic category、behavior category、evidence role
  - 结构化模型输出必须先通过 schema 校验和归一化，只能落为 `candidate`
- 已支持可解释 conflict set：
  - reason / handling / status impact 由应用层 policy 计算
  - member title / summary / status / validation status 通过 `memory_id` 实时读取，不在 member 表保存快照
- 已补长期记忆 Prometheus / Grafana / alert 基线：
  - candidate backlog
  - promotion rate
  - conflict rate
  - materialization failure rate
  - maintenance duration
- 已新增 memory 详情与治理接口：
  - `GET /api/v1/memory/knowledge/{id}`
  - `GET /api/v1/memory/behavior/{id}`
  - `GET /api/v1/memory/{type}/{id}/evidence-links`
  - `GET /api/v1/memory/{type}/{id}/governance-decisions`
  - `GET /api/v1/memory/{type}/{id}/annotations`
  - `GET /api/v1/memory/reflection-corpus`
  - `POST /api/v1/memory/{type}/{id}/suppress`
  - `POST /api/v1/memory/{type}/{id}/annotate`
  - `POST /api/v1/memory/{type}/{id}/restore`
- operator API 已支持 `X-Operator-Key` 鉴权
- worker 已通过独立 maintenance job 队列执行长期记忆治理刷新、压缩维护与 conflict refresh

当前限制：

- 自动沉淀只创建或刷新 `candidate`，不会直接晋升为 `active / stable`
- 证据提取仍以 memory event / task attempt / topic mastery / reflection outcome 的最小规则为主
- 动态阈值、精细化 topic 对齐、长期数据回归集仍需继续增强
- 当前测试覆盖的是“治理主链路最小正确性”，还不是长期生产回归级别

---

### 13. 第二阶段最小自主任务系统

已完成内容：

- `LearnerProfile` 创建、列表、详情接口
- `LearnerGoal` 创建、列表、详情、状态更新
- `StudyPlan` 生成、列表、详情
- `PlanStage` 持久化
- `DailyTask` 查询、执行、状态更新
- `WorkflowRun` 持久化与查询
- `GoalAutonomyState` / `LearnerAvailability` / `LearnerTopicMastery` / `TaskAttempt`
- `ScheduledAutonomyJob` 与 DB 驱动 worker 轮询入口
- autonomy control API：state / availability / mastery / pause / resume / manual replan
- `POST /sessions` 已兼容 `learner_profile_id` 与 `learner_goal_id`
- session 已可绑定 `learner_goal_id` 与 `daily_task_id`
- Planner 已形成 `规则骨架 + LLM 填充 + fallback` 结构
- 已支持 14 天任务窗口物化
- 已支持 task 执行时自动创建 session 并走现有 `chat/quiz` 链路
- 已支持 task `completed -> review scheduling`
- 已支持 task `failed/skipped -> immutable version replan`
- 已支持 assessment 任务调度
- 关键 plan/task/workflow 动作已补审计与 metrics
- 已补 learner workspace summary / filtered task list / long-term memory browse API，供 CLI/TUI 复用

说明：

- 这部分已经不再只是文档设计
- 当前属于“受控最小自主任务系统 + DB 驱动 worker 的最小自治层”
- 不是完整的后台长期自治运行体

---

### 14. 审计能力

已完成内容：

- assistant / user message 创建会写 audit
- quiz 生成会写 audit
- embedding retrieval 成功 / 失败会写 audit
- profile memory retrieval 失败也会单独写 audit
- LLM chat / hint 成功 / 失败会写 audit
- session 创建已写 audit
- session 状态更新已写单独 audit
- learner profile 创建失败会写 durable audit
- learner goal 创建 / 状态更新失败会写 durable audit
- memory event 写入已写单条 audit
- memory turn 级汇总 audit 仍保留
- workflow run 失败会走 durable audit，避免事务回滚吞掉失败事件
- daily task 幂等复用会写 audit
- daily task 状态更新失败会写 durable audit
- 数据层已有 `audit_events` 表

说明：

- 审计主链路已经覆盖到 session / message / memory / quiz / embedding / LLM / workflow / task / goal / profile 的关键动作
- 后续增强重点将转向更细粒度的运营分析事件，而不是补主业务失败审计缺口

---

### 15. 历史 CLI / TUI learner workspace baseline

已完成内容：

- 安装型 CLI 入口：`agent-edu`
- dual mode backend client：remote API / embedded ASGI
- `doctor` / `profile list` / `goal list` / `goal select`
- `task today` / `task execute` / `task status`
- `session resume`
- `memory search` / `memory browse`
- learner workspace summary API
- filtered task list API
- knowledge / behavior memory browse API
- learner-first TUI baseline（历史实现与参考资产）：左侧任务、中心 transcript、右侧长期记忆摘要
- 本地 active profile / goal / last session / last task context 持久化

说明：

- 这部分已经让系统具备“终端优先”的最小产品表面
- 当前仍是最小工作台，不是完整的终端学习操作系统
- UI 层仍严格复用 API contract，没有复制业务逻辑或直连数据库

---

### 16. 代码库基础设施优化（2026-06-14）

已完成内容：

- **repositories.py 大文件拆分（Task #7）**：
  - 将 4,268 行、44 个 Repository 类的单体文件拆分为 7 个领域模块：
    - `repositories/session.py` — SessionRepository / SessionMessageRepository / SessionQuizRepository
    - `repositories/skill.py` — SkillArtifactRepository / SkillUsageEventRepository / SkillCuratorRecommendationRepository
    - `repositories/audit.py` — AuditRepository
    - `repositories/learner.py` — LearnerProfileRepository / LearnerGoalRepository / GoalAutonomyStateRepository / ScheduledAutonomyJobRepository / LearnerAvailabilityRepository / LearnerTopicMasteryRepository / TaskAttemptRepository
    - `repositories/planning.py` — StudyPlanRepository / PlanStageRepository / DailyTaskRepository / WorkflowRunRepository
    - `repositories/memory.py` — 11 个记忆相关 Repository
    - `repositories/reflection.py` — 15 个反思相关 Repository
    - `repositories/__init__.py` — 统一导出层
  - 原 `repositories.py` 改为 65 行 re-export 层，保持完整向后兼容
  - 52 处现有调用方 import 路径无需任何修改

- **代码清理和文档化（Task #16）**：
  - 删除临时工具脚本 `.gemini/split_repositories.py`
  - 解决 `skills.py` 中两个硬编码 TODO：将 rollout observation 计数常量
    `STABLE_REQUIRED_PROMOTE_OBSERVATION_COUNT` 和 `REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN`
    迁入 `SkillLifecycleThresholds`，实现零散空殖常量的零剩留
  - 清晰化 `container.py` 中模糊的 `TODO: wire reflection service` 为精确架构注释
  - 更新 `ARCHITECTURE.md`：补充 Phase 2 repositories 拆分记录和 `infrastructure/db/repositories/` 子目录结构说明
  - 扩充 `test_repositories_split.py`：3 个测试用例 → 16 个
    （覆盖所有 7 个域模块的新旧路径、`__init__` 完整性 44 类验证、类身份一致性测试）
  - `packages/` 下零残留 TODO/FIXME

说明：

- 这是纯基础设施优化，不涉及功能变更
- 可维护性大幅提升：单文件可读性从 4,268 行降至平均 ~200-400 行/域模块
- 所有常量现均通过 `SkillLifecycleThresholds` 集中管理，消除了残留散点
- 已通过 AST 语法验证；运行时测试待 Docker 环境执行

---

### 17. 调度方法重构与服务拆分（Task #14）（2026-06-14，后续状态修正）

已完成内容：

- **TaskAutonomySchedulingService 中等与复杂方法迁移**：
  - 将 `AutonomousTaskService` (God Class) 中的 4 个中等和复杂自主调度核心方法移植至 `TaskAutonomySchedulingService`：
    - `materialize_today()` — 物化今日工作窗口
    - `manual_replan_goal()` — 手动重新规划
    - `run_periodic_goal_reflection()` — 定期反思
    - `run_due_autonomy_jobs()` — 运行到期任务
  - 引入了 `TriggerReflectionCallback` 和 `ProcessAutonomyJobCallback` 回调机制，将复杂调度逻辑从 `AutonomousTaskService` 中迁出，但仍通过 callback 与 legacy core 协调反思和作业执行。
  - `container.py` 已接入这些新服务与回调包装，但当前接线仍明确绑定到 `AutonomousTaskService._...` 私有协作逻辑。
  - 这一步完成的是“方法迁移”，不是“服务边界完全解耦”。

说明：

- 这是 Phase 3 中一次重要迁移，但不是收尾。
- `TaskAutonomySchedulingService` 已承接主要自治调度入口；与此同时，`AutonomousTaskService` 仍然存在，且并非纯委托空壳。
- 当前更准确的结论是：Task #14 在“方法迁移”层面已完成，在“架构解耦”层面仍未完成。

---

## 半完成

### 1. 测试体系与 Docker 验证

已完成部分：

- 已有 session、chat、message history、memory、quiz、health、schema 的基础测试
- 已有 DashScope-compatible LLM provider 测试
- 已有 embedding provider 测试
- 已补充 session audit、memory audit 与 durable failure audit 的单元测试
- 已补充数据库真实交互的 durable audit 回归测试
- 已补充更完整的 API 集成测试，覆盖 session / message / quiz / skills / readyz / metrics 与主要错误路径
- 已补充 Docker blackbox API 验证链路
- 已补充手动 gated 的 DashScope-compatible 真实 provider 长期回归测试，并已跑通一轮真实回归
- 已补充 Prometheus `/metrics` 暴露、Prometheus 抓取配置、长期记忆告警规则与 Grafana 预置面板
- 已有 live smoke test，且默认以环境变量显式开启
- `Makefile` 已提供 API 集成测试、Docker blackbox 测试、真实 provider 回归、Prometheus/Grafana 启动入口

未完成部分：

- 还缺少真实 provider 的定时化长期回归调度
- 还缺少告警通知、阈值调优与自动化观测闭环
- 还缺少更系统化的成本治理、限流与熔断策略

判断：

> 测试体系和 Docker 验证已经从“雏形”推进到“具备 API 集成、黑盒验证、真实 provider 回归、基础观测面板和长期记忆告警规则”，但仍未达到长期生产稳定运营。

---

## 部分完成

### 1. 第二阶段：自主任务系统

已完成内容：

- `LearnerProfile` 最小公开 API
- `LearnerGoal` 创建、读取、状态更新
- `StudyPlan` 生成、版本化、查询
- `DailyTask` 查询、执行、状态更新
- `WorkflowRun` 记录、查询
- `GoalAutonomyState` / `LearnerAvailability` / `LearnerTopicMastery` / `TaskAttempt`
- `ScheduledAutonomyJob` 与 DB 驱动 worker 轮询入口
- autonomy control API：state / availability / mastery / pause / resume / manual replan
- `POST /sessions` 已兼容 `learner_profile_id` 与 `learner_goal_id`
- session 已可绑定 `learner_goal_id` 与 `daily_task_id`
- Planner 已形成 `规则骨架 + LLM 填充 + fallback` 结构
- 已支持 14 天任务窗口物化
- 已支持 learner timezone 驱动的定时 daily task materialization
- 已支持 task 执行时自动创建 session 并走现有 `chat/quiz` 链路
- 已支持 task `completed -> review scheduling`
- 已支持更动态的 spaced review interval 调整
- 已支持 task `failed/skipped -> immutable version replan`
- 已支持 assessment 任务调度
- 已支持 milestone 阶段关卡与 gate release
- 已支持受控 external HTTP tool framework v1
- 关键 plan/task/workflow 动作已补审计与 metrics

说明：

- 数据模型、服务、API 和 worker 轮询入口已经落地
- 这部分已经不再只是文档设计
- 当前属于“受控自主任务系统 + DB 驱动 worker 的第一轮正式闭环”
- 还没有进入“长期自动运行的自治系统”阶段

仍未纳入本阶段的后续增强：

- 更完整的 TUI 任务导航、quiz/review 交互和 connector 扩展
- 非 HTTP 外部连接器与完整插件系统
- 更重的长期后台自治 runtime

---

### 2. 第三阶段：长期记忆系统

已落地内容见上文第 12 节“长期记忆系统（治理增强版）”，这里不重复展开。

仍需继续增强：

- 更细粒度的重要度与遗忘策略
- 更系统化的人工审核与修正治理
- 反思记忆与长期记忆的晋升闭环仍需继续增强，但 reflection outcome 已能桥接长期记忆 evidence / candidate
- 更完整的 reflection outcome replay/eval 体系
- 更完整的长期数据回归集：多轮学习、多 goal、多 topic、迁移升级
- proposal rollout 的更细粒度观测与运营面板
- 更完整的 review queue 运营面板与人工治理体验
- bundle / global rollout 与自动 promote / rollback

说明：

- 长期记忆系统不是未开始，而是已完成治理增强版的主链路，当前进入阈值、运营和回归收敛阶段

---

### 3. 第四阶段：反思系统

已落地内容：

- `ReflectionRecord / ReflectionAction`
- task failed / skipped 的 task-level reflection
- assessment completed 的 task-level / goal-level reflection
- workflow failed reflection
- replan completed 与连续失败模式触发的 goal-level reflection
- 规则优先 root cause 分类
- 低风险 follow-up action：
  - `replan`
  - `review_scheduling`
  - `assessment_generation`
- 高风险动作阻断并标记 `needs_review`
- 反思增强版新增：
  - `ReflectionEvidenceSignal`
  - `ReflectionOutcomeEvaluation`
  - `ReflectionReviewDecision`
  - `LearnerGoalStrategyCard`
  - `ReflectiveMemory`
  - session/task/workflow 的异步 evidence derivation
  - strategy card 对 chat/task 编排的最小影响
  - strategy card 对 planner blueprint 与 planning LLM context 的影响
  - review queue 聚合优先级：
    - `aggregation_key`
    - `duplicate_count`
    - `priority_score`
    - `cooldown_until`
  - outcome evaluation 自动回写：
    - strategy card
    - reflective memory
    - reflection priority/status
    - long-term memory evidence / candidate
  - proposal 闭环：
    - `ReflectionProposal`
    - `ReflectionProposalEvaluation`
    - proposal review queue
    - prompt / workflow proposal records
    - rule-based replay/eval
    - `ReflectionProposalSandboxRun`
    - archived replay sandbox worker path
    - `ReflectionProposalApprovalDecision`
    - operator approve / reject flow
    - proposal evaluation read API
    - low / medium risk proposal auto-admission to sandbox
  - rollout / rollback 闭环：
    - `ReflectionProposalRollout`
    - `ReflectionProposalRolloutObservation`
    - `ReflectionProposalRolloutDecision`
    - goal-scoped staged activation
    - `chat / hint / plan_generation / review_scheduling / assessment_generation / replan` rollout surfaces
    - rollout overlay 进入 chat / planner / task runtime
    - manual promote / rollback
    - planner rollback baseline replan
  - operator reflection governance：
    - `review`
    - `resolve`
    - `override-root-cause`
    - `override-action`
- 反思查询 API：
  - `GET /api/v1/goals/{goal_id}/reflections`
  - `GET /api/v1/tasks/{task_id}/reflections`
  - `GET /api/v1/reflections/{reflection_id}`
  - `GET /api/v1/reflections/review-queue`
  - `GET /api/v1/reflections/{reflection_id}/reviews`
  - `GET /api/v1/goals/{goal_id}/strategy-card`
  - `GET /api/v1/goals/{goal_id}/reflective-memories`
- 反思审计链路：
  - `reflection.record.created / completed`
  - `reflection.action.proposed / executed / blocked`
  - `llm.reflection.completed / failed`
  - `reflection.evidence.derived`
  - `reflection.outcome.evaluated`
  - `reflection.reviewed / resolved`
  - `reflection.root_cause.overridden / reflection.action.overridden`
  - `strategy.card.refreshed`
  - `reflective_memory.candidate.created`
  - `reflection.proposal.created`
  - `reflection.replay.completed`
  - `reflection.proposal.sandbox.queued / started / completed / failed`
  - `reflection.proposal.approved / rejected`

说明：

- 反思引擎本体已经独立成模块，并接入 task / workflow / autonomy 主链路
- 当前已进入 v2 增强阶段，但仍是“部分落地”
- 本轮已进一步补齐：
  - periodic goal reflection 的保守型 autonomy job 调度
  - worker 侧 reflection outcome evaluation sweep
  - outcome -> strategy / reflective memory / long-term memory bridge 的更完整自动回写
  - reflection outcome -> long-term memory 的 candidate 补建与 evidence upsert
  - prompt / workflow proposal v1 与 rollout / rollback v1
  - `skill_package` proposal 类型与最小 sandbox / rollout / artifact handoff
- 仍未完成：
  - reflection -> skill artifact 的自动化生产与长期治理闭环
  - 更完整的 replay/eval 治理闭环
  - 更丰富的 prompt / workflow optimization 输出
  - bundle / global rollout 治理
  - auto promote / auto rollback
  - 更细粒度的 session signal / hint signal 证据抽取

---

### 4. 第五阶段：Skill Evolution

当前状态：

> skill evolution 最小治理闭环已部分落地，但还不是完整动态技能系统。

已落地内容：

- proposal 层已支持 `skill_package` 和 `skill_patch_request` 类型，不再只有 `prompt_optimization` / `workflow_optimization`
- 反思服务可以从有效反思模式生成 single-surface `skill_package` proposal
- `skill_package` proposal 可以进入既有 sandbox / replay / evaluation / approval 路径
- `skill_patch_request` proposal 已作为 curator patch request 的 reference-only 承载：
  - 由 `patch_needed` recommendation 被 operator accept 后创建
  - payload 只引用 artifact、usage evidence、recommendation reason / metrics，不直接生成最终 artifact payload
  - 可以进入 sandbox / replay / evaluation / approval
  - 明确不可 rollout，也不能用于创建 skill candidate，避免绕过 `skill_package -> sandbox -> evaluation -> approval -> artifact lifecycle`
- approved / effective `skill_patch_request` 已可通过 operator-protected realization API 生成新的 replacement `skill_package` proposal：
  - realization 要求 source artifact 存在且 name / scope / version anchor 匹配
  - 新 proposal 复制 source artifact 的 match_rules / runtime_directives / tool_plan / scoring_contract
  - evidence_snapshot 记录 source patch request、source artifact、recommendation、usage 和 evaluation provenance
  - realization 不修改 active / stable artifact，也不直接创建 candidate
- 已引入 `SkillArtifact` 版本化技能资产：
  - `name / version / lineage_id`
  - `skill_type / scope / status`
  - `definition / runtime_directives / tool_plan`
  - `compatibility_contract`
  - `source_reflection_ids / source_memory_ids / source_proposal_id`
  - `quality_score`
- 已引入 `SkillUsageEvent` 使用记账：
  - artifact 归因
  - learner profile / goal / session / task / workflow 上下文
  - surface / topic / outcome / latency / cost
  - resolver status / selection reason / outcome signals
- 已引入 `SkillCuratorRecommendation` 治理建议承载层：
  - recommendation type 覆盖 promote / patch / merge / archive / rollback review / flag-for-review / restore
  - `recommended_action` 与 recommendation type 分离，accept 只调用已有 lifecycle service，不直接改 artifact 表
  - `evidence_snapshot / metrics_snapshot / action_result` 保留证据快照、指标快照与处理结果
  - pending duplicate 复用，accept / dismiss 幂等
  - operator-protected list / get / accept / dismiss API
  - audit 覆盖 recommendation created / reused / accepted / dismissed
- 已引入 `SkillCuratorJob` MVP：
  - application service 可被 worker tick 调用，默认启用且阈值可配置
  - 扫描 active / stable / deprecated artifact，不直接修改 artifact
  - active artifact 满足 rolled_out rollout、rolled_out binding、连续 promote observation、成功 usage 和负向比例阈值时，生成 `promote_candidate / stabilize_active`
  - active / stable artifact 出现负向 usage、blocked resolver、suppressed 或 incompatible 信号增多时，生成 `flag_for_review / none`
  - latest rollout observation 建议 rollback 且尚无后续 rollback decision 时，生成 `rollback_review / none`
  - deprecated artifact 长期无 attributed usage 时，生成 `archive_candidate / archive_deprecated`
  - memory conflict summary、reflection outcome evaluation 和 resolver health trend 已作为 `governance_evidence` 接入，可生成或增强 `flag_for_review / none`
  - 使用 deterministic `source_job_id` 做日窗口去重，已 accepted / dismissed / pending 的同窗口建议都会复用
  - recommendation 保留 evidence / metrics snapshot，并记录 job completed / recommendation reused audit
- artifact lifecycle 已覆盖：
  - `candidate -> staged`
  - `staged -> active`
  - `active -> stable`
  - active / stable selectable artifact replacement
  - active / stable -> suppressed
  - suppressed -> previous selectable status restore
  - active / stable / suppressed -> deprecated on rollout rollback
  - deprecated -> archived
- runtime resolver 已支持：
  - active/stable artifact 选择
  - suppressed artifact fail-closed blocking
  - incompatible compatibility contract blocking
  - missing artifact static fallback，且 deprecated / archived 不参与 fallback
- operator-protected API 已覆盖 artifact 创建、stage、activate、replace、stabilize、suppress、restore、deactivate、archive、usage 查询和 resolution probe
- operator-protected API 已覆盖 curator recommendation 查询与 accept / dismiss
- `archive_candidate / archive_deprecated` 被 operator accept 后，会通过 lifecycle service 执行 `deprecated -> archived`，失败时 recommendation 保持 pending
- `patch_needed / none` 被 operator accept 后，会通过 reflection proposal service 创建 `skill_patch_request` proposal；缺少 `learner_goal_id` / `reflection_record_id` anchor 或 proposal 创建失败时，recommendation 保持 pending
- approved / effective `skill_patch_request` 被 operator realization 后，会创建 replacement `skill_package` proposal；该 proposal 仍需自己通过 sandbox / evaluation / approval，之后可由 operator-protected staging API 复用既有 candidate / stage lifecycle 生成 `staged` replacement artifact
- `SkillCuratorJob` 已可扫描同 name/scope 或同 implementation binding 的 governed artifacts，比较 `match_rules.task_types/topic_keys` 交集，生成带 overlap evidence 的 `merge_candidate / none` recommendation；related artifact 允许 candidate / staged / active / stable / deprecated，拒绝 suppressed / archived / rejected
- `SkillCuratorJob` 已可按 artifact topic / rollout goal 聚合 memory conflict summary、reflection outcome evaluation 和 resolver health trend，写入 `governance_evidence`，并在高严重冲突或反思 outcome 退化时生成 `governance_evidence_regression` review recommendation
- `SkillCuratorJob` 已可按 artifact 声明 `topic_keys` 与实际 usage 的偏移检测 surface / topic coverage regression，并在声明外 topic demand 或 governed binding gap 持续出现时生成带 coverage evidence 的 `patch_needed / none` recommendation
- skill observability 已补 Prometheus / Grafana / alert 基线，覆盖 skill usage、resolver failure、artifact status、curator pending backlog、recommendation rate 与 curator job p95
- `merge_candidate / none` 被 operator accept 后，会通过 reflection proposal service 创建 merge-sourced replacement `skill_package` proposal；source artifact 必须是 active / stable，related artifact 可以引用 governed candidate / staged / active / stable / deprecated artifact，但拒绝 suppressed / archived / rejected
- chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan 已接入 skill resolution 与 usage 记录
- staged governed replacement 的 readiness read API 现会直接返回 `recommended_action`（`replace_selectable / activate_staged / null`），不再要求 operator 仅凭双 readiness 状态自行推断下一步动作
- staged governed replacement 的 direct `activate_staged` 路径已与 replace 一样走加锁 artifact 读取；operator accept recommendation 仍先执行 lifecycle，再标记 recommendation accepted
- staged replacement lifecycle 执行失败时，系统会写 `skill.curator.recommendation.accept_failed` durable audit，且 recommendation 保持 `pending`

仍未完成：

- runtime 已能在 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 上消费 governed `SkillExecutionPlan`，并把 `implementation_binding / execution_kind / binding metadata` 写入 usage；但 active artifact 还没有成为完整动态技能注册源
- `tool_plan` 已从最小 runtime compatibility gate 升级为 internal-only 的受控 runtime executor，并在 sandbox preview 与 autonomy runtime 上复用同一套 payload-template 解析与 fail-closed 约束；当前支持最多 2 步的 linear chain、显式 `step_id` 和 prior-step output 引用（如 `$steps.repair.created_task_ids[0]`），且已把 `partial_replan -> review_scheduling` 作为保守白名单序列落到 `replan` 主 surface；其 usage metadata、step 级 audit 和 sandbox summary 已能反映 sequence / step count / step summary，但通用多步 tool-plan orchestration interpreter 仍未实现
- `SkillCuratorJob` 仍是 MVP：已消费 usage / rollout observation / rollout decision、artifact overlap / duplicate detection、memory conflict summary、reflection outcome evaluation、resolver health trend、surface / topic coverage regression 和 staged replacement readiness；生产级 dashboard / alert 基线已落地，但自动执行和更重的运维编排仍未完成
- patch / merge 的长期治理闭环仍是保守人工执行形态；当前已完成 `patch_needed -> skill_patch_request -> replacement skill_package proposal -> staged replacement -> readiness -> operator activate/replace` 和 `artifact overlap -> merge_candidate -> merge-sourced replacement skill_package proposal -> staged replacement -> readiness -> operator activate/replace`，但没有自动 activate / replace
- bundle / global rollout 治理尚未实现
- auto promote / auto rollback 尚未实现
- skill artifact 与 runtime behavior 的绑定仍偏保守，当前主要通过静态 implementation binding、runtime directives、goal binding 和 resolver gate 生效

说明：

- 当前已经不能再描述为“未开始”
- 更准确的状态是：`memory -> reflection -> skill_package proposal -> sandbox/evaluation/approval -> rollout/binding -> SkillArtifact -> usage` 已形成最小受控链路
- `usage -> SkillCuratorJob -> curator recommendation` 的保守 MVP 已打通，recommendation 存储、operator review API、audit 和 lifecycle action handoff 已落地
- `recommendation -> patch request / merge-sourced replacement proposal -> staged replacement -> readiness -> operator activate/replace` 的最小安全路径已对 `patch_needed` 和 `merge_candidate` 打通，artifact overlap / duplicate detection 已可生成 merge 输入；dynamic runtime V1 与 tool-plan orchestration V2/V3 已覆盖主要 autonomy surfaces，并对 `replan` 落地了受控 multi-step 样板，但更深的 runtime orchestration 与长期治理仍未完成，因此不能视为完整 Skill Evolution

---

### 5. 第六阶段：多 Agent 协作

未开始内容：

- 多角色 agent 分工
- planner / tutor / memory / reflection / safety 的协作机制
- agent society 治理机制

说明：

- 当前系统仍是单体后端服务形态

---

### 6. 生产化教学治理

未开始内容：

- 成本治理
- 限流与熔断策略
- 更完整的质量评估基线

说明：

- 真实模型已经能接入
- Prometheus/Grafana 基础观测已经补齐，长期记忆告警规则基线也已落地
- 但离可长期稳定生产运行还有一段距离

---

## 按第一阶段验收标准的判断

### 已基本具备

- 用户可以创建学习会话
- 用户可以在 session 下持续发消息
- 系统可以输出结构化解释
- 系统可以生成练习题
- 系统可以在需要时只给提示而不直接给答案
- 系统可以把 session memory 作为检索上下文回注到回复链路

---

### 尚未完全达到

- 教学回复的真实质量与稳定性
- 基于更丰富 learner state 的连续教学
- 基础记忆已进入长期治理增强阶段，但质量抽取、阈值策略和生产回归仍需继续增强
- 可证明稳定可用的第一阶段闭环
- 真实 provider 回归的定时化与长期趋势监控

---

## 当前最准确的结论

如果只用一句话概括当前进度：

> 项目已经完成第一阶段大部分核心教学能力，并落地了第二阶段最小自主任务系统 + worker baseline，代码库架构重构进度已达 84%；但离“稳定可用的教学 Agent + 长期自动运行的任务系统”还差定时调度、长期治理和更强状态管理。

如果用阶段语言概括：

- 不是“仅有愿景”的空仓库
- 也不是“第一阶段已完全验收”的可交付产品
- 更接近“Phase 1 核心链路已完成，Phase 2.1 最小闭环已落地，架构重构进度 84%，正在做稳定化与生产化收敛”

---

## 后续最优先事项

建议下一步优先补齐：

1. 给概念讲解和 hint 增加更稳定的质量回归样本
2. 增加真实 provider 回归的定时化执行与结果留档
3. 增加真实 API 的成本治理、限流与熔断策略
4. 在现有 Prometheus/Grafana/alert 规则基础上补通知、阈值调优与持续观测闭环
5. 补齐定时调度与长期任务推进机制
6. 在保持当前结构稳定的前提下，继续增强长期记忆治理、审核面板与回归数据集

当这几项完成后，项目才能更接近 `docs/IMPLEMENTATION_PLAN.md` 中定义的第一阶段验收标准。
