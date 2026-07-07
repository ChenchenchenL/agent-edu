# Memory System 修复计划

> **状态: 已完成** — 全部 6 个 Phase 已实施并验证，9 条完成定义已全部满足。(2026-07-03)

## 1. 文档定位

本文档用于指导 `agent-edu` 当前 memory system 的修复工作，范围聚焦在“长期记忆已经能写入，但没有稳定地反哺 chat、task、reflection 决策”的真实缺口。

这不是一份泛泛而谈的 memory roadmap，也不是把 [docs/MEMORY_SYSTEM_DEFECTS.md](/home/cl/agent-edu/docs/MEMORY_SYSTEM_DEFECTS.md) 原样搬进 `plan/`。本计划基于当前代码重新核对，目标是：

- 只修仍然存在的真实缺陷
- 明确哪些文档结论已经过期
- 按影响面和风险分阶段落地
- 为每一阶段定义代码范围、测试义务、验收标准和回滚边界

本计划优先级：

1. 先修读路径断裂，再修质量优化。
2. 先保证治理边界不被绕过，再谈“更聪明的记忆”。
3. 先补真实消费链路，再补 operator 辅助视图。
4. 先补测试覆盖高风险路径，再补低风险打磨。
5. 默认最小 diff，不借机扩散重构。

---

## 2. 当前状态判断

### 2.1 已完成但未闭环

memory system 当前并不是“不可用”，而是“写入强、消费弱”。

已存在的能力：

- chat turn 可写 `MemoryEvent`，并进一步物化 long-term memory candidate
- task outcome 可物化 knowledge / behavior memory
- reflection outcome 可物化 knowledge / behavior memory
- structured extraction 有 schema 校验与 candidate-only 写入边界
- knowledge / behavior retrieval service 已存在
- memory maintenance、promotion eligibility、conflict refresh、compression 已存在 worker 化执行路径
- reflection / planner 已经开始消费 interpretation / reflection corpus

结论：

1. memory 写路径不是当前主要问题。
2. 当前最大缺口是 learner-facing chat 没把知识/行为长期记忆带回上下文。
3. 第二层缺口是 retrieval / governance 之间仍有语义断层。

### 2.2 当前仍然成立的问题

#### A. Chat 读路径没有消费 knowledge / behavior memory

当前 [chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py:197) 只检索：

- session memories
- profile memories

而 [chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py:300) 的 `long_term_context` 只由：

- `cross_session_context`
- `profile_retrieval_result.memories`

组成。

`retrieve_relevant_knowledge_memories()` 和 `retrieve_relevant_behavior_memories()` 虽然在 [memory.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/memory.py:430) 已暴露，但当前没有进入 chat runtime context。

影响：

- learner 的知识薄弱点、误解、行为偏好无法稳定进入教学回答
- long-term memory 在 learner-facing surface 上几乎不可见
- memory materialization 的收益无法闭环验证

#### B. Task outcome 只在失败/跳过时生成 behavior memory

[long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py:140) 仍然只在 `failed/skipped` 时构建 behavior memory。

影响：

- 只能记住“哪里卡住了”，记不住“什么策略有效”
- behavior memory 对 learner support pattern 的建模天然偏负面
- 后续行为检索即使被 chat 消费，也更可能偏向 failure framing

#### C. 检索阶段对 conflict / contested 语义不敏感

当前 knowledge retrieval 在 [retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py:117) 只基于：

- `status in MEMORY_RETRIEVAL_STATUSES`
- 或 knowledge candidate 有 eligibility 特例

behavior retrieval 在 [retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py:167) 只基于：

- `status in MEMORY_RETRIEVAL_STATUSES`

评分函数 [retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py:234) 不考虑：

- `validation_status`
- `contested`
- conflict severity
- recommended use

影响：

- active/stable 但处于 contested pressure 的记忆仍可能正常进入 top results
- chat 后续一旦接入 knowledge/behavior retrieval，会把冲突语义直接暴露给 learner-facing decision
- retrieval 和 governance 之间缺少最后一道安全降噪层

#### D. Reflection corpus 参与分析，但不驱动 trigger

当前 [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:995) 已经构建 interpretation + reflection corpus；[reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:779) 也会把 `recommended_action` 作为 root-cause 打分信号。

但 post-task trigger 仍然主要依赖 [task_status_update_support.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_status_update_support.py:437) 的规则：

- failed
- skipped
- consecutive failure
- assessment completed

影响：

- reflection 仍然偏 reactive
- corpus 的“reinforce / validate / refresh / review”智能没有进入调度层
- knowledge 风险只能在出事后被动反思

#### E. 检索权重与 embedding 兼容策略仍然粗糙

[retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py:243) 仍然使用硬编码权重。

[retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py:223) 在向量维度不一致时直接返回 `0.0`。

影响：

- chat / hint / planning / reflection 共用同一评分偏好，不符合多 surface 需求
- embedding provider 切换后会出现 retrieval cliff
- 没有 degrade path，只有 silent relevance collapse

#### F. Structured extraction freshness 初始值过高

[long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py:358) 和 [long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py:397) 仍把 structured extraction memory 的 `freshness_score` 直接设为 `1.0`。

影响：

- 未经时间验证的 system inference 在初始检索中被高估
- 初始排序可能挤压更稳健的 active/stable memory

### 2.3 已过期或需要改写的问题

以下内容不应继续作为修复基线：

#### A. “没有自动周期性 memory maintenance”

该结论已过期。

- worker 会在 [apps/worker/main.py](/home/cl/agent-edu/apps/worker/main.py:42) 每个 tick 执行 `run_memory_maintenance_once()`
- [memory_maintenance.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/memory_maintenance.py:123) 会自动 `seed_due_jobs()`

真正的问题不再是“有没有调度”，而是“maintenance 输出是否足够支撑 retrieval / chat / reflection 消费”。

#### B. “memory replay 没有最大重试次数”

该结论已过期。

- autonomy job 默认 `max_attempts=3`，见 [autonomy.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/domain/entities/learner/autonomy.py:154)
- replay 失败时会有限重试，见 [task_autonomy_scheduling.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py:361)

真正的问题不再是无限重试，而是 replay 失败后的 observability 与 root-cause 归因是否足够快。

#### C. “freshness decay 没有写回实体”

该结论已过期。

- knowledge refresh 会写回 decay 后的 freshness，见 [governance_batches.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/governance_batches.py:463)
- behavior refresh 也会写回，见 [governance_batches.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/governance_batches.py:530)

#### D. “interpretation / reflection corpus 没被任何流程消费”

该结论已过期。

- planner 已消费 interpretation，见 [task_plan_lifecycle.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_plan_lifecycle.py:130)
- reflection 已消费 interpretation + corpus，见 [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:995)

真正缺口是“消费深度和调度联动不足”，不是“完全没消费”。

---

## 3. 修复目标

### 3.1 目标

本计划完成后应满足：

1. chat surface 能稳定消费 governed knowledge/behavior memory。
2. knowledge/behavior retrieval 在 learner-facing path 上具备 conflict-aware ranking 或 filtering。
3. behavior memory 同时覆盖负向模式和正向有效策略。
4. reflection trigger 可以消费 corpus intelligence，而不只依赖失败计数。
5. retrieval scoring 对不同 surface 可配置，不再把 chat/hint/reflection/planning 混成一套固定权重。
6. embedding 维度不兼容时有明确 degrade contract 和补救路径。

### 3.2 非目标

本轮不做：

- 不重写整套 memory schema
- 不引入新的 memory class
- 不把 chat prompt 改成大规模自由拼接 memory dump
- 不让 candidate memory 直接绕过 governance 成为高信任事实
- 不借机重构 `chat.py` / `memory.py` 以外的无关模块

---

## 4. 分阶段实施方案

## Phase 1: 打通 Chat 读路径闭环

### 4.1 目标

让 governed long-term knowledge / behavior memory 进入 chat runtime context，并保持 fail-closed 与 bounded context。

### 4.2 代码范围

优先修改：

- [packages/agent_core/src/agent_core/application/services/chat.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/chat.py)
- 如需要，补充：
  - `packages/agent_core/src/agent_core/application/interfaces/memory.py`
  - `tests/test_chat_service.py`

### 4.3 实施步骤

1. 在 chat runtime context 构建阶段增加：
   - `retrieve_relevant_knowledge_memories()`
   - `retrieve_relevant_behavior_memories()`
2. 定义 learner-facing memory 注入 contract：
   - knowledge memory 只注入 `active/stable`，以及经过明确 eligibility gate 的少量 candidate special-case
   - behavior memory 只注入 `active/stable`
   - contested/conflict-heavy memory 默认不直接注入 learner-facing natural language context
3. 对 knowledge / behavior retrieval 单独加异常隔离：
   - retrieval failure 记录 audit / metrics
   - chat 主流程不因附加 memory retrieval 全面失败
4. 为 `long_term_context` 定义分层配额：
   - cross-session context
   - profile memory summaries
   - knowledge memory summaries
   - behavior memory summaries
5. 调整 `_build_learner_profile` 或 prompt assembly 逻辑，避免直接塞入过长原始 summary。

### 4.4 设计约束

- 不允许把 `candidate` 当作已验证事实直接注入
- 不允许注入 suppression/archived memory
- 不允许让 memory retrieval failure 破坏 chat 事务边界
- 不允许无上限扩 context

### 4.5 测试要求

至少补：

- chat 成功路径：knowledge + behavior memory 被查询并进入上下文
- retrieval 部分失败：chat 仍可回复，且有 audit/metrics
- contested / suppressed memory 不进入 learner-facing context
- context budget 生效，避免 memory flood

### 4.6 验收标准

- chat 对同一主题提问时，能稳定引用已有知识薄弱点或行为偏好
- test 覆盖 knowledge/behavior 注入与失败隔离
- 没有把 candidate 当作高信任事实直接输出的回归

---

## Phase 2: 修正 Behavior Memory 的负向偏置

### 5.1 目标

让 task outcome 不只记录 failure pattern，也能记录成功时的有效学习策略。

### 5.2 代码范围

- [packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py)
- 如需补充打分/分类：
  - `packages/agent_core/src/agent_core/application/services/memory.py`
  - `tests/test_memory_service.py`

### 5.3 实施步骤

1. 为 `completed` task 定义 behavior materialization 条件：
   - 只在有明确 learner signal 时写入
   - 不把所有完成任务都机械转成 behavior memory
2. 为正向 behavior pattern 定义最小 schema 语义：
   - 示例：偏好先看 hint 再独立完成
   - 示例：分步推导后成功
   - 示例：assessment 前复习短测有效
3. 区分负向和正向 behavior summary 文案，避免都写成 “was stuck on”
4. 校准初始 importance/confidence/freshness，避免成功样本被过度放大

### 5.4 设计约束

- 不允许把单次偶然成功直接升格成稳定偏好
- 不允许让 success-path behavior memory 绕过 recurrence/evidence gate
- 不允许污染现有失败场景的治理语义

### 5.5 测试要求

- completed task 在满足条件时可生成 behavior memory
- 普通 completed task 不会产生噪声 memory
- failed/skipped 既有行为保持不回归
- behavior evidence / recurrence 统计仍然正确

### 5.6 验收标准

- behavior memory 不再只反映 failure
- retrieval 样本可覆盖 positive pattern + negative pattern
- tests 证明 success path 不造成噪声膨胀

---

## Phase 3: 让 Retrieval 感知 Governance / Conflict

### 6.1 目标

在 learner-facing retrieval 前增加最后一道 conflict-aware ranking/filtering，避免 contested memory 以正常高分进入对话。

### 6.2 代码范围

- [packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py)
- 如需 repository 扩展：
  - `packages/agent_core/src/agent_core/infrastructure/db/repositories/memory.py`
- tests:
  - `tests/test_memory_service.py`
  - 可能补 `tests/test_chat_service.py`

### 6.3 实施步骤

1. 为 retrieval score 增加 governance-aware 调整层：
   - contested validation status penalty
   - contradiction score penalty
   - review-recommended penalty
2. 明确 learner-facing surface 与 operator browse surface 的差异：
   - operator browse 保持完整可见
   - chat/hint 走保守策略
3. 为 knowledge candidate eligible 的特例重新定义排序上限：
   - 可检索不等于可高排
4. 评估 behavior memory 是否也需要 contradiction-based penalty

### 6.4 设计约束

- 不允许在 retrieval 层偷改 memory status
- 不允许绕过既有 governance batch
- 不允许让 operator 失去观察 contested object 的能力

### 6.5 测试要求

- contested memory 排名下降或被过滤
- suppressed/archived 本就不可检索的语义不回归
- candidate eligible 仍可按既定策略有限检索
- chat surface 不会优先拿到 conflict-heavy memory

### 6.6 验收标准

- learner-facing retrieval 结果与治理语义一致
- contested memory 不再在 top results 中无差别暴露
- operator browse 不受误伤

---

## Phase 4: 让 Reflection Trigger 消费 Memory Corpus

### 7.1 目标

让 reflection 从“失败后反思”扩展到“基于记忆证据主动反思”。

### 7.2 代码范围

- [packages/agent_core/src/agent_core/application/services/reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py)
- [packages/agent_core/src/agent_core/application/services/task_status_update_support.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_status_update_support.py)
- 如需要调度协同：
  - `packages/agent_core/src/agent_core/application/services/task.py`
  - `tests/test_reflection_service.py`
  - `tests/test_task_service.py`

### 7.3 实施步骤

1. 定义 corpus-driven trigger policy：
   - `review` item 过多时触发 goal-level reflection
   - `validate`/`reinforce` 持续积压时触发轻量 review/reflection
   - 高 priority contested item 触发 bounded reflection
2. 把 corpus 信号接入 trigger decision，而不是直接自动执行高风险动作
3. 做去重与频率限制：
   - topic 级 cooldown
   - goal 级 dedupe
4. 明确哪些 corpus signal 只做 observability，不做 trigger

### 7.4 设计约束

- 不允许形成 reflection spam
- 不允许绕过现有 `proposal -> sandbox -> evaluation -> approval`
- 不允许把 corpus recommendation 直接当 action 执行

### 7.5 测试要求

- corpus signal 满足阈值时触发 reflection
- cooldown / dedupe 生效
- 普通成功路径不会引发大量噪声 reflection
- trigger denial / no-op 行为可验证

### 7.6 验收标准

- reflection 能在 failure 前介入部分高风险知识点
- 触发量受控，没有 worker flood
- tests 覆盖 dedupe、cooldown、denied path

---

## Phase 5: Retrieval Scoring 与 Embedding 兼容性治理

### 8.1 目标

把 retrieval 从固定硬编码策略提升为可按 surface 调整，并为 embedding migration 提供明确降级行为。

### 8.2 代码范围

- [packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py)
- [packages/agent_core/src/agent_core/infrastructure/config/settings.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/infrastructure/config/settings.py)
- 可能涉及依赖注入：
  - `packages/agent_core/src/agent_core/api/dependencies.py`

### 8.3 实施步骤

1. 把 retrieval weight 从硬编码抽成配置或 profile：
   - chat
   - hint
   - planning
   - reflection
2. 增加 embedding dimension mismatch 观测：
   - metrics
   - durable audit 或结构化日志
3. 定义 mismatch degrade contract：
   - 返回空结果并显式打点
   - 或回退到 freshness/importance-only ranking
4. 为后续 backfill 预留 migration contract，但本阶段不强制做全量重嵌入

### 8.4 设计约束

- 不允许因为加配置把 retrieval service 变成无约束策略引擎
- 不允许在默认路径依赖 live embedding migration
- 不允许静默吞掉 dimension mismatch

### 8.5 测试要求

- 不同 surface 使用不同 weight profile
- 维度不一致时有明确且可观测的降级结果
- 默认 profile 不改变现有非相关路径行为

### 8.6 验收标准

- retrieval scoring 可按 surface 调整
- embedding 切换不再表现为 silent zero-relevance failure

---

## Phase 6: Structured Extraction 初始新鲜度校正

### 9.1 目标

降低 system inference 初始 freshness 过高导致的排序放大。

### 9.2 代码范围

- [packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py)
- `tests/test_memory_service.py`

### 9.3 实施步骤

1. 把 structured extraction 的初始 `freshness_score` 从 `1.0` 降到保守默认值
2. 如有必要，区分：
   - knowledge extraction
   - behavior extraction
3. 校验对 promotion / retrieval 的连带影响

### 9.4 测试要求

- structured extraction memory 初始 freshness 降低
- candidate-only governance contract 不回归
- retrieval 排序不会被新 inference 过度支配

### 9.5 验收标准

- structured extraction 在初期更像“待验证信号”，而不是“满新鲜度事实”

---

## 5. 建议实施顺序

建议按以下顺序落地：

1. Phase 1
2. Phase 3
3. Phase 2
4. Phase 4
5. Phase 5
6. Phase 6

原因：

- Phase 1 直接修 learner-facing 主缺口，收益最大。
- Phase 3 必须在 chat 接入前后尽快补上，否则会把 contested memory 直接带进回答。
- Phase 2 能提升 behavior memory 质量，但前提是消费路径先存在。
- Phase 4 是调度增强，风险高于 Phase 1-3。
- Phase 5、6 属于质量和演进能力增强，可后置。

---

## 6. 详细测试计划

### 6.1 单元 / 集成测试新增重点

必须新增或扩展：

- `tests/test_chat_service.py`
  - knowledge/behavior memory 注入
  - retrieval failure isolation
  - context budget
  - contested filtering
- `tests/test_memory_service.py`
  - success-path behavior materialization
  - retrieval ranking with governance penalty
  - structured extraction freshness defaults
  - dimension mismatch degradation
- `tests/test_reflection_service.py`
  - corpus-driven trigger
  - dedupe/cooldown
- `tests/test_task_service.py`
  - post-task reflection trigger integration

### 6.2 必测场景

- success path
- partial retrieval failure
- permission/governance denied path
- duplicate / repeated trigger path
- contested memory present
- candidate eligible present
- embedding dimension mismatch
- positive behavior evidence
- reflection cooldown / dedupe

### 6.3 验证命令建议

至少运行与变更相关的子集：

```bash
pytest tests/test_chat_service.py
pytest tests/test_memory_service.py
pytest tests/test_reflection_service.py
pytest tests/test_task_service.py
```

如果 Phase 1-4 同时改动，建议再跑：

```bash
pytest tests/test_worker_runtime.py
pytest tests/test_memory_maintenance_service.py
```

---

## 7. 风险与控制

### 7.1 Chat 上下文膨胀

风险：

- knowledge/behavior memory 接入后 prompt 变长
- 回答质量可能因噪声下降

控制：

- 分层 quota
- surface-specific limit
- summary-only injection

### 7.2 Contested memory 泄漏到 learner-facing 回答

风险：

- chat 可能把有冲突的知识当事实说给 learner

控制：

- retrieval penalty/filter
- learner-facing prompt contract 不直接暴露 contested item
- tests 覆盖 conflict-heavy cases

### 7.3 Reflection 触发风暴

风险：

- corpus-driven trigger 引入后产生 worker flood

控制：

- cooldown
- dedupe key
- per-goal / per-topic rate cap

### 7.4 正向 behavior memory 噪声过多

风险：

- 所有 completed task 都产生命中率很低的 behavior memory

控制：

- 只有高信号 completed case 才物化
- recurrence gate 保守

---

## 8. 完成定义

本计划可视为完成，需要同时满足：

1. chat 已消费 governed knowledge/behavior memory。
2. learner-facing retrieval 对 contested/conflict-heavy memory 有保守处理。
3. success-path behavior memory 有受控写入能力。
4. reflection trigger 已开始消费 corpus signal，且有去重/冷却。
5. retrieval weight 可按 surface 调整。
6. embedding dimension mismatch 有可观测降级。
7. structured extraction freshness 默认值已保守化。
8. 相关测试通过。
9. 没有引入新的 governance bypass、隐式 commit 或 unbounded retrieval。

---

## 9. 推荐的第一批执行项

如果只做一批最有价值的修复，建议只包含：

1. Phase 1: chat 接入 knowledge/behavior retrieval
2. Phase 3: contested/conflict-aware retrieval penalty
3. Phase 2: success-path behavior memory 最小闭环

这三项一起完成后，memory system 才算从“能写入”进入“能被 learner-facing agent 安全消费”的状态。
