# 长期记忆 / 反思进化 / Skills 路线图

## 文档定位

这份文档说明后续三个核心系统应该怎么协同演进：

1. 长期记忆
2. 反思进化
3. Skills 生命周期

它不是阶段进度表，而是后续实现流程与边界定义。

当前实现状态可参考：

- [docs/PROGRESS_STATUS.md](./PROGRESS_STATUS.md)
- [docs/IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)

---

## 结论先行

当前这三层的正确顺序是：

```text
运行行为
-> 长期记忆治理
-> 反思判断
-> Skill 候选生成
-> sandbox / replay / approval
-> rollout / binding
-> usage tracking
-> curator 维护
```

其中：

- 长期记忆负责“记录发生了什么、什么重复出现、什么有效/无效”
- 反思负责“该不该改、改什么、风险多大”
- Skills 负责“把稳定可复用的能力真正装进运行时”

反思不能直接改 skill 库。
Skills 不能靠单次成功直接晋升。
长期记忆也不能被当成 skill 存储层。

---

## 当前基线

### 1. 长期记忆

当前长期记忆已经够用，重点不在继续扩实体，而在治理和证据质量。

已具备：

- `candidate / active / stable / compressed / archived / suppressed`
- `memory_conflict_sets / memory_conflict_members`
- `memory_maintenance_jobs`
- `MemoryNormalizer`
- `long_term_memory.materialization.failed`
- Prometheus / Grafana / alert 基线

它现在的职责应该收敛为：

- 提供 evidence
- 提供 pattern
- 提供 provenance
- 提供 operator review 入口

### 2. 反思进化

当前反思系统已经不是空壳，而是一个受控 proposal 系统：

- `ReflectionRecord`
- `ReflectionAction`
- `ReflectionProposal`
- `ReflectionProposalSandboxRun`
- `ReflectionProposalRollout`
- `GoalSkillBinding`

但它现在的主要问题是：

- 还没有真正的 skill 生命周期
- 反思产物更多是 goal-scoped runtime overlay
- 还没有独立的 skill usage 记账

### 3. Skills 系统

当前 skills 系统仍是固定白名单：

- `explain_concept`
- `create_quiz`
- `adaptive_hint`
- `plan_study_path`
- `schedule_review`

它还不是动态技能库，只是一个受限执行目录。

---

## 三层职责边界

| 系统 | 主要职责 | 输出 | 禁止事项 |
|---|---|---|---|
| 长期记忆 | 记录和整理证据 | candidate、conflict、provenance、usage context | 直接生成可执行 skill |
| 反思进化 | 判断是否需要改变行为 | reflection record、proposal、sandbox、rollout 建议 | 直接修改 registry |
| Skills | 执行可复用能力 | versioned skill artifact、binding、usage event | 靠单次成功直接晋升 |

---

## 运行流程

### 标准主链路

```text
session / task / workflow 运行
-> memory event / task attempt / reflection evidence
-> 长期记忆 materialization
-> 反思触发
-> proposal 生成
-> sandbox / replay / evaluation
-> approval
-> rollout / binding
-> 运行时使用
-> usage event 记录
-> curator 定期审查
-> promote / patch / merge / archive
```

### 这个流程里每一步的含义

1. **memory event**
   - 只负责把事实记下来
   - 不负责决定新 skill

2. **reflection**
   - 把事实压缩成问题
   - 给出改动方向
   - 生成 proposal 候选

3. **sandbox / replay**
   - 验证 proposal 是否真有收益
   - 阻止偶然有效的内容直接进生产

4. **rollout / binding**
   - 把通过验证的能力放到 goal / surface 级运行时
   - 先局部生效，不要全局扩散

5. **usage tracking**
   - 记录技能是否真的被调用
   - 记录调用后结果好不好

6. **curator**
   - 依据 usage 和 outcome 做周期性整理
   - 输出 promote / patch / merge / archive 建议

---

## 后续应该怎么做

### 一、长期记忆后续怎么做

长期记忆后续不应再追求“更多种类”，而应追求“更好证据”。

建议重点是：

- 提高 evidence 质量
- 提高 provenance 完整性
- 提高 conflict 解释质量
- 提高 operator review 的可读性
- 扩充长期回归集
- 稳定长期阈值和告警通知

长期记忆在这里扮演的是：

> 事实仓库 + 证据仓库 + 质量筛选器

它不是技能仓库。

### 二、反思进化后续怎么做

反思系统后续要从“生成 proposal”升级为“管理改动生命周期”。

建议补齐四件事：

1. **明确触发信号**
   - 失败
   - 连续失败
   - 低质量成功
   - 重复模式
   - skill usage 退化

2. **明确 proposal 类型**
   - prompt 级改动
   - workflow 级改动
   - skill package 候选
   - rollback 建议

3. **明确验证方式**
   - rule replay
   - archived replay
   - sandbox run
   - operator approval

4. **明确闭环**
   - 反思产生 proposal
   - proposal 经验证后进入 rollout
   - rollout 产生 usage
   - usage 再反馈给反思

反思系统的目标不是“自动变强”，而是：

> 把不稳定经验变成可验证改动，再把改动变成可审计资产。

### 三、Skills 系统后续怎么做

Skills 系统后续必须从“固定白名单”走向“版本化技能资产”。

建议新增三类核心对象：

#### 1. `SkillArtifact`

表示一个可复用、可版本化、可回滚的技能资产。

应包含：

- `name`
- `version`
- `skill_type`
- `scope`
- `status`
- `definition`
- `runtime_directives`
- `tool_plan`
- `source_reflection_ids`
- `source_memory_ids`
- `quality_score`

#### 2. `SkillUsageEvent`

表示技能在真实运行中的使用记录。

应包含：

- `skill_artifact_id`
- `learner_profile_id`
- `learner_goal_id`
- `surface`
- `topic_key`
- `outcome_status`
- `latency`
- `cost`
- `created_at`

没有 usage，就没有 curator。
没有 usage，skill 也无法判断是否该保留。

#### 3. `SkillCuratorJob`

表示后台维护器对技能库做周期性整理。

职责是：

- promote
- patch
- merge
- archive
- flag for review

它只能输出建议或新 proposal，不能直接越过审批修改生产 skill。

---

## 推荐状态机

### SkillArtifact 状态

```text
candidate
-> staged
-> active
-> deprecated
-> archived
```

### 迁移规则

- `candidate -> staged`
  - 需要 repeated evidence
  - 需要 sandbox / replay 通过

- `staged -> active`
  - 需要 approval
  - 需要 rollout 稳定
  - 需要 usage 证据

- `active -> deprecated`
  - 使用率下降
  - 或者有更优替代
  - 或者回滚率过高

- `deprecated -> archived`
  - 长期低使用
  - 仅保留历史可追踪性

---

## 实现顺序

### 第 1 步：补 skill usage

先做使用记录，不要先做自动生成。

需要把下面这些调用都记下来：

- chat
- hint
- quiz
- planner
- review scheduling
- replan

### 第 2 步：引入 skill artifact

把 `skill_package` 从“goal-scoped binding 方案”升级为真正的版本化 skill 候选。

### 第 3 步：让 reflection 产出 skill candidate

只有满足以下条件才可以进入 skill candidate：

- 重复出现
- sandbox 通过
- replay 有收益
- 可解释
- 可回滚

### 第 4 步：补 curator job

curator 只做周期性审查，不做即时决策。

它依据：

- usage rate
- success rate
- rollback rate
- coverage
- recurrence
- overlap

输出：

- promote
- patch
- merge
- archive

### 第 5 步：把 runtime 真正接到 skill artifact

现在 runtime 主要吃的是固定白名单和 goal binding。
后续要让 runtime 读取 active skill artifact，并按 surface / topic / goal 选用。

---

## 反模式

不要做这些事：

- 单次任务成功直接创建 active skill
- 让长期记忆直接充当 skill 存储
- 让 reflection 直接修改 registry
- 让 curator 直接写生产配置
- 不做版本号就上线 skill
- 没有 usage 还硬做 promote

这些做法会把系统搞成一个不断自我污染的回路。

---

## 评判标准

一个健康的三系统闭环，应该满足：

- 长期记忆能清楚说明发生了什么
- 反思能清楚说明为什么要改
- skills 能清楚说明改动如何复用
- 每个 skill 都有 usage 证据
- 每次 promote 都有回放或 sandbox 证据
- 每次 archive 都有明确理由
- operator 可以追溯每一次变更

---

## 简短结论

后续最应该做的，不是继续膨胀长期记忆，也不是继续堆 proposal 类型，而是把这三层真正连起来：

```text
memory -> reflection -> skill artifact -> usage -> curator
```

这才是可控的自反思、自进化路径。
