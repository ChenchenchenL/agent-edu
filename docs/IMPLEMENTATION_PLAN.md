# IMPLEMENTATION_PLAN.md

## 文档定位

这份文档用于说明 `agent-edu` 接下来要优先实现哪些功能、每项功能解决什么问题、实施顺序如何安排，以及每个阶段做到什么程度才算完成。

它不是架构文档，也不是代码规范，而是面向项目 owner 的功能推进计划。

---

## 一、项目当前所处阶段

当前项目已经完成了第一轮后端工程骨架搭建，具备：

- API 服务基础结构
- PostgreSQL / Redis 接入骨架
- Session / Message / MemoryEvent / AuditEvent 基础模型
- 可切换的 mock / 真实 LLM provider
- DashScope-compatible 聊天接口接入
- embedding provider 与 session memory retrieval 最小链路
- 最小路由与迁移骨架

这意味着：

- 工程底座已经开始成形
- “用户可感知的教育功能”已经开始进入真实链路联调
- 接下来工作的重点应从“搭骨架”切换到“做稳定闭环与质量治理”

当前阶段的核心任务不是继续堆基础设施，而是尽快做出：

> 一个能真正完成基础教学任务的稳定教学 Agent。

补充说明：

- 当前已经不再只是 mock 骨架
- 教学对话、hint、quiz 已可走真实模型调用
- session memory 已可写入 embedding 并在回复前做 retrieval
- 现在的主要问题从“链路有没有”转为“效果稳不稳定、能不能治理”
- 默认验证环境为 Docker compose，后续 smoke test 也应以它为基线
- 工程组织方式参考 Hermes 的 unified core / skills / session / curator 思路，但 learner model、mastery、curriculum、reflection、pedagogical safety 由本项目自研
- 详细映射见 [docs/hermes-to-edu-mapping.md](./hermes-to-edu-mapping.md)
- 当前交互表面优先走 CLI / TUI，设计说明见 [docs/CLI_TUI_DESIGN.md](./CLI_TUI_DESIGN.md)

---

## 二、功能实施总目标

功能实施的第一阶段目标是：

> 让用户能够围绕一个学习主题，完成一次完整的“提问 -> 讲解 -> 练习 -> 记录 -> 继续学习”的基础闭环。

围绕这个目标，项目功能实施分为四层：

1. 教学交互功能
2. 学习诊断与练习功能
3. 基础记忆与学习连续性功能
4. 学习规划与后续演化预留功能

当前优先级最高的是前 3 层，第 4 层先做接口和扩展位，不做完整能力。

---

## 三、第一阶段必须完成的核心功能

### 1. 学习会话功能

功能目标：

- 让每一次学习过程有明确的会话上下文
- 为后续对话、练习、记忆、学习计划提供统一载体

功能内容：

- 创建学习会话
- 查看单个学习会话
- 记录会话主题
- 记录会话状态

用户价值：

- 用户不是在和一个“无状态聊天框”交流，而是在进入一个具体学习任务
- 后续所有学习记录都可以围绕 session 持续累积

完成标准：

- 可以创建一个新的学习会话
- 可以读取已有学习会话
- 后续消息、练习、记忆都能绑定到 session

---

### 2. 教学对话功能

功能目标：

- 让用户可以围绕某个主题持续提问并获得教学型回答

功能内容：

- 用户提交问题
- 系统返回结构化教学回复
- 回复内容区分普通聊天与教学型解释
- 记录本轮使用的 skill trace

用户价值：

- 用户能真正开始使用系统学习
- 系统从第一天开始形成“教学而不是闲聊”的产品特征

完成标准：

- 用户发送消息后，系统能生成稳定回复
- 回复不是随机闲聊，而是围绕学习主题组织解释
- 每轮消息都能落库保存
- 后续可继续接着该 session 学习

---

### 3. 概念讲解功能

功能目标：

- 让系统具备“解释一个概念”的最基础教学能力

功能内容：

- 输入一个知识点或问题
- 输出结构化解释
- 支持简要定义、核心原理、例子、常见误区等基础讲解结构

用户价值：

- 用户能把系统当作一个可持续提问的教学助手
- 项目能形成最直观的“教育产品感”

完成标准：

- 对同类问题输出风格稳定
- 回复内容以“讲清楚”为目标，而不是只给结论
- skill registry 中 `explain_concept` 能真实参与链路

---

### 4. 练习题生成功能

功能目标：

- 让系统具备“讲完就练”的基本教学节奏

功能内容：

- 根据 topic 生成 quiz
- 支持难度和题量控制
- 返回结构化题目与参考答案

用户价值：

- 用户不仅能看解释，还能立刻练习
- 系统开始具备教学闭环，而不只是回答问题

完成标准：

- 可以基于指定主题生成题目
- 返回结构统一
- 每次生成都可追踪来源 session 或 topic
- skill registry 中 `create_quiz` 能真实参与链路

---

### 5. 自适应提示功能

功能目标：

- 让系统不是只会“直接说答案”，而是能逐步引导学习者

功能内容：

- 用户请求提示时，系统返回 hint 而不是完整解答
- hint 强调下一步思路、关键概念、纠错方向

用户价值：

- 更符合教学场景
- 为后续苏格拉底式对话和分层教学打基础

完成标准：

- 至少存在一条 `hint` 模式链路
- `adaptive_hint` 可在 skill trace 中体现
- 提示内容明显区别于完整讲解

---

### 6. 基础学习记忆功能

功能目标：

- 让系统能够记住当前用户在这个 session 里学了什么、卡在哪里

功能内容：

- 为每轮对话写入 session memory event
- 记录摘要、标签、来源消息
- 记录用户正在学习的主题和局部困难点
- 在条件允许时为 memory event 生成 embedding
- 在后续回复前检索同 session 的相关记忆
- 检索结果和 provider 响应元数据应进入 audit，方便 Docker 场景排查
- 当前已经补齐 knowledge / behavior 双通道长期记忆 v1；session 级事件记忆仍是底层输入
- 当前已经进入长期记忆治理增强阶段：在 knowledge / behavior 双通道之上增加状态治理、动态强化/衰减、证据链、运营标注、反思语料导出、告警基线与 worker 维护闭环
- 当前已经接入长期记忆自动沉淀：正常对话后的 profile `MemoryEvent` 会生成或刷新 `KnowledgeMemory` / `BehaviorMemory` candidate
- 自动沉淀使用 upsert / dedupe，不会在同一语义身份下每轮重复插入 candidate；被 `suppressed` 的记忆不会被自动恢复
- `MemoryNormalizer` 已集中 topic key、semantic category、behavior category、evidence role 归一规则
- 结构化抽取结果必须先经过 schema 验证和归一化，且只允许落为 `candidate`
- `memory_conflict_sets` / `memory_conflict_members` 已提供可解释冲突输出，成员详情通过 `memory_id` 实时关联，不再存快照
- `memory_maintenance_jobs` 已拆分为独立维护队列，支持 bounded batch、lease 恢复、retry/backoff 与 durable audit
- 长期记忆观测已补 candidate backlog、promotion rate、conflict rate、materialization failure rate、maintenance duration，并提供 Prometheus/Grafana/alert 基线

用户价值：

- 用户能获得连续性的学习体验
- 后续回复可以基于上下文而不是每次从零开始

完成标准：

- 每轮关键交互都能产生 memory event
- memory event 能关联到 session 和 message
- 记忆内容以会话级事件记忆为主，但已经进入长期记忆治理增强版的最小落地阶段
- 检索结果能够作为教学上下文进入回复链路
- 长期记忆默认以 `candidate` 落库，而不是未经治理直接成为高权重上下文
- 长期记忆支持 `active / stable / compressed / archived / suppressed` 的治理语义
- 长期记忆维护周期会同步调整 `importance / confidence / freshness / stability`，并写回证据链
- 长期记忆维护还包括 profile 级 conflict refresh、压缩维护和观测告警
- 已提供面向反思 Agent 的 `reflection-corpus` 结构化导出接口
- 运营侧至少能做 suppress / annotate / restore 三类人工干预
- provenance 可追踪 `SessionMessage -> MemoryEvent -> long-term memory`，且 `session_event` 来源 ID 指向 `MemoryEvent.id`

---

### 7. 学习轨迹与审计功能

功能目标：

- 让系统的关键行为可追踪、可解释、可排查

功能内容：

- 记录 session 创建
- 记录 message 创建
- 记录 quiz 生成
- 记录 memory event 写入
- 为后续高风险功能预留 audit 机制

用户价值：

- 当前对用户是间接价值，但对后续可控性、排错和产品质量至关重要

完成标准：

- 关键链路都有 audit 记录
- 可以回看一次学习动作是如何发生的
- 后续接真实模型时具备基本安全治理基础
- Docker 环境下可以直接通过 audit 事件回放问题

---

## 四、第一阶段功能实施顺序

为了尽快形成可用产品闭环，建议严格按照下面顺序实施：

### 第一步：学习会话功能

原因：

- 没有 session，就没有上下文承载，后续所有功能都失去组织结构

交付结果：

- 用户能创建和读取学习会话

---

### 第二步：教学对话功能

原因：

- 这是用户第一次真正感知系统价值的入口

交付结果：

- 用户可以围绕会话主题发消息并获得教学型回复

---

### 第三步：概念讲解功能

原因：

- 教育产品首先必须把“讲明白”做好

交付结果：

- 系统能稳定完成概念解释，而不是泛泛回答

---

### 第四步：练习题生成功能

原因：

- 只有讲解没有练习，学习闭环不成立

交付结果：

- 用户可以让系统围绕主题出题并练习

---

### 第五步：自适应提示功能

原因：

- 这是从“回答工具”向“教学工具”迈出的关键一步

交付结果：

- 系统能在不直接给答案的情况下引导用户继续思考

---

### 第六步：基础学习记忆功能

原因：

- 连续学习体验必须依赖上下文累积

交付结果：

- 系统记住 session 内的主题、消息和局部困难点

---

### 第七步：学习轨迹与审计功能

原因：

- 为后续真实模型接入、错误排查和安全治理做准备

交付结果：

- 关键学习动作可追踪

---

## 五、功能依赖关系

功能之间不是并列关系，而是存在明显依赖：

- 学习会话功能
  是所有功能的基础

- 教学对话功能
  依赖 session 存在

- 概念讲解功能
  依赖教学对话链路稳定

- 练习题生成功能
  可独立存在，但最好与 session / topic 绑定

- 自适应提示功能
  依赖已有讲解逻辑和题目/问题上下文

- 基础学习记忆功能
  依赖 session 和 message 都已稳定落库

- 学习轨迹与审计功能
  贯穿所有功能，应随核心链路同步补齐

因此，不建议并行无序推进，否则会出现：

- 数据结构先铺太多但没有真实功能使用
- 功能看似很多但链路不闭环
- 测试和验收无法形成稳定基线

---

## 六、第一阶段功能验收标准

当下面这些能力全部成立时，可以认为项目完成了第一阶段的第一轮功能落地：

### 教学闭环验收

- 用户可以创建一个学习会话
- 用户可以围绕一个主题连续提问
- 系统可以输出教学型解释
- 系统可以生成练习题
- 系统可以在需要时只给提示而不直接给答案

### 连续性验收

- 同一个 session 中的消息可以持续累积
- 系统能记录会话级学习事件
- 后续回复能基于已有 session 上下文继续进行
- 后续回复能基于检索到的 session memory 继续进行
- Docker compose 环境下可重复跑通同一条教学链路

### 可治理性验收

- 关键动作都有 audit
- 所有输入都经过校验
- mock provider 输出不会直接触发高风险副作用
- 真实 provider 调用具备基础超时、错误处理与配置校验
- 真实 API 在 Docker 环境下有 smoke test 和可见运行指标

### 工程可持续性验收

- API 结构稳定
- 数据表与功能链路匹配
- 可以在不推翻现有结构的前提下继续进入下一阶段

---

## 七、第二阶段计划功能

当第一阶段稳定后，再进入第二阶段功能实施。

第二阶段不再只是“回答与出题”，而是进入：

> 学习任务组织能力。

第二阶段计划功能：

- 学习目标创建
- 学习路径规划
- 每日学习任务生成
- 自动复习安排
- 基础 workflow orchestration

当前代码已完成的第二阶段正式收尾能力：

- `LearnerProfile` 最小公开 API
- `LearnerGoal` 创建、读取、状态更新
- `StudyPlan` 生成、版本化、查询
- `DailyTask` 查询、执行、状态更新
- `WorkflowRun` 记录、查询
- `GoalAutonomyState` / `LearnerAvailability` / `LearnerTopicMastery` / `TaskAttempt`
- `ScheduledAutonomyJob` 与 DB 驱动 worker 轮询入口
- autonomy control API：state / availability / mastery / pause / resume / manual replan
- learner timezone 驱动的定时 daily task materialization
- 14 天滚动任务物化窗口
- `completed -> review scheduling`
- 更动态的 spaced review interval 调整
- `failed/skipped -> full replan`
- `assessment` 任务调度
- `milestone` 阶段关卡与 gate release
- 受控 external HTTP tool framework v1
- task 执行时自动创建绑定 goal/task 的 session

当前第二阶段刻意未包含的后续增强：

- 更完整的 TUI 任务导航、quiz/review 交互与 connector 扩展
- 完整插件系统与非 HTTP 外部工具连接器
- 更重的长期后台自治 runtime / scheduler

这一阶段的核心变化是：

- 系统从“响应式教学”转向“带有主动组织能力的教学”
- 同时开始从“纯 API 后端”转向“CLI-first 的学习工作台”

但前提仍然成立：

- 当前已落地的是“受控自主任务系统 + DB 驱动 worker 的正式第一轮闭环”
- 仍不是完整的长期后台自治体
- 第一阶段稳定化和生产治理仍然会直接影响第二阶段体验

---

## 八、第三阶段计划功能

第三阶段进入长期记忆功能建设。

计划功能：

- Episodic memory
- Semantic memory
- Knowledge memory
- Behavior memory
- 用户学习画像
- 记忆压缩
- 记忆检索与教学调用

已落地的最小能力：

- knowledge / behavior 双实体
- 独立检索 API
- importance / confidence / freshness / time horizon 元数据
- 异步压缩与聚类
- session memory 仍作为事件输入层
- chat / task outcome / reflection outcome 到长期记忆 candidate 的自动沉淀
- stable identity upsert / dedupe，避免重复长期记忆候选
- provenance 链路区分 message、memory event、task attempt、reflection outcome 来源
- topic 对齐增强与更细粒度 evidence extraction
- governance summary 输出增强
- maintenance 周期中的动态治理乘子
- `memory_maintenance_jobs` 独立队列、lease 恢复、retry/backoff、durable audit
- `MemoryNormalizer` 集中 topic/category/evidence role 规则，结构化抽取只允许校验后进入 candidate
- 冲突解释通过 policy + 实时 memory 关联输出，避免成员快照冗余

补充：

- 当前已新增 workspace summary / filtered task list / memory browse API
- 当前已新增 `agent-edu` CLI 与 learner-first TUI baseline
- terminal surface 仍严格复用 API contract，而不是复制业务逻辑

这一阶段的目标不是简单“存更多数据”，而是：

> 让系统真正形成连续学习关系。

---

## 九、第四阶段以后功能方向

在前面能力稳定后，再逐步进入：

- Reflection system 增强版
- Teaching strategy optimization
- Workflow optimization
- Skill proposal
- Skill sandbox evaluation
- Multi-agent collaboration

其中当前已完成的最小反思能力包括：

- `ReflectionRecord / ReflectionAction`
- task / goal reflection 事件驱动触发
- workflow failure reflection
- 规则优先 root cause 分类
- 低风险 follow-up action 执行
- 反思查询 API 与审计链路
- review queue 聚合优先级主链
- outcome evaluation 自动回写 strategy / reflective memory
- outcome evaluation 可桥接长期记忆 evidence，必要时补建 candidate，但不绕过长期记忆治理晋升
- strategy card 深接 planner blueprint 与 planning LLM context
- periodic goal reflection 最小入口
- prompt / workflow optimization proposal records
- rule-based replay/eval for proposal validation
- proposal sandbox / approval v1
  - DB-backed sandbox run records
  - worker-driven archived replay evaluation
  - operator approval / rejection decisions
  - proposal evaluation read API
  - low / medium risk proposal auto-admission to sandbox
- proposal rollout / rollback v1
  - goal-scoped staged activation
  - chat / hint / plan_generation / review_scheduling / assessment_generation / replan rollout surfaces
  - rollout overlay consumption in chat / planner / task runtime
  - rollout observation records and recommendations
  - manual promote / rollback
  - planner rollback baseline replan

仍未完成的反思增强项包括：

- evidence signal / outcome / strategy / reflective memory 的更完整评估闭环
- 更丰富的 prompt / workflow optimization 输出
- bundle / global rollout 治理
- auto promote / auto rollback
- 更重的周期化 goal reflection 调度形态
- 与 skill proposal / sandbox 的闭环

这些增强能力仍然不应在当前阶段一次性铺开。

---

## 十、当前最重要的实施结论

接下来项目开发的重点，不应该再是继续讨论系统愿景，也不应该先做复杂自治能力，而应该聚焦：

> 先把“会话 + 教学对话 + 概念讲解 + 练习题 + 提示 + 基础记忆 + memory retrieval”这一条学习主链路做成稳定可用产品功能。

只有这条链路完成，项目才真正从：

> 工程初始化阶段

进入：

> 教育智能体功能建设阶段

---

## 十一、当前落地后的下一步优先级

基于当前代码状态，建议下一步按下面顺序推进：

1. 让概念讲解与 hint 输出形成更稳定的质量回归样本
2. 把真实 provider 回归从手动 gated 推进到可定时执行与可留档
3. 在已有 Prometheus/Grafana/alert 基线基础上补告警通知、成本治理、限流与熔断
4. 给第二阶段 Planner / task execution / review scheduling 增加更完整的 API 与回归测试
5. 补齐定时调度与每日任务自动推进策略，并评估是否需要引入更重的外部编排引擎
6. 在保持当前结构稳定的前提下，继续增强长期记忆治理与晋升策略

当前长期记忆组织的前提已经变化：

- 双通道长期记忆 v1 已落地
- 目前重点转向更细粒度的重要度、衰减、晋升与治理策略，以及长期回归数据集、运营观测和告警通知

---

## 十二、Docker 验证路径

建议默认用下面路径验证：

1. `docker compose up --build`
2. 等待 `postgres`、`redis`、`api` 都健康
3. `make test-api`
4. `make docker-api-test`
5. 在具备真实 provider 配置时执行 `make real-provider-regression`
6. 用 Grafana 与 `audit_events` 回看 latency、retry、response shape

后续所有真实模型联调都应优先走这条路径。

代理、真实 provider 回归、Prometheus / Grafana 与排障顺序细节见 [DOCKER_VALIDATION.md](./DOCKER_VALIDATION.md)。
