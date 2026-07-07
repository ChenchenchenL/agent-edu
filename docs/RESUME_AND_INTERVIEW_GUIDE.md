# Agent-Edu 简历与面试表述指南

## 文档定位

本文用于把 `agent-edu` 项目整理成可放入简历、作品集和面试叙述的材料。

核心原则：

- 按“教育智能体原型系统 / 学习平台项目”表述，不包装成已上线生产系统。
- 突出架构设计、后端工程、Agent 治理、长期记忆、学习任务闭环。
- 对未完成或计划中的能力明确说成“后续增强方向”，例如用户资料上传、知识图谱、完整生产级运维。
- 面试回答要能落到具体模块、数据流、接口、测试和工程取舍。

---

## 一句话项目介绍

推荐版本：

> Agent-Edu 是一个面向个性化学习场景的教育智能体原型系统，基于 FastAPI、React、PostgreSQL、Redis 和 LLM Provider 构建，支持学习目标管理、教学会话、练习生成、提示辅导、学习任务规划、长期记忆沉淀和受控治理审计。

更偏后端版本：

> Agent-Edu 是一个教育智能体后端与 Web 工作台项目，重点实现从学习目标到学习计划、每日任务、教学会话、Quiz/Hint、长期记忆和治理审计的核心闭环。

更偏 Agent 方向版本：

> Agent-Edu 聚焦教育智能体的长期学习陪伴能力，通过学习目标分解、记忆沉淀、反思评估和受控技能演化，验证 Agent 在个性化学习场景中的可追踪、可治理执行路径。

---

## 简历项目名称

可选标题：

- `Agent-Edu 教育智能体学习平台`
- `面向个性化学习的教育智能体系统`
- `基于长期记忆与任务规划的教育 Agent 系统`
- `可治理教育智能体原型系统`

推荐使用：

> Agent-Edu 教育智能体学习平台

这个标题比较稳，既能体现方向，也不会显得过度学术或过度产品化。

---

## 简历技术栈写法

```text
技术栈：FastAPI、React、TypeScript、PostgreSQL、Redis、SQLAlchemy、Alembic、TanStack Query、Docker Compose、pytest、Prometheus、Grafana、LLM Provider
```

如果简历空间有限：

```text
技术栈：FastAPI + React + PostgreSQL + Redis + Docker + pytest + LLM Provider
```

如果投后端岗位：

```text
技术栈：FastAPI、SQLAlchemy、PostgreSQL、Redis、Alembic、pytest、Docker Compose、Prometheus/Grafana、LLM Provider
```

如果投前端/全栈岗位：

```text
技术栈：React、TypeScript、TanStack Query、TailwindCSS、FastAPI、PostgreSQL、Docker Compose
```

---

## 简历项目描述

### 标准版本

```text
Agent-Edu 教育智能体学习平台
基于 FastAPI + React + PostgreSQL + Redis 构建面向个性化学习的教育智能体原型系统，支持学习目标管理、教学会话、Quiz 生成、Hint 辅导、学习任务规划、长期记忆沉淀和治理审计。
- 设计 LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun 学习任务闭环，实现根据学习目标生成阶段计划、每日任务，并将任务执行接入学习会话。
- 实现教学会话主链路，支持结构化概念讲解、练习题生成、提示辅导和消息历史读取，并保留 skill trace 便于追踪教学行为。
- 构建 session memory 与 long-term memory candidate 机制，将对话、任务结果和反思结果沉淀为可治理的学习记忆，支持 provenance 与候选晋升路径。
- 引入 proposal -> sandbox -> evaluation -> approval 的受控治理链路，约束反思、技能变更和运行时策略调整，避免 Agent 直接修改生产行为。
- 搭建 operator 控制台与可观测基础，支持 audit、memory、reflection、skill、quiz attempt 等视图，并使用 pytest、Docker Compose、Prometheus/Grafana 做本地验证和运行观测。
```

### 后端岗位版本

```text
Agent-Edu 教育智能体学习平台
基于 FastAPI + PostgreSQL + Redis 构建教育智能体后端，围绕学习目标、教学会话、任务调度、长期记忆和治理审计实现核心业务闭环。
- 按 Application / Domain / Infrastructure 分层组织服务、实体、仓储和外部 Provider，降低路由、业务逻辑、存储实现之间的耦合。
- 设计学习任务生命周期：LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun，支持计划生成、任务物化、任务执行、会话承接和状态追踪。
- 实现长期记忆候选机制，支持从 chat、task outcome、reflection outcome 中生成 memory candidate，并通过治理状态控制晋升、压制和审计。
- 为反思和技能演化设计 proposal -> sandbox -> evaluation -> approval 流程，避免模型输出直接触发高风险写入或运行时变更。
- 使用 Alembic 管理数据库迁移，使用 pytest 覆盖 session、goal、quiz、memory、reflection、worker、audit 等关键路径。
```

### 全栈岗位版本

```text
Agent-Edu 教育智能体学习平台
基于 FastAPI + React + PostgreSQL 构建教育智能体 Web 工作台，覆盖学习者侧目标/会话/任务流程和 operator 侧治理审计流程。
- 实现学习者侧页面，包括学习目标、会话列表、学习工作台、Quiz、Hint、任务面板等核心交互。
- 使用 TanStack Query 管理服务端状态，封装 session、goal、task、quiz、operator 等 API hooks，处理加载、错误和 mutation 状态。
- 后端实现学习目标、学习计划、每日任务、工作流执行、消息历史、长期记忆和治理审计等模块。
- operator 控制台支持 guardrails、review queue、curator recommendation、audit event、quiz attempt、learning gain 等治理与观测视图。
- 使用 Docker Compose 组织 API、PostgreSQL、Redis 等本地环境，并通过 pytest / 前端测试验证关键交互。
```

### Agent / AIGC 岗位版本

```text
Agent-Edu 教育智能体学习平台
面向教育场景设计长期学习 Agent，重点实现学习目标分解、教学技能调用、长期记忆沉淀、反思评估和受控技能演化。
- 将教学能力拆分为 explain_concept、create_quiz、adaptive_hint、plan_study_path、schedule_review 等技能，并在会话和任务执行中记录 skill trace。
- 引入 session memory 与 long-term memory candidate，将用户对话、学习任务结果和反思结果转化为可追溯学习记忆。
- 设计受控演化路径 proposal -> sandbox -> evaluation -> approval，避免模型反思直接影响生产策略或技能行为。
- 结合 audit、provenance、operator review 和 fail-closed 策略，提高 Agent 行为的可解释性和可治理性。
- 预留用户资料上传与知识图谱增强方向，用于后续将资料概念、前置关系和学习掌握度接入个性化教学路径。
```

---

## 后续增强方向的简历写法

如果后续确实实现“用户上传资料 + 知识图谱”，可以追加：

```text
- 设计资料知识结构化模块，支持用户上传学习资料后进行文本切分、概念抽取、前置关系识别和知识图谱构建。
- 将知识图谱节点与学习目标、Quiz、Hint、掌握度关联，用于生成个性化学习路径和薄弱知识点复习任务。
```

如果还没有实现，不要写进已完成项目条目。可以在面试中说：

> 当前项目已完成学习目标、教学会话、任务规划、长期记忆和治理审计主链路。资料上传与知识图谱是下一阶段计划，目标是把用户资料中的概念和前置关系接入学习路径生成与 Quiz/Hint。

---

## 面试自我介绍中的项目讲法

### 30 秒版本

> 我做过一个教育智能体项目 Agent-Edu，核心目标是把普通问答式 AI 做成能围绕学习目标持续工作的学习助手。系统用 FastAPI、React、PostgreSQL、Redis 实现，已经支持学习目标、学习计划、每日任务、教学会话、Quiz、Hint、长期记忆和 operator 审计。项目里我重点做了学习任务闭环、长期记忆候选机制，以及 Agent 反思和技能演化的治理路径，避免模型输出直接修改生产行为。

### 1 分钟版本

> Agent-Edu 是一个教育智能体原型系统。我没有把它做成简单聊天机器人，而是围绕学习过程建模：用户先创建学习目标，系统生成学习计划和每日任务，任务执行时进入教学会话，过程中可以生成解释、练习和提示。会话、任务结果和反思结果会进入长期记忆候选，再通过治理状态控制是否晋升为更高信任的学习记忆。另外，系统对 Agent 的反思和技能变更做了 proposal、sandbox、evaluation、approval 流程，避免自动演化失控。前端有学习者工作台和 operator 控制台，后端使用 FastAPI、PostgreSQL、Redis、Alembic、pytest 和 Docker Compose。

### 2 分钟版本

> 这个项目的出发点是教育智能体不能只做单轮问答，它需要知道学习目标、当前进度、薄弱点和历史上下文。所以我把系统拆成几条主链路：第一条是学习目标到学习计划、每日任务、工作流执行的任务闭环；第二条是教学会话链路，支持解释、Quiz、Hint 和消息历史；第三条是长期记忆链路，把对话、任务结果和反思结果沉淀成候选记忆，并通过 provenance、治理状态和审计控制它们的可信度；第四条是 Agent 治理链路，反思或技能变更必须经过 proposal -> sandbox -> evaluation -> approval，不能直接影响生产行为。
>
> 工程上，后端按应用服务、领域实体、基础设施分层，数据库用 PostgreSQL 和 Alembic 管理迁移，Redis 用于运行时依赖，测试用 pytest 覆盖 session、goal、task、quiz、memory、reflection、worker 和 audit 等路径。前端用 React 和 TypeScript 做学习工作台和 operator 控制台。后续我准备把用户上传资料和知识图谱接进来，把资料中的概念、前置关系和掌握度映射到学习路径生成、Quiz 和 Hint。

---

## 面试高频问题与回答口径

### 1. 这个项目解决什么问题？

回答：

> 它解决的是普通 AI 问答缺少长期学习上下文的问题。教育场景里，系统不仅要回答当前问题，还要知道用户的学习目标、历史会话、薄弱知识点、任务进度和复习节奏。所以我把项目设计成学习目标、学习任务、教学会话、长期记忆和治理审计几个模块，而不是单一聊天接口。

可补充：

- 单轮问答：只关注当前 prompt。
- 教育智能体：需要目标、路径、记忆、评估和干预。
- 本项目验证的是“长期学习闭环”，不是只验证模型生成能力。

### 2. 项目整体架构是什么？

回答：

> 架构上分为 UI、Application、Domain、Infrastructure 四层。UI 是 React 工作台；Application 放业务服务，例如 chat、goal、task、quiz、memory、reflection；Domain 放学习目标、会话、记忆、技能、审计等实体和 schema；Infrastructure 负责数据库、Redis、LLM Provider、Embedding Provider 和观测。这样做是为了避免路由直接写业务逻辑，也避免领域层依赖 FastAPI 或数据库实现。

### 3. 核心业务流程是什么？

回答：

> 最核心的是 LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun。用户创建学习目标后，系统生成学习计划和阶段任务；每天可以物化出 DailyTask；执行任务时会创建或进入学习会话；会话过程中可以调用解释、Quiz、Hint 等教学技能；任务结果再反向影响学习记录和记忆候选。

### 4. 你为什么要做长期记忆？

回答：

> 教育场景需要连续性。比如用户多次在同一个概念上出错，系统应该在后续解释、出题和复习安排里体现这一点。长期记忆不是简单保存聊天记录，而是把对话、任务结果、反思结果转成候选记忆，再通过治理状态和证据链决定是否进入更可信的记忆层。

### 5. 记忆机制怎么设计？

回答：

> 当前有 session memory 和 long-term memory candidate 两层。session memory 更接近近期上下文，服务当前会话；long-term memory candidate 用于沉淀跨会话的知识点、行为模式和学习证据。候选记忆会保留 provenance，标明来自会话事件、任务结果还是反思结果，后续再通过治理策略晋升、压制或刷新。

### 6. 为什么不能直接把模型输出写进长期记忆？

回答：

> 因为模型输出可能有误，也可能过度推断用户状态。教育场景中如果错误地记录“用户已经掌握某知识点”，会影响后续教学路径。所以系统默认把自动抽取结果作为 candidate，不直接写成高信任状态，并通过治理、审计和 provenance 控制晋升。

### 7. Reflection 和 Skill Evolution 是什么？

回答：

> Reflection 是对教学结果或任务结果做复盘，例如某次提示是否有效、某个策略是否导致失败。Skill Evolution 是根据反思结果提出改进建议。但我没有让反思直接修改系统行为，而是设计成 proposal -> sandbox -> evaluation -> approval。也就是先提案，再沙箱评估，再审批，最后才可能影响运行时。

### 8. 你怎么保证 Agent 不失控？

回答：

> 主要靠治理边界。高风险变更不能从模型输出直接进入生产路径；工具执行和技能变更要经过 allowlist、sandbox、approval、audit；记忆写入先进入 candidate；operator 控制台可以查看反思、提案、审计和运行状态。系统默认 fail-closed，也就是权限、审批或证据不足时不继续执行高风险路径。

### 9. 前端做了哪些？

回答：

> 前端是 React + TypeScript，主要有学习者侧和 operator 侧。学习者侧包括学习目标、会话列表、学习工作台，工作台里有对话、Quiz、Hint 和任务面板。operator 侧包括系统防护状态、反思审核、提案审核、Curator 建议、审计事件、Quiz attempt、学习增益等页面。前端通过 TanStack Query 封装 API 请求和缓存，处理 loading、error 和 mutation 状态。

### 10. 这个项目最难的地方是什么？

回答：

> 难点不是调用大模型，而是把大模型输出放进一个可控的业务系统里。比如模型生成的解释、Quiz、记忆候选、反思建议都不能直接当作可信事实或生产变更，所以需要 schema 校验、provenance、治理状态、审计和审批路径。另外，长期任务和 worker 路径还要考虑重试、幂等和部分失败后的状态一致性。

### 11. 项目有哪些不足？

回答：

> 当前更准确地说是教育智能体原型系统，不是完整生产级产品。主要不足有三点：第一，Web-first 产品表面还可以继续收口；第二，资料上传和知识图谱还属于后续增强方向；第三，生产级运维能力，例如成本控制、告警通知、长期压测，还需要继续补齐。我在简历里会把已完成能力和计划能力分开，不会说成已经上线生产。

### 12. 如果继续做，你下一步做什么？

回答：

> 下一步我会收紧到“用户资料知识图谱增强教学”这条线。先支持 PDF、Markdown、TXT 上传，做文本切分、概念抽取、前置关系识别和知识图谱构建。然后把图谱节点和学习目标、Quiz、Hint、掌握度关联起来，让系统能根据资料结构和用户薄弱点生成个性化学习路径。

### 13. 知识图谱准备怎么接入？

回答：

> 我会把知识图谱限定为教育场景下的轻量图谱：节点是概念、章节、资料片段和学习目标；边包括 prerequisite、contains、related_to、evidence_for。图谱不做复杂本体推理，主要服务三个功能：学习路径生成、相关资料检索、薄弱知识点定位。

### 14. 上传资料怎么处理？

回答：

> 资料上传后先进入 ingestion pipeline：文件解析、文本切分、元数据记录、概念抽取、关系抽取、置信度过滤、人工审核或自动入库。每个概念和关系都要保留来源片段，避免图谱节点没有证据。前端会提供资料库、资料详情、图谱视图和 operator 审核页面。

### 15. 怎么评价这个系统效果？

回答：

> 可以从工程和教学两个角度评价。工程上看核心链路测试、API 成功率、worker 失败恢复、审计完整性。教学上可以设计小规模数据集，比较没有记忆/图谱增强和有记忆/图谱增强时，解释相关性、Quiz 覆盖率、学习路径合理性、用户答题提升和人工评分。

### 16. 为什么说它不是简单套壳 ChatGPT？

回答：

> 简单套壳通常只有一个聊天入口，业务状态主要停留在 prompt 里。这个项目把教育过程拆成了学习目标、计划、每日任务、会话、Quiz、Hint、记忆、反思和审计等持久化对象。模型只是其中的生成能力，真正的系统价值在于学习状态建模、任务闭环、记忆治理和受控执行路径。

### 17. 你在项目里主要负责什么？

回答：

> 可以按模块说：我主要负责学习目标与任务闭环、教学会话链路、长期记忆候选、反思治理和前端工作台整合。后端侧包括服务层、schema、仓储、迁移和测试；前端侧包括学习工作台、目标详情、任务面板和 operator 侧治理视图。实际面试时要根据自己真实修改过的模块收窄，不要把整个仓库都说成一个人完整完成。

### 18. 后端为什么采用分层架构？

回答：

> 因为这个项目有很多高风险业务状态，比如记忆晋升、任务状态、反思提案、审批和审计。如果把逻辑都写在 route 里，后续很难保证事务、权限和审计一致性。所以路由只负责输入输出和权限入口，Application service 处理业务流程，Domain 保持框架无关，Infrastructure 负责数据库、Redis、LLM 和 embedding。

### 19. FastAPI 路由层主要做什么？

回答：

> 路由层应该保持薄，只做请求参数校验、身份上下文解析、调用 service、提交或回滚事务、返回统一响应。像学习计划生成、任务状态转换、记忆治理、审批判断这类业务逻辑不应该放在 route 里。

### 20. 数据库里有哪些核心表？

回答：

> 可以按业务域回答：学习会话相关有 learning_sessions、session_messages、session_quizzes、session_quiz_questions；学习目标和任务相关有 learner_goals、study_plans、daily_tasks、workflow_runs；记忆相关有 memory event、knowledge memory、behavior memory、embedding 或治理记录；治理相关有 reflection records、evolution proposals、skill artifacts、audit events。面试时不需要背所有表名，重点讲清楚对象之间的关系。

### 21. 为什么需要 Alembic？

回答：

> 项目有较多持久化对象，数据库结构会随着功能迭代变化。Alembic 用来管理 schema migration，保证本地、测试和部署环境能按版本演进，而不是手工改库。对学习任务、记忆、反思、技能治理这类状态型系统，迁移可追踪很重要。

### 22. PostgreSQL 和 Redis 分别承担什么？

回答：

> PostgreSQL 存放核心业务状态，比如学习目标、会话、消息、任务、记忆、审计和治理记录，因为这些数据需要事务和持久化。Redis 更适合运行时辅助能力，比如缓存、队列、限流或 worker 协调。不能把长期学习状态只放 Redis，因为它不是系统可信数据源。

### 23. 为什么任务执行需要 WorkflowRun？

回答：

> DailyTask 表示“应该做什么”，WorkflowRun 表示“这次执行发生了什么”。两者分开后，可以保留任务本身的计划信息，也能记录每次执行的状态、结果、失败原因、关联会话和审计信息。这样更适合做重试、复盘和学习效果分析。

### 24. DailyTask 和 StudyPlan 有什么区别？

回答：

> StudyPlan 是围绕学习目标生成的阶段性路径，偏长期规划；DailyTask 是从计划中物化出来的具体任务，偏可执行单元。比如一个计划阶段是“掌握栈和队列”，每日任务可以是“学习栈的基本操作并完成 5 道练习”。

### 25. 任务状态怎么设计？

回答：

> 任务状态要能表达 pending、due、in_progress、completed、failed、skipped 等生命周期。状态转换应该由 service 或 domain transition 控制，不能在 route 或 repository 里随便赋值。这样可以集中处理审计、重试、幂等和失败后的状态一致性。

### 26. Worker 路径需要注意什么？

回答：

> Worker 最关键的是幂等、租约、重试和失败恢复。比如一个定时任务被重复消费时，不能重复创建大量 DailyTask；执行失败后要记录原因并可重试；如果 worker 中途挂掉，需要通过 lease 或状态检查恢复，而不是留下不可解释的半完成状态。

### 27. 你怎么处理事务一致性？

回答：

> 核心原则是明确事务 owner。一次写路径里，核心状态写入、必要审计和必需校验应该在提交前完成。如果提交后再做必须成功的副作用，就可能造成状态不一致。对于可以异步补偿的动作，可以设计成 post-commit job 或明确的后台协调路径。

### 28. AuditEvent 的作用是什么？

回答：

> AuditEvent 用来记录关键行为，比如任务状态变化、记忆治理、反思提案、审批、工具执行或权限拒绝。它不是普通日志，而是可追溯证据。对教育智能体来说，系统为什么做了某个教学调整、为什么压制某条记忆、谁批准了某个变更，都应该能查到。

### 29. 权限怎么考虑？

回答：

> 项目里要区分 learner、operator 和 system actor。学习者只能访问自己的目标、会话和任务；operator 可以查看治理、审计和审核队列；system actor 代表后台任务或自动流程。高风险路径不能靠前端隐藏按钮保护，后端必须做认证、授权和审计。

### 30. 为什么需要 operator 控制台？

回答：

> 因为教育智能体有长期记忆和策略演化，不能完全黑箱运行。operator 控制台提供治理入口，可以查看系统防护、反思审核、提案审核、Curator 建议、审计事件、Quiz attempt 和学习效果指标。它的作用是把 Agent 行为变成可观察、可干预的流程。

### 31. LLM Provider 怎么封装？

回答：

> Provider 封装的目的是隔离模型厂商差异。业务服务不应该直接依赖某个 SDK，而是依赖统一的聊天或 embedding 接口。这样后续可以切换 mock provider、DashScope compatible provider 或其他模型服务，也方便测试时使用 fake provider 保持确定性。

### 32. 为什么测试里不能依赖真实大模型？

回答：

> 真实模型输出不稳定，调用成本和网络状态也不可控。如果默认测试依赖真实 Provider，会导致测试慢、贵、不可重复。默认测试应该用 mock 或 fake provider，真实模型测试作为 gated regression 或 smoke test 单独运行。

### 33. Prompt 怎么管理？

回答：

> Prompt 不应该散落在各个接口里。更稳的做法是按能力拆分，比如 explain_concept、create_quiz、adaptive_hint、plan_study_path，每个能力有明确输入、输出 schema 和校验逻辑。模型输出必须结构化解析和验证，不能直接当作可信业务对象。

### 34. Quiz 生成怎么保证质量？

回答：

> 首先用结构化输出约束题目、选项、答案、解析、难度和知识点；其次做 schema 校验和数量限制；再结合 session 或 goal 上下文生成题目；最后通过 quiz attempt 记录用户作答结果，用于分析错误点和学习增益。质量评价可以看题目有效性、覆盖知识点、答案一致性和人工评分。

### 35. Hint 和直接给答案有什么区别？

回答：

> Hint 应该提供逐步提示，而不是直接替用户完成。教育场景里，提示要帮助学生定位思路、回忆前置概念或纠正常见误区。系统可以根据用户当前问题、历史错误和相关知识点生成提示，但应避免直接给出完整答案，除非用户明确请求讲解。

### 36. 学习掌握度怎么建模？

回答：

> 可以把掌握度看成知识点上的动态状态，来源包括 Quiz 正确率、错误类型、任务完成情况、近期复习表现和用户自评。它不应该只由一次答题决定，而应该结合证据和时间衰减。后续接入知识图谱时，掌握度可以挂在概念节点上，用来驱动路径推荐和复习调度。

### 37. Spaced review 或复习调度怎么做？

回答：

> 最小版本可以根据掌握度、最近答题结果和任务完成情况调整复习间隔。比如掌握度低或近期错误多，就缩短复习间隔；连续正确则拉长间隔。这个项目可以先实现规则策略，后续再引入更复杂的记忆曲线或个性化模型。

### 38. Reflection 的输入来自哪里？

回答：

> Reflection 可以来自任务失败、Quiz 表现、用户反馈、会话结果或 operator 审核。它分析的是某次教学或执行结果是否有效、失败原因是什么、是否需要调整提示词、技能、计划或复习策略。但 reflection 只产生建议或提案，不直接修改生产行为。

### 39. proposal -> sandbox -> evaluation -> approval 每一步做什么？

回答：

> proposal 是候选变更，比如提示词、技能策略或工作流调整；sandbox 是隔离环境或离线评估，不影响生产；evaluation 记录评估结果和证据；approval 是人工或治理策略确认。只有通过审批的变更才可能进入 rollout 或 staging。

### 40. 如果一个提案效果不好怎么办？

回答：

> 提案应该保留失败评估结果，不应该静默删除。失败结果可以作为后续反思和治理证据。如果已经 rollout 后效果变差，需要 rollback 或 deprecate 相关 artifact，并记录审计事件。这样系统能解释“为什么没有采用某个自动建议”。

### 41. 你怎么做可观测性？

回答：

> 可观测性分几层：业务审计记录关键状态变化；Prometheus/Grafana 观察运行指标；错误响应有统一 code；operator 控制台展示 guardrails、队列、审计和学习效果。对 Agent 系统来说，只看 HTTP 状态码不够，还要知道模型调用、记忆写入、任务调度和治理路径是否正常。

### 42. 限流和熔断为什么重要？

回答：

> 项目会调用 LLM 和 embedding provider，成本和延迟都不可忽略。如果没有限流、超时、熔断和预算保护，少量异常请求就可能放大成成本问题或服务不可用。教育场景还涉及后台任务，如果 worker 批量触发模型调用，更需要 guardrail。

### 43. API 错误怎么设计？

回答：

> 前后端应该使用稳定的错误结构，例如 status、code、message。前端不能只解析字符串，否则难以区分 rate limit、provider timeout、not found、validation error 和 circuit open。稳定错误码也方便 UI 给出不同反馈和测试断言。

### 44. 前端为什么用 TanStack Query？

回答：

> 因为学习目标、会话、任务、Quiz 和 operator 数据都是服务端状态。TanStack Query 可以统一处理缓存、加载、错误、刷新和 mutation 状态，避免每个组件手写重复的 useEffect 和 loading/error 管理。

### 45. 前端组件怎么拆？

回答：

> 页面组件负责组装数据和布局，具体展示拆成 MessageThread、ChatComposer、QuizPanel、HintPanel、TaskPanel 等组件。这样学习工作台不会变成一个巨大组件。数据请求放在 hooks 或页面边界，展示组件尽量不直接请求后端。

### 46. 前端如何处理权限？

回答：

> 前端可以根据权限隐藏或禁用按钮，但这只是体验优化。真正的权限判断必须在后端。operator key、learner key 之类的身份上下文只能作为请求凭证，不能让浏览器状态成为权限来源。权限失败时前端要展示明确错误，而不是假装操作成功。

### 47. Markdown 或模型生成内容怎么安全渲染？

回答：

> 用户输入和模型输出都要当作不可信内容。前端渲染 Markdown 时要使用安全组件，避免直接插入未清洗 HTML。后端也不应该把内部 prompt、secret 或治理细节暴露给前端。

### 48. 你会怎么设计资料上传表？

回答：

> 可以拆成 material、material_chunk、extracted_concept、extracted_relation、ingestion_job。material 存文件元信息和归属；chunk 存文本分片和位置；concept/relation 存抽取结果、置信度和来源 chunk；ingestion_job 存解析状态、失败原因和重试信息。

### 49. 知识图谱用关系型数据库还是图数据库？

回答：

> 初期可以先用 PostgreSQL 表建模节点和边，因为需求主要是概念、前置关系、来源证据和掌握度，不一定需要复杂图查询。等出现多跳路径、复杂图算法或大规模关系查询瓶颈时，再评估 Neo4j 或图数据库。简历项目阶段不要为了概念引入过重基础设施。

### 50. 知识图谱和 RAG 有什么区别？

回答：

> RAG 更偏文本检索，把相关片段取出来增强回答；知识图谱强调概念和关系，比如前置、包含、关联、掌握状态。教育场景里两者可以结合：RAG 提供资料证据，图谱提供学习路径和知识结构。回答问题时用 RAG 找来源，规划学习时用图谱找前置关系和薄弱节点。

### 51. 图谱抽取错误怎么办？

回答：

> 抽取结果不能直接成为高信任图谱。每个节点和边要保留来源片段、置信度和抽取版本；低置信度结果进入审核队列；operator 可以确认、合并、删除或修正。后续用户答题和教学反馈也可以作为图谱质量修正信号。

### 52. 如何避免知识图谱变成一堆无用节点？

回答：

> 要控制粒度和用途。节点应该是可教学、可出题、可评估的概念，而不是任意名词。还要有去重、同义词合并、孤立节点检查、无来源边检查和低置信度边审核。图谱服务的是学习路径和掌握度，不是为了展示复杂网络图。

### 53. 用户上传资料后怎么和学习目标关联？

回答：

> 资料可以在上传时选择关联目标，也可以通过抽取出的主题和概念与目标匹配。目标下的学习计划生成时优先使用关联资料中的概念、章节和前置关系。这样同一份资料可以服务多个目标，但每个目标的学习路径和掌握度是独立的。

### 54. 如果上传资料和模型知识冲突怎么办？

回答：

> 教育系统应该优先标明来源。上传资料中的内容和模型常识冲突时，回答要说明依据哪份资料，不能假装没有冲突。可以把冲突记录成待审核项，operator 或用户确认后再影响图谱和教学路径。

### 55. 这个项目怎么部署？

回答：

> 本地开发用 Docker Compose 启动 API、PostgreSQL、Redis 等服务；数据库用 Alembic 迁移；前端是 Vite/React 开发服务或构建后部署。生产化还需要补齐 HTTPS、正式鉴权、密钥管理、日志采集、告警通知、备份和成本控制。

### 56. 你怎么做测试？

回答：

> 后端用 pytest 覆盖 service、repository、API、worker、memory、reflection、quiz 等路径；默认使用 mock provider，避免依赖真实模型。前端测试重点覆盖 Quiz、答题反馈、API client 等交互。高风险路径要测失败、拒绝、幂等、回滚和审计，不只测 happy path。

### 57. 这个项目最容易被质疑哪里？

回答：

> 最容易被质疑的是范围太大。所以面试时要主动收窄：当前不是完整商业产品，而是教育智能体工程原型，重点验证长期学习上下文、任务规划、记忆治理和受控演化。知识图谱、资料上传和生产运维是下一阶段，不把计划能力说成已完成。

### 58. 如果面试官说“这个项目太大不像学生项目”怎么办？

回答：

> 可以承认项目覆盖面比较大，然后把自己的贡献收敛到几个模块：学习任务闭环、教学会话、记忆候选、治理审计、前端工作台。再说明很多能力是原型级闭环，不是所有生产细节都完整实现。可信的关键是讲清楚具体数据流和取舍，而不是硬说全部成熟。

### 59. 如果面试官问“你遇到过什么 bug”怎么答？

回答：

> 可以选一个状态一致性或模型输出校验类问题。例如模型返回的 Quiz JSON 不稳定，导致解析失败；解决方式是加强 schema 校验、错误处理和 mock regression。或者任务执行后部分状态已写入但后续副作用失败，解决方式是明确事务边界，把后续协调拆成可重试 job 或在提交前完成必要审计。

### 60. 如果面试官要求现场画架构图，怎么画？

回答：

> 从上到下画四层：React Web 工作台；FastAPI routes；Application services，包括 goal、task、chat、quiz、memory、reflection、skill、audit；Domain entities 和 schemas；Infrastructure，包括 PostgreSQL、Redis、LLM Provider、Embedding Provider、Prometheus/Grafana。旁边画主流程 LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun -> Session -> Memory/Audit。

### 61. 如果面试官问“项目有什么量化结果”怎么办？

回答：

> 如果没有真实用户数据，不要编。可以说目前主要是工程验证，量化包括测试数量、覆盖的核心链路、Docker smoke、API 成功路径、worker 路径和 operator 可观测项。后续如果做知识图谱实验，会补充图谱抽取准确率、Quiz 覆盖率、人工评分和学习前后测提升。

### 62. 如果被问“为什么不用 LangChain / LlamaIndex”怎么答？

回答：

> 可以说这个项目重点是教育业务状态和治理闭环，不是快速拼接 Agent demo。LangChain 或 LlamaIndex 可以用于 RAG、工具编排或资料解析，但核心的学习目标、任务生命周期、记忆治理、审批和审计仍然需要自己建模。后续接入资料上传时，可以评估局部使用它们，但不会让框架接管业务状态。

### 63. 如果被问“为什么不用微服务”怎么答？

回答：

> 当前阶段单体分层更合适。项目仍在快速验证业务模型，如果拆成微服务，会增加部署、事务、观测和接口成本。现在用模块化单体保持清晰边界，等流量、团队和部署需求真的增长，再拆出 ingestion、worker、model gateway 或 graph service。

### 64. 如果被问“如何支持多用户”怎么答？

回答：

> 多用户的关键是 profile 或 learner identity 隔离。学习目标、会话、任务、记忆和资料都要归属到 learner profile；API 查询必须带身份上下文并做过滤；operator 路径单独授权。不能只在前端按用户筛选，后端 repository 和 service 都要保证数据隔离。

### 65. 如果被问“如何删除用户数据”怎么答？

回答：

> 需要设计 profile 级数据删除或归档策略，覆盖目标、会话、消息、任务、记忆、资料、图谱节点和审计相关引用。审计日志可能不能物理删除，但要避免保留敏感正文，可以用脱敏摘要和安全标识。这个能力偏生产合规，当前可以作为后续生产化增强点。

### 66. 如果被问“如何控制成本”怎么答？

回答：

> 成本主要来自 LLM、embedding 和后台批处理。可以通过 per-user rate limit、provider timeout、熔断、缓存、批处理限额、模型分级、任务队列限速和预算告警控制。默认测试使用 mock provider，避免开发和 CI 阶段产生真实调用成本。

### 67. 如果被问“怎么处理模型幻觉”怎么答？

回答：

> 幻觉不能完全消除，只能降低影响范围。做法包括结构化输出校验、资料来源引用、低置信度标记、知识图谱证据链、operator 审核、记忆 candidate 机制和用户反馈。尤其不能把模型推断直接写入高信任记忆或教学策略。

### 68. 如果被问“这个项目和普通在线教育系统有什么不同”怎么答？

回答：

> 普通在线教育系统通常围绕固定课程、题库和进度管理；这个项目重点是 Agent 根据学习目标和历史上下文动态生成解释、练习、提示和任务，并通过长期记忆和治理链路持续调整。它不是替代 LMS，而是在 LMS 之上提供个性化教学智能体能力。

### 69. 如果被问“你从这个项目学到了什么”怎么答？

回答：

> 最大收获是 Agent 项目不能只关注模型能力，工程上更重要的是状态建模、边界控制、审计、失败恢复和可测试性。特别是在教育场景，错误记忆、错误掌握度和未审核策略都会影响学习路径，所以需要把模型输出放进受控业务流程里。

### 70. 如果被问“这个项目还要多久能产品化”怎么答？

回答：

> 可以说还需要补几类工作：收口 Web-first 产品流程、完善资料上传和知识图谱、加强真实用户评估、补齐生产鉴权和数据隔离、完善成本控制和告警、做压测与稳定性验证。它现在适合作为原型和简历项目，不能直接说已经产品化。

---

## STAR 法面试表达

### 场景

> 普通大模型问答无法持续跟踪学习目标和薄弱点，教育场景需要长期记忆、任务规划和可控治理。

### 任务

> 设计并实现一个教育智能体原型系统，支持从学习目标到计划、任务、会话、练习、记忆和审计的闭环。

### 行动

> 我把系统拆成学习目标、任务规划、教学会话、长期记忆、反思治理、operator 控制台几部分；后端使用 FastAPI、PostgreSQL、Redis 和 Alembic；前端使用 React 和 TypeScript；并为高风险 Agent 行为设计 proposal、sandbox、evaluation、approval 和 audit 路径。

### 结果

> 项目实现了学习目标、学习计划、每日任务、教学会话、Quiz、Hint、长期记忆候选、反思提案和 operator 审计等主链路。它可以作为教育智能体方向的工程原型，后续继续接入用户资料上传和知识图谱增强个性化教学。

---

## 面试中应避免的说法

不要说：

- “已经是生产级教育智能体平台。”
- “实现了完整多 Agent 自治。”
- “系统可以自动进化并优化自己。”
- “已经完整支持知识图谱。”
- “长期记忆一定准确。”
- “前端和后端都已经完全产品化。”

推荐改成：

- “当前是教育智能体原型系统，核心链路已打通。”
- “多 Agent 和更强自治是架构预留或后续阶段。”
- “技能演化通过受控治理链路验证，不是直接自我修改。”
- “知识图谱是下一阶段增强方向。”
- “长期记忆通过 candidate、provenance 和治理状态降低误写风险。”
- “Web 工作台已有学习者侧和 operator 侧基础页面，仍可继续收口。”

---

## 简历压缩版

适合一页简历：

```text
Agent-Edu 教育智能体学习平台 | FastAPI, React, PostgreSQL, Redis, Docker, pytest
- 构建面向个性化学习的教育智能体原型系统，支持学习目标、教学会话、Quiz/Hint、学习任务规划、长期记忆和治理审计。
- 设计 LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun 闭环，实现从学习目标到每日任务和会话执行的流程承接。
- 实现 session memory 与 long-term memory candidate，将对话、任务结果和反思结果沉淀为可追溯、可治理的学习记忆。
- 引入 proposal -> sandbox -> evaluation -> approval 治理链路，约束反思和技能变更，避免 Agent 直接修改生产行为。
- 搭建 React 学习工作台和 operator 控制台，并使用 Alembic、pytest、Docker Compose、Prometheus/Grafana 完成本地验证与观测。
```

---

## 面试前准备清单

面试前至少准备清楚：

- 能画出系统架构图：UI、Application、Domain、Infrastructure。
- 能讲清楚 `LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun`。
- 能讲清楚 session memory 和 long-term memory candidate 的区别。
- 能讲清楚为什么模型输出不能直接写入长期记忆或生产策略。
- 能讲清楚 proposal -> sandbox -> evaluation -> approval。
- 能演示学习目标、会话、Quiz、Hint、任务面板和 operator 控制台。
- 能说明哪些能力已完成，哪些是后续计划。
- 能回答“为什么这不是简单套壳 ChatGPT”。
- 能回答“如果接入知识图谱，数据模型和页面怎么设计”。

---

## 后续资料上传与知识图谱页面规划

如果继续增强项目，建议新增页面控制在以下范围：

学习者侧：

- `/materials`：资料库，支持上传资料、查看解析状态、资料列表和关联学习目标。
- `/materials/:id`：资料详情，展示分段内容、抽取概念、来源片段和低置信度项。
- `/goals/:id/graph`：目标知识图谱，展示概念节点、前置关系、掌握状态和来源资料。
- `/sessions/:id` 右侧新增 `知识点` 或 `资料上下文` tab，展示当前会话命中的图谱节点和资料片段。

operator 侧：

- `/operator/ingestion`：资料解析审核，处理抽取失败、低置信度概念和待确认边关系。
- `/operator/graph-quality`：图谱质量，展示孤立节点、重复概念、低置信度边、无来源边和覆盖率统计。

不要优先做：

- 通用文件网盘。
- 复杂图数据库管理后台。
- 全学科知识库市场。
- 自动本体推理平台。
- 大而全 BI 报表。

知识图谱增强的核心闭环应保持为：

```text
上传资料 -> 文本切分 -> 概念/关系抽取 -> 置信度过滤/人工审核 -> 知识图谱 -> 个性化学习路径 -> Quiz/Hint/解释 -> 答题结果 -> 掌握度更新
```

