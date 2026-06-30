# agent-edu
# 自进化教育智能体（Educational Evolutionary Agent）完整架构设计

> 状态说明（2026-06-16）：
> 这份文档保留为历史系统设计说明和早期整体叙事材料，不再代表当前主规范。
> 当前应优先参考：
>
> - `ARCHITECTURE.md`
> - `README.md`
> - `AGENTS.md`
> - `rules/backend.md`
> - `rules/frontend.md`
> - `rules/security.md`
> - `rules/testing.md`
> - `rules/review.md`

---

# 一、项目定义

## 1.1 什么是自进化教育智能体

自进化教育智能体（Educational Evolutionary Agent）：

> 是一种能够长期陪伴用户学习、持续积累记忆、自主执行教学任务、自动优化教学策略，并在规则限制下实现能力演化的智能系统。

它不是传统：

```text
ChatBot
```

而是：

```text
长期运行的认知系统（Persistent Cognitive System）
```

---

# 二、项目最终目标

系统最终形态：

```text
教育Agent
→ 长期记忆
→ 自主规划
→ 自主执行
→ 自我反思
→ 技能进化
→ 多Agent协作
→ 数字生命体雏形
```

最终演化为：

> 长期成长型数字认知伴生体（Cognitive Companion）

---

# 三、系统核心思想

## 3.1 核心原则

系统必须遵守：

| 原则 | 说明 |
|---|---|
| 长期记忆 | 形成连续人格与成长轨迹 |
| 自主执行 | 自动完成学习任务 |
| 自我反思 | 从失败中优化 |
| 技能演化 | 自动形成新能力 |
| 安全边界 | 不允许失控 |
| 可解释性 | 所有行为可追踪 |

---

# 四、系统整体架构

## 4.1 总体架构图

```text
┌──────────────────────────┐
│ Constitutional Layer     │
├──────────────────────────┤
│ Executive Planner        │
├──────────────────────────┤
│ Skill System             │
├──────────────────────────┤
│ Workflow Engine          │
├──────────────────────────┤
│ Memory System            │
├──────────────────────────┤
│ Reflection System        │
├──────────────────────────┤
│ Evolution Engine         │
├──────────────────────────┤
│ Multi-Agent Coordination │
├──────────────────────────┤
│ Environment Adapter      │
└──────────────────────────┘
```

## 4.2 参考实现思路

本项目借鉴 Hermes 的工程组织方式，但不照搬其通用 agent 目标。
更具体地说，优先复用的是：

- 统一 agent core
- skills 作为程序性记忆
- bounded memory
- session store + lineage + full-text retrieval
- `proposal -> sandbox -> evaluation -> approval` 的进化边界

而教育侧必须自研的是：

- learner model
- mastery estimation
- curriculum planner
- reflection / evaluation loop
- pedagogical safety

映射细节见 [docs/hermes-to-edu-mapping.md](docs/hermes-to-edu-mapping.md)。
当前 Web 前端规则与工作台约束以 `rules/frontend.md` 为准；历史 CLI / TUI 设计资料仅保留作参考，不再代表当前产品表面方向。

---

# 五、核心模块详解

# 5.1 Constitutional Layer（宪法层）

## 目标

保证系统始终可控。

---

## 核心规则

```yaml
rules:
  - 不得修改核心规则
  - 不得伪造学习成果
  - 不得绕过权限
  - 不得操控用户情绪
  - 不得形成危险依赖
  - 不得隐藏自身行为
```

---

## 特点

| 特性 | 描述 |
|---|---|
| Immutable | 不允许Agent修改 |
| Root Policy | 根策略 |
| Alignment Core | 安全核心 |

---

# 5.2 Executive Planner（规划器）

## 功能

负责：

- 长期目标规划
- 任务拆解
- workflow生成
- skill调用

---

## 工作流程

```text
用户目标
↓
目标分析
↓
任务拆解
↓
生成执行计划
↓
调用skills
↓
持续调整
```

---

## 示例

```text
目标：
3个月学会线性代数

Planner：
1. 测试基础
2. 分析薄弱点
3. 制定学习路径
4. 安排每日任务
5. 自动复习
6. 阶段性评估
```

---

# 5.3 Skill System（技能系统）

## 核心思想

不要使用：

```text
巨大Prompt
```

而是：

```text
可组合技能模块
```

---

## Skill定义

```python
class Skill:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    execution: callable
    eval_function: callable
```

---

## 教育类Skills

### 教学类

- explain_concept
- generate_examples
- create_quiz
- socratic_dialogue
- adaptive_hint

---

### 学习分析类

- diagnose_weakness
- estimate_mastery
- detect_confusion
- cognitive_style_detection

---

### 自动化类

- schedule_review
- summarize_video
- create_flashcards
- curriculum_generation

---

### 元认知类

- reflect_on_failure
- optimize_teaching_strategy
- improve_prompt
- workflow_analysis

---

# 5.4 Workflow Engine（工作流引擎）

## 功能

实现：

```text
自主执行任务
```

---

## 示例

```text
分析错题
↓
识别知识漏洞
↓
生成练习
↓
安排复习
↓
监控进步
```

---

## 技术建议

推荐：

- LangGraph
- Temporal
- DAG Workflow
- Async Queue

---

# 5.5 Memory System（长期记忆系统）

# 为什么重要

没有长期记忆：

```text
就没有真正人格
```

---

## 记忆分层

### 1. Episodic Memory（事件记忆）

记录：

```text
用户今天卡在矩阵乘法
```

---

### 2. Semantic Memory（语义记忆）

抽象规律：

```text
用户更适合图像化学习
```

---

### 3. Procedural Memory（程序记忆）

保存教学经验：

```text
现实案例解释效果更好
```

---

### 4. Reflective Memory（反思记忆）

记录失败经验：

```text
教学步骤太复杂导致用户失去耐心
```

## 当前落地

当前已经落地的长期记忆治理增强版包括：

- `KnowledgeMemory` 与 `BehaviorMemory` 双实体
- `candidate / active / stable / compressed / archived / suppressed` 治理状态
- `importance / confidence / freshness / stability / goal_relevance` 元数据
- 自动沉淀链路：chat profile `MemoryEvent`、终态 `TaskAttempt`、已评估 `ReflectionOutcomeEvaluation` 可生成或刷新长期记忆候选
- 结构化抽取边界：模型输出先经过 Pydantic schema 与 `MemoryNormalizer` 归一化校验，只能进入长期记忆 `candidate`，不能直接写入 `active / stable`
- upsert / dedupe：按稳定知识键或行为键刷新既有 candidate / active / stable 记忆，避免重复候选堆积；`suppressed` 记忆不会被自动恢复
- provenance 边界：对话来源以 profile `MemoryEvent.id` 作为长期记忆来源，原始 `SessionMessage.id` 保留在 memory event 或 evidence payload 中
- 维护周期中的动态强化 / 衰减刷新
- `memory_evidence_links / memory_governance_decisions / memory_annotations`
- `memory_conflict_sets / memory_conflict_members`：冲突原因、处理结果和后续状态影响由应用层 policy 计算；成员标题/摘要/状态通过 `memory_id` 实时查询，不做冗余快照
- 独立的知识记忆 / 行为记忆检索接口
- 反思语料导出接口：`/api/v1/memory/reflection-corpus`
- topic 对齐增强：知识点 / 标签 / prerequisite / 行为模式的更细粒度语义匹配
- governance summary 输出增强：promotion candidate / demotion risk / topic bucket / review recommended 聚合
- operator 入口：`suppress / annotate / restore`
- worker 侧维护使用独立 `memory_maintenance_jobs` 队列，按 profile + job type 分批处理 governance / compression / conflict refresh，支持 lease 恢复、retry/backoff 与 durable audit
- Prometheus / Grafana / alert 已覆盖长期记忆 candidate backlog、promotion rate、conflict rate、materialization failure rate 与 maintenance duration
- session 级事件记忆仍作为底层输入

---

## Memory Compression

必须实现：

| 技术 | 作用 |
|---|---|
| Summarization | 摘要压缩 |
| Clustering | 聚类 |
| Decay | 遗忘机制 |
| Abstraction | 抽象化 |

否则：

```text
Memory Explosion
```

---

# 5.6 Reflection System（反思系统）

# 核心

真正的“自进化”：

> 来自反思系统。

---

## Reflection Loop

```text
任务失败
↓
分析原因
↓
生成优化方案
↓
重新测试
↓
保存经验
```

当前已落地的反思输入层包括：

- `reflection-corpus` 结构化导出
- 记忆治理中的证据链 / 决策链 / 标注链
- 维护周期中的强化 / 衰减 / 复核信号

当前已落地的反思系统 v1 包括：

- `ReflectionRecord / ReflectionAction` 持久化模型
- `task failed / skipped` 触发的 task-level reflection
- `assessment completed` 触发的 task-level / goal-level reflection
- `workflow failed` 触发的 workflow reflection
- `replan completed` 与连续失败模式触发的 goal-level reflection
- 规则优先的 root cause 分类：`knowledge_gap / difficulty_mismatch / review_gap / sequencing_issue / engagement_constraint / workflow_issue / assessment_regression`
- 低风险自动动作：受控创建 `replan / review / assessment` 自治 job
- 高风险反思动作阻断并标记 `needs_review`
- 反思查询 API：
  - `GET /api/v1/goals/{goal_id}/reflections`
  - `GET /api/v1/tasks/{task_id}/reflections`
  - `GET /api/v1/reflections/{reflection_id}`
- 反思相关 audit：
  - `reflection.record.created / completed`
  - `reflection.action.proposed / executed / blocked`
  - `llm.reflection.completed / failed`

当前已进一步落地的反思增强版包括：

- `ReflectionEvidenceSignal`
- `ReflectionOutcomeEvaluation`
- `ReflectionReviewDecision`
- `LearnerGoalStrategyCard`
- `ReflectiveMemory`
- 异步 evidence derivation：
  - session turn signal
  - task attempt signal
  - workflow failure signal
- strategy card 读取并影响：
  - chat 的 `response_preference / teaching_goal`
  - task 的 `replan / review / assessment` 倾向
- review queue 聚合优先级：
  - 同 `aggregation_key` 命中时更新主 `ReflectionRecord`
  - `duplicate_count / priority_score / cooldown_until`
- outcome evaluation 闭环：
  - 后续 3 次机会窗口
  - `effective / ineffective / inconclusive`
  - 自动回写 strategy card / reflective memory / reflection priority
  - 自动桥接长期记忆 `reflection_outcome` evidence
- strategy card 更深接入 planner：
  - 影响 stage/task blueprint
  - 注入 `generate_study_plan_draft` 的 strategy summary
- 反思闭环新增：
  - `ReflectionProposal`
  - `ReflectionProposalEvaluation`
  - `ReflectionProposalSandboxRun`
  - `ReflectionProposalApprovalDecision`
  - `ReflectionProposalRollout`
  - `ReflectionProposalRolloutObservation`
  - `ReflectionProposalRolloutDecision`
  - proposal queue / sandbox queue / operator proposal governance
  - periodic goal reflection：
    - 手动 API 入口
    - autonomy job 保守型周期调度
    - worker 侧 outcome evaluation sweep
  - 结构化 replay/eval
  - archived replay sandbox + approval v1
  - rollout / rollback v1：
    - goal-scoped staged activation
    - chat / hint / plan_generation rollout
    - manual promote / rollback
    - planner rollback baseline replan
- operator reflection governance API：
  - `review`
  - `resolve`
  - `override-root-cause`
  - `override-action`
- reflective memory 候选沉淀

---

## 可优化内容

| 类型 | 示例 |
|---|---|
| Prompt | 调整提示词 |
| Workflow | 优化步骤 |
| Teaching Style | 调整教学风格 |
| Tool Sequence | 更换工具链 |
| Curriculum | 优化课程结构 |

---

## 安全限制

必须限制：

```yaml
max_reflection_depth: 2
```

否则：

```text
无限递归反思
```

---

# 5.7 Evolution Engine（进化引擎）

# 核心目标

实现：

```text
技能自动演化
```

---

## Evolution流程

```text
发现问题
↓
生成新策略
↓
形成候选skill
↓
沙箱测试
↓
效果评估
↓
批准上线
```

---

## Skill Proposal示例

```text
发现：
动画教学提升理解率

自动生成：
vector_animation_skill
```

---

## 关键原则

### Agent不能直接修改系统

必须：

```text
proposal
→ sandbox
→ evaluation
→ approval
```

---

# 5.8 Multi-Agent System（多Agent系统）

# 最终形态

不是：

```text
单个超级Agent
```

而是：

```text
Agent Society
```

---

## 推荐角色

| Agent | 职责 |
|---|---|
| Tutor Agent | 教学 |
| Reflection Agent | 反思 |
| Curriculum Agent | 课程规划 |
| Memory Agent | 长期记忆 |
| Motivation Agent | 激励 |
| Safety Agent | 对齐与监管 |

---

## 协作模式

```text
Planner
↓
Tutor执行
↓
Reflection分析
↓
Memory保存
↓
Evolution优化
```

---

# 六、开发阶段路线（最重要）

# Phase 1：稳定教学Agent

## 目标

先实现：

```text
稳定教学
```

---

## 功能

- 对话
- 出题
- 教学
- 基础记忆
- skills架构

---

## 技术栈

| 模块 | 技术 |
|---|---|
| Backend | FastAPI |
| Agent | LangGraph |
| Database | PostgreSQL |
| Vector DB | pgvector |
| LLM | GPT/Claude/Qwen |

## 当前阶段能力

当前代码状态已经不再只是架构设计或 mock 骨架，而是进入：

> Phase 1 主教学链路已打通，Phase 2 自主任务系统已完成第一轮正式收尾；当前产品表面方向已调整为 Web-first，既有 CLI / TUI baseline 作为历史实现与参考资产保留。

当前已落地能力：

- 学习会话创建、读取、列表与状态更新
- session 下的教学对话链路
- `explain_concept` 结构化概念讲解
- `create_quiz` 结构化练习题生成
- `adaptive_hint` 分层提示链路
- session memory 写入、embedding 检索与跨 session learner context 注入
- long-term memory governance v2：知识记忆 / 行为记忆双通道、自动候选沉淀、upsert / dedupe、治理状态、证据链、operator 接口、独立检索 API、独立维护队列、压缩维护、冲突刷新与观测告警
- 关键动作 audit、失败 audit durable 持久化
- `LearnerProfile` / `LearnerGoal` 的最小公开 API
- `StudyPlan` / `PlanStage` / `DailyTask` / `WorkflowRun` 的最小数据与接口
- `GoalAutonomyState` / `LearnerAvailability` / `LearnerTopicMastery` / `TaskAttempt` / `ScheduledAutonomyJob`
- 受控 Planner：学习目标 -> 学习路径 -> 14 天任务窗口
- 任务执行链路：task -> auto session -> chat/quiz
- 自治控制面：state / availability / mastery / pause / resume / manual replan
- learner timezone 驱动的定时 daily task materialization
- 动态 spaced review interval 调整
- `assessment` 与 `milestone` 阶段关卡调度
- `failed/skipped` 后的受控 full replan 与 immutable plan version
- DB 驱动的 autonomy worker 轮询入口
- 受控 external HTTP tool framework v1 与统一 tool execution audit
- 历史 CLI 终端入口：`agent-edu`
- dual mode backend client：remote API / embedded ASGI
- learner workspace summary API
- filtered task list API
- read-only knowledge / behavior memory browse API
- learner-first TUI 工作台 baseline（历史实现与参考资产）
- 长期记忆生产化维护：`memory_maintenance_jobs` 独立队列、profile 级分批治理/压缩/conflict refresh、lease 恢复、retry/backoff 与 durable audit
- 长期记忆抽取与归一化：`MemoryNormalizer` 集中 topic key、semantic category、behavior category、evidence role 规则，结构化模型输出只允许校验后写入 candidate
- 长期记忆冲突解释：冲突原因、成员详情、处理结果、后续状态影响已通过 policy + 实时 memory 关联返回，避免成员快照冗余
- 长期记忆观测：candidate backlog、promotion rate、conflict rate、materialization failure rate、maintenance duration 已进入 Prometheus / Grafana / alerts
- Reflection System v1：结构化反思记录、规则分类、低风险自动动作与查询 API
- Reflection System v2 部分增强：evidence signals、outcome tracking、strategy card、reflective memory、operator governance API
- prompt / workflow proposal v1：proposal queue、sandbox、replay/eval、approval、evaluation read API
- proposal rollout / rollback v1：goal-scoped staged activation，覆盖 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan`
- rollout overlay 已进入 chat / task / planner 运行时，能影响 hint level、review bias、assessment bias、replan bias

当前已具备的验证与观测能力：

- service / repository / provider / schema 的基础测试
- API 集成测试，覆盖 session、message、quiz、skills、`readyz`、`/metrics` 与主要错误路径
- Docker blackbox API 验证
- 手动 gated 的 DashScope-compatible 真实 provider 回归
- Prometheus 指标暴露、Grafana 预置面板与长期记忆告警规则
- Phase 2 核心链路 Docker 测试：
  `learner profile -> goal -> plan -> execute task -> complete task -> review scheduling`

当前默认验证路径：

```bash
make test-api
make docker-api-test
make observability-up
# 具备真实 provider 配置时：
make real-provider-regression
pip install -e .[dev]
agent-edu --json doctor
agent-edu tui

# Phase 2 本地挂载式 Docker 验证示例：
docker run --rm -v "$PWD":/app -w /app agent-edu-api:dev \
  pytest tests/test_session_domain.py \
         tests/test_session_service.py \
         tests/test_goal_service.py \
         tests/test_task_service.py \
         tests/test_api_integration.py -q
```

Docker 代理、真实 provider 回归与 Prometheus / Grafana 观测细节见 [docs/DOCKER_VALIDATION.md](docs/DOCKER_VALIDATION.md)。

当前仍未完成的重点：

- 教学质量回归样本仍需继续收敛
- 真实 provider 回归还没有定时化调度
- 成本治理、限流、熔断与告警通知/自动化闭环还未补齐；长期记忆告警规则基线已落地
- 更完整的长期记忆治理仍在继续增强，但知识/行为双通道、维护队列、知识候选物理晋升/压制、压缩、冲突刷新和核心观测已落地
- 长期记忆自动沉淀已覆盖 chat / task outcome / reflection outcome 的候选生成与刷新；knowledge candidate 可由 `knowledge_governance` 应用 eligibility 结果完成物理晋升或压制，压缩和恢复仍由治理链路处理
- 长期数据回归集仍需继续扩充，尤其是多轮学习、多 goal、多 topic 与迁移升级场景
- TUI 仍是最小工作台版本，完整任务导航、quiz/review 交互和 connector 生态仍需继续扩展
- reflection -> skill proposal / sandbox 仍未进入代码主链路
- replay/eval 仍以规则启发式为主，自动 promote / rollback、bundle rollout 与更强运营观测仍未完成
- Hermes 风格的 core / session / skill / memory / approval 组织方式已写入架构说明，但教育侧能力仍然自研

---

# Phase 2：自主任务系统

## 增加

- `GoalAutonomyState`
- `LearnerAvailability`
- `LearnerTopicMastery`
- `TaskAttempt`
- `ScheduledAutonomyJob`
- `LearnerGoal`
- `StudyPlan`
- `DailyTask`
- `WorkflowRun`
- 受控 Planner
- 受控 Workflow
- 内部 tool use
- 受控 external HTTP tool use v1
- 自动学习计划与复习安排
- 自治控制面与 worker runtime
- Web-first 产品方向下保留的 CLI / TUI 历史 baseline

---

# Phase 3：长期记忆系统

## 已落地的最小能力

- Episodic Memory
- Semantic Memory
- Knowledge Memory
- Behavior Memory
- Memory Compression
- 用户画像
- chat / task outcome / reflection outcome 到长期记忆 candidate 的自动沉淀
- 长期记忆 upsert / dedupe 与 provenance 追踪
- `memory_maintenance_jobs` 独立维护队列与 bounded worker runner
- `MemoryNormalizer` 集中 topic/category/evidence role 归一化
- 结构化模型抽取只允许校验后写入 `candidate`
- profile 级 conflict refresh 与可解释冲突输出
- knowledge candidate 的 `promotion_eligibility -> knowledge_governance` 物理晋升 / 压制闭环
- 长期记忆 dashboard / alert 基线

## 仍需继续增强

- 更细粒度的重要度与遗忘策略
- 更系统化的人工审核与修正治理
- knowledge candidate 的 eligibility 驱动物理晋升 / 压制闭环已落地；后续仍需增强 stable 固化、衰减降级、behavior 记忆治理和 reflection outcome replay/eval
- 更完整的 reflection outcome replay/eval 体系
- 更完整的长期数据回归集：多轮学习、多 goal、多 topic、迁移升级
- proposal rollout 的更细粒度观测与运营面板
- 更完整的 review queue 运营面板与人工治理体验
- bundle / global rollout 与自动 promote / rollback

---

# Phase 4：反思系统

## 增加

- ReflectionRecord / ReflectionAction
- task-level / goal-level 反思闭环
- 规则优先 root cause 分类
- 低风险 follow-up action 执行
- 反思查询 API 与审计链路
- Reflection v2 增强链路：
  - evidence signals / outcome evaluation / review queue aggregation
  - strategy card / reflective memory / long-term memory bridge
  - periodic goal reflection 最小调度入口
  - prompt / workflow proposal records
  - sandbox / replay-eval / approval / evaluation read API
- rollout / rollback v1，覆盖 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan`
  - rollout overlay 进入 chat / planner / task runtime

## 仍需继续增强

- 更丰富的 Prompt Optimization / Workflow Optimization 输出
- 更细粒度的 session signal / hint signal 证据抽取
- reflection / curator evidence -> skill proposal / sandbox 的最小闭环已落地，后续重点转向更广覆盖的自动治理与更丰富 proposal 生成
- 更完整的 review queue / priority / dedupe 聚合治理
- outcome -> skill proposal / sandbox 的更深闭环仍需继续增强，但 patch request auto realization / sandbox / guarded auto staging v1 已落地
- bundle / global rollout 治理
- auto promote / auto rollback
- periodic goal reflection 的更重后台调度形态

---

# Phase 5：Skill Evolution

## 当前状态

- 最小治理闭环已部分落地，但还不是完整动态技能系统
- `skill_package` proposal 已进入 sandbox / evaluation / approval / artifact lifecycle 主链路
- `SkillArtifact`、`SkillUsageEvent`、`SkillCuratorRecommendation` 和 `SkillCuratorJob` MVP 已落地
- `patch_needed` recommendation accept 已可创建 reference-only `skill_patch_request` proposal，并继续走 sandbox / evaluation / approval
- approved / effective `skill_patch_request` 已可 realization 为 replacement `skill_package` proposal
- `reflection_skill_evolution_curator` 已落地，可自动变现 approved / effective `skill_patch_request`、自动入沙箱低/中风险 replacement proposal、自动 reject failed / ineffective / inconclusive 候选，并在配置开启时对受信 replacement proposal 做 guarded auto staging
- `merge_candidate` recommendation accept 已可创建 merge-sourced replacement `skill_package` proposal；merge payload 复用 source artifact 的可执行基线，只合并 list-valued `match_rules`
- `SkillCuratorJob` 已可基于同 name/scope 或同 implementation binding 的 artifact overlap / duplicate detection 自动生成 `merge_candidate / none` recommendation；只产 recommendation，不直接修改 artifact
- `SkillCuratorJob` 已接入 memory conflict summary、reflection outcome evaluation 和 resolver health trend 作为 `governance_evidence`，可生成或增强 `flag_for_review / none` recommendation；该 evidence 只进入 recommendation，不直接改 artifact
- `SkillCuratorJob` 已接入 surface / topic coverage regression 输入，可基于声明外 topic demand 与 governed binding gap 生成 `patch_needed / none` recommendation，并复用既有 patch proposal 治理路径
- skill observability 已接入 Prometheus / Grafana / alert 基线，可观测 skill usage、resolver failure、artifact status、curator pending backlog、recommendation rate 和 curator job p95
- approved / effective replacement `skill_package` proposal 已可通过 operator-protected staging API 或 curator guarded auto staging 生成 `staged` replacement artifact
- staged governed replacement 已接入 shared readiness evaluation、operator read API、strict source-anchor gate 和 curator ready recommendation
- staged replacement readiness API 现会直接返回 `recommended_action`，并统一暴露 source anchor / rollout / usage / threshold 摘要
- staging 不会自动 activate / replace source artifact；activate / replace 仍必须人工触发，不会自动执行
- staged replacement recommendation accept 现为 lifecycle-first：只有 lifecycle 成功后 recommendation 才会 accepted；失败时会写 `skill.curator.recommendation.accept_failed` durable audit，并保持 pending
- `tool_plan` 已支持保守 multi-step 样板：当前 `replan` 可受控执行 `partial_replan -> review_scheduling` 两步链，并把 sequence / step 摘要写回 usage、audit 和 sandbox summary
- dynamic runtime registry V1 已统一 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 的 execution-plan resolution / usage metadata sourcing，并把 artifact/binding 来源摘要写入 usage metadata
- `chat / quiz / plan_generation` 已与 task/autonomy 对齐到同一套 runtime usage metadata helper；`chat / hint / quiz / plan_generation` 的 rollout observation 已在成功路径接通，其中 `plan_generation` 只会在 plan/task 持久化成功后调度 observation
- rollout auto-governance V1 已落地独立 decision job；当前只对 `review_scheduling / assessment_generation / replan` 的 allowlisted rollout 自动执行 `promote / rollback`
- rollout auto-governance 已配置化：可通过 `AGENT_EDU_SKILL_ROLLOUT_AUTO_GOVERNANCE_ENABLED`、`AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_ENABLED`、`AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_ENABLED` 和对应 surface allowlist 环境变量控制
- skill observability 已补 rollout auto-governance 指标与告警，可观测 auto decision queued / executed / skipped、auto rollback 速率与 decision skip 速率

## 仍需继续增强

- dynamic runtime skill registry V2（更丰富的 multi-step tool-plan orchestration 与更完整的 active-artifact runtime sourcing）
- bundle / global rollout 治理
- `chat / hint / quiz / plan_generation` 仍未进入 auto-governance allowlist
- staged replacement 的 auto-activate / auto-replace 仍未实现

---

# Phase 6：Multi-Agent Society

## 增加

- Agent协作
- Agent自治
- 长期数字人格

---

# 七、推荐技术架构

# 后端

| 技术 | 用途 |
|---|---|
| FastAPI | API |
| LangGraph | Agent orchestration |
| Celery | 异步任务 |
| Redis | Queue/Cache |
| PostgreSQL | 主数据库 |
| pgvector | 向量记忆 |

---

# AI层

| 技术 | 用途 |
|---|---|
| GPT | 主推理 |
| Claude | 长上下文 |
| Qwen | 本地部署 |
| Embedding Model | 记忆检索 |

---

# Workflow层

| 技术 | 用途 |
|---|---|
| Temporal | 长流程 |
| DAG Engine | workflow |
| Async Runtime | agent任务 |

---

# 八、安全设计（极其重要）

# 必须禁止

| 危险行为 | 原因 |
|---|---|
| 修改核心规则 | 失控 |
| 自主扩权 | 风险极高 |
| 无限反思 | token爆炸 |
| 无限记忆 | memory污染 |
| 隐藏行为 | alignment失效 |

---

# 必须实现

| 安全机制 | 功能 |
|---|---|
| Sandbox | 隔离测试 |
| Audit Log | 行为记录 |
| Human Approval | 高风险审批 |
| Skill Whitelist | 技能白名单 |
| Reflection Limit | 限制递归 |

---

# 九、项目真正方向

# 不要做：

```text
AI问答机器人
```

---

# 而是做：

```text
长期成长型认知伙伴
```

---

# 最终形态

未来系统会逐渐形成：

```text
长期记忆
+
自主规划
+
技能演化
+
人格连续性
+
多Agent协作
```

最终接近：

# 数字生命体（Digital Cognitive Being）

---

# 十、核心哲学

真正高级的教育智能体：

不是：

```text
替代老师
```

而是：

# 成为人的长期认知共生体

它会：

- 帮助学习
- 帮助思考
- 帮助成长
- 帮助形成认知结构
- 长期陪伴用户演化

这就是本项目希望逐步逼近的教育智能体方向。
