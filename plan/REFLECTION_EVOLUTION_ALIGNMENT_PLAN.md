# Reflection / Evolution 对齐实施计划

## 1. 文档定位

本文档用于回答一个具体问题：

当 [plan/MEMORY_SYSTEM_REPAIR_PLAN.md](/home/cl/agent-edu/plan/MEMORY_SYSTEM_REPAIR_PLAN.md) 和 [plan/SKILL_AUTONOMY_SEQUENCE.md](/home/cl/agent-edu/plan/SKILL_AUTONOMY_SEQUENCE.md) 全部落地后，当前反思与进化系统应如何同步升级，才能保持闭环一致、治理边界一致、运行时解释性一致。

这不是一份新的顶层 roadmap，也不是把 memory / skill 两份计划拼接起来。它只关注三件事：

- 反思系统应该如何改变触发、证据、判因和动作模型
- 进化系统应该如何改变 proposal、sandbox、curator 和 rollout 治理
- 运行时 skill 自治升级后，反思和进化如何继续可解释、可审计、可回滚

本文档优先级：

1. 先保证反思/进化不会落后于 runtime 与 memory 的新抽象
2. 先守住 `proposal -> sandbox -> evaluation -> approval` 治理边界
3. 先补“主动发现问题”的能力，再扩“自动推进变更”的能力
4. 先补证据契约和 explainability，再扩自治强度
5. 默认最小扩展，不借机重写整套 reflection / evolution 子系统

---

## 2. 当前实现基线

### 2.1 已存在的真实主链路

当前系统已经存在最小可用的反思/进化闭环，不应再按“未实现”处理：

1. task / workflow 结果会触发 reflection
2. reflection 会生成 verdict、action、summary，并写入 `ReflectionRecord`
3. reflection outcome 会回写 strategy / reflective memory / long-term memory bridge
4. reflection 可生成 `prompt_optimization`、`workflow_optimization`、`skill_package`、`skill_patch_request`
5. proposal 可进入 sandbox、evaluation、approval
6. rollout 会写 `GoalSkillBinding`
7. chat / quiz / planner / task runtime 已会消费 binding / runtime directives / tool plan

关键代码入口：

- 反思触发与主流程：[reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py)
- task 状态驱动反思：[task_status_update_support.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_status_update_support.py:437)
- workflow failure 反思协调：[task_failure_reflection_coordinator.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_failure_reflection_coordinator.py:1)
- proposal 生成与治理：[reflection_proposals.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposals.py:48)
- sandbox 执行：[reflection_proposal_sandbox.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposal_sandbox.py:77)
- curator 自动推进：[reflection_skill_evolution_curator.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_skill_evolution_curator.py:89)
- rollout / binding：[reflection_proposal_rollouts.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposal_rollouts.py:105)
- 运行时 binding 解析：[goal_skill_binding_resolver.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/goal_skill_binding_resolver.py:51)

### 2.2 当前实现的主要限制

当前闭环已经存在，但它仍然是“后验修补型”，还没有与 memory 修复和 skill autonomy 升级对齐。

主要限制如下：

1. 反思 trigger 仍以 `failed/skipped/assessment/workflow error` 为主，缺少 corpus-driven proactive trigger
2. memory corpus 已参与 reflection 判因，但尚未参与 reflection 调度决策
3. root cause taxonomy 仍主要面向 learner/task 问题，不足以解释 capability routing / retrieval / template / governance failure
4. proposal payload 仍以固定 surface + 固定 skill 形态为主，尚未面向 capability / router / template
5. high-risk proposal 目前不能自动进入更严格 sandbox，和 skill autonomy 目标不一致
6. runtime skill 选择仍是 first-match binding，不是多候选 ranking，因此 reflection 也缺少“候选比较失败”证据
7. explainability 主要解释“最后用了什么”，不能解释“为什么没选别的候选”

---

## 3. 设计目标

当 memory 修复和 skill autonomy 两份计划落地后，reflection / evolution 子系统应满足以下目标：

1. 反思可以由 memory corpus、runtime routing evidence、governance regression 主动触发，而不只靠失败结果被动触发
2. 反思证据能够覆盖 learner-side、system-side、governance-side 三类问题
3. 反思产出的 proposal 可以针对 capability routing、template policy、skill package、prompt/workflow policy 分层作用
4. high-risk change 可以自动进入受限 sandbox，但不能自动越过 activation / replace / privilege gate
5. curator 能消费 memory conflict、reflection outcome、tool-plan sequence、routing regression 等统一证据
6. runtime explain 能向 operator 展示 winner、loser、fallback chain、confidence、reason code
7. 整个闭环仍然遵守：
   - fail closed
   - bounded reflection
   - no direct production mutation from reflection
   - no bypass of approval / audit / rollout governance

---

## 4. 总体改造方向

### 4.1 Trigger 从 reactive 扩展到 proactive

反思触发要从当前的“结果坏了再反思”，扩展成三层模型：

1. `outcome-triggered`
   - failed
   - skipped
   - assessment regression
   - workflow runtime failure
2. `corpus-triggered`
   - contested memory backlog
   - high-priority validate/review backlog
   - stale but high-importance knowledge cluster
   - positive-strategy reinforcement opportunity
3. `runtime-governance-triggered`
   - repeated router fallback to baseline
   - low-confidence selection bursts
   - tool-plan sequence mismatch
   - rollout governance regression

结论：

- memory 修复计划完成后，reflection 不应只把 memory 当“打分因子”
- skill autonomy 完成后，reflection 不应只分析 learner/task outcome，还要分析 runtime selection failure

### 4.2 Evidence 从 task-centric 扩展到 capability-centric

当前 [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:668) 的 evidence payload 已经包含：

- task
- workflow
- plan
- recent attempts
- mastery
- goal state
- memory corpus
- session signals

后续必须再加入：

1. capability request
   - requested capability
   - surface
   - risk budget
   - tenant policy
2. routing result
   - selected artifact / candidate
   - fallback chain
   - confidence
   - loser reason codes
3. runtime plan evidence
   - template id
   - template source
   - tool plan policy version
   - required output contract
4. governance evidence
   - rollout state
   - approval origin
   - blast radius class
   - recent rollback pressure

### 4.3 Root Cause 从 learner 问题扩展到 system 问题

当前 root cause 主要有：

- `knowledge_gap`
- `difficulty_mismatch`
- `review_gap`
- `sequencing_issue`
- `engagement_constraint`
- `assessment_regression`
- `workflow_issue`

未来至少要补下面这组 system-side root cause：

- `retrieval_conflict_exposure`
- `retrieval_relevance_collapse`
- `capability_routing_miss`
- `candidate_ranking_regression`
- `template_policy_miss`
- `tool_plan_contract_break`
- `governance_blocked_improvement`
- `rollout_regression`

否则 skill autonomy 升级后的问题会被错误压扁成 learner 问题，导致：

- replan 代替 routing repair
- prompt patch 代替 capability repair
- memory reinforce 代替 governance fix

### 4.4 Proposal 从 skill-centric 扩展到 capability/router/template 分层

当前 proposal 模型已支持：

- `prompt_optimization`
- `workflow_optimization`
- `skill_package`
- `skill_patch_request`

这套模型还可继续保留，但需要扩展表达层，而不是强行另起炉灶。

建议分层如下：

1. `prompt_optimization`
   - 面向 chat / hint / quiz instruction bias
2. `workflow_optimization`
   - 面向 plan / review / assessment / replan policy
3. `capability_routing_patch`
   - 面向 router 权重、fallback policy、trust rule、candidate filter
4. `tool_template_patch`
   - 面向 plan template / sequence contract / allowed template choice
5. `skill_package`
   - 面向 artifact 级能力包调整
6. `skill_patch_request`
   - 继续作为 curator / operator 之间的 governed bridge

如果当前阶段不想扩 proposal type，也至少要在 `skill_package` / `workflow_optimization` payload 里容纳：

- capability scope
- router policy delta
- template policy delta
- candidate gating reason

### 4.5 Governance 从单一 proposal gate 扩展到分层 gate

`SKILL_AUTONOMY_SEQUENCE` 明确要求拆开：

- sandbox admission
- evaluation
- stage
- activate
- replace
- broaden scope
- privilege change

当前实现里：

- low / medium risk 可 auto sandbox
- high risk 通常停在 manual sandbox review
- auto stage 仅对受信来源和条件化 replacement 开放

后续需要改成：

1. high-risk 可以 auto-admit 到 stricter sandbox
2. high-risk 仍不能 auto-activate / auto-replace
3. privilege broaden / scope broaden 必须永远显式治理
4. sandbox policy 与 activation policy 必须分别审计、分别解释

---

## 5. 分阶段实施计划

## Phase 1: 让 Reflection Trigger 真正消费 Memory 与 Runtime 信号

### 5.1 目标

把 reflection trigger 从 outcome-only 扩展成：

- outcome-triggered
- corpus-triggered
- runtime-governance-triggered

### 5.2 代码范围

- [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py)
- [task_status_update_support.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_status_update_support.py)
- [task_autonomy_scheduling.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py)
- 可能新增：
  - `reflection_trigger_policy.py`

### 5.3 实施步骤

1. 提取 `ReflectionTriggerPolicy`
   - 输入 goal/task/runtime/memory summary
   - 输出是否触发、scope、trigger_source、cooldown key、reason codes
2. 把当前硬编码 trigger 条件从 task 状态更新逻辑中抽离
3. 接入 memory corpus signal
   - contested high-severity
   - validate/review backlog
   - reinforce opportunity
4. 接入 runtime routing signal
   - fallback-to-baseline burst
   - low-confidence burst
   - repeated sequence mismatch
5. 做 topic / goal / source 级 cooldown 与 dedupe

### 5.4 设计约束

- 不允许 reflection spam
- 不允许 corpus signal 直接执行高风险动作
- 不允许 routing 异常直接改生产 binding
- trigger denial 必须可审计或可观测

### 5.5 测试要求

- failure trigger 不回归
- corpus threshold 达标时可触发 bounded reflection
- runtime regression 达标时可触发 bounded reflection
- cooldown / dedupe 生效
- noisy success path 不会 flood

### 5.6 验收标准

- 反思可在 learner-facing failure 前捕获部分系统性风险
- periodic reflection 不再只是 `plan_replanned` 占位调用
- 触发量受控且有明确 reason code

---

## Phase 2: 扩展 Reflection Evidence Contract

### 6.1 目标

让 reflection evidence 能解释“为什么能力选择错了”，而不只是“任务结果不好”。

### 6.2 代码范围

- [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:668)
- future runtime abstractions from `SKILL_AUTONOMY_SEQUENCE`
- 可能新增：
  - `reflection_evidence_contracts.py`

### 6.3 实施步骤

1. 为 runtime 新增 evidence payload 规范：
   - `capability_request`
   - `capability_selection`
   - `candidate_summary`
   - `template_summary`
2. 将下列 runtime 证据接入 reflection payload：
   - winner artifact
   - fallback chain
   - loser reason codes
   - confidence
   - template id
   - template source
   - sequence contract version
3. 将 rollout / governance 信息接入 payload：
   - rollout status
   - staged vs rolled_out
   - approved_by origin
   - recent observation recommendation
4. 保持 payload schema 稳定，避免继续扩散 ad hoc dict

### 6.4 设计约束

- 不把内部敏感治理细节暴露到 learner-facing surface
- 不把未验证模型解释直接当证据事实
- evidence schema 必须向后兼容旧 reflection record

### 6.5 测试要求

- 旧 trigger 仍能构建 payload
- 新 runtime path 构建的 payload 字段完整
- 缺失 runtime evidence 时 fail closed / degrade 明确

### 6.6 验收标准

- operator 可从 reflection detail 中区分 learner-side 与 system-side failure
- routing/template failure 不再只能落到“workflow_issue”

---

## Phase 3: 升级 Root Cause 与 Action Taxonomy

### 7.1 目标

让反思结果能产生正确的后续动作，而不是一律回到 replan。

### 7.2 代码范围

- [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:714)
- [reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py:806)
- [reflection_governance.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_governance.py)

### 7.3 实施步骤

1. 将 root cause 分成两层：
   - learner/task causes
   - runtime/governance causes
2. 为新 root cause 定义新 action：
   - `enqueue_router_review`
   - `enqueue_template_review`
   - `enqueue_memory_governance_review`
   - `enqueue_sandbox_admission_review`
3. 将原本高风险一律 `blocked` 的行为细分：
   - 可 auto sandbox 的
   - 必须 manual activation 的
   - 只能做 operator review 的
4. 为每种 action 明确：
   - approval requirement
   - idempotency key
   - audit event

### 7.4 设计约束

- reflection 仍不能直接修改 production runtime behavior
- reflection action 仍然只能调度 governed job / proposal path
- 新 action 不能绕开现有 artifact lifecycle

### 7.5 测试要求

- 同一 evidence 在不同 root cause 下动作不同
- governance-side issue 不会再误触发 learner replan
- blocked / review / executed 三种状态都可验证

### 7.6 验收标准

- 反思动作和真实问题层级一致
- system-side 问题不会继续被 learner-plan 动作错误吞掉

---

## Phase 4: 扩展 Proposal 与 Sandbox 治理模型

### 8.1 目标

让 evolution 能承接 capability routing 与 template policy 的治理对象，并允许 high-risk auto sandbox。

### 8.2 代码范围

- [reflection_proposals.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposals.py)
- [reflection_proposal_sandbox.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposal_sandbox.py)
- [reflection_replay.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_replay.py)
- domain proposal entities / schemas

### 8.3 实施步骤

1. 扩 proposal 表达层
   - 新 proposal type，或扩展现有 payload contract
2. 将 replay / sandbox baseline 与 candidate snapshot 扩展到：
   - routing policy
   - template policy
   - trust / fallback / ranking policy
3. 拆分 sandbox admission policy 与 activation policy
4. 引入 stricter sandbox profile：
   - high-risk candidate 可 auto-admit
   - 资源更小
   - evidence 要求更高
   - summary 更详细
5. 确保 high-risk 仍不能 auto-activate / auto-replace

### 8.4 设计约束

- 不允许用 high-risk auto sandbox 为自动上线开后门
- sandbox / approval / rollout 的 reason code 必须分开
- replay contract 不能只依赖硬编码 score delta

### 8.5 测试要求

- 新 proposal payload 校验通过
- high-risk proposal 可 auto-admit sandbox
- high-risk proposal 仍卡在 activate / replace gate
- sandbox fail / inconclusive / effective 路径覆盖

### 8.6 验收标准

- evolution 能治理 router/template 级问题
- governance 分层更清楚，不再把“不能 auto activate”误写成“不能 auto sandbox”

---

## Phase 5: 让 Curator 消费统一治理证据并推进受限自治

### 9.1 目标

把 curator 从“围绕 artifact 使用结果建议修补”，升级成“消费统一治理证据后推进受限演化”。

### 9.2 当前基础

当前 curator 已经能消费：

- memory conflict summary
- reflection outcome evaluation
- tool-plan sequence evidence

相关代码：

- [skill/curator_job.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/skill/curator_job.py:553)

### 9.3 实施步骤

1. 在 curator evidence 中加入：
   - routing regression
   - fallback pressure
   - low-confidence selection burst
   - retrieval conflict exposure
2. 将 recommendation 从 artifact-only 扩展到：
   - patch capability routing policy
   - patch template policy
   - patch/select replacement skill package
3. 保留高风险动作的人工 gate：
   - activate
   - replace selectable
   - broaden scope
   - privilege broaden
4. 将 recommendation -> proposal 自动转化路径统一化
5. 对自动推进失败增加挂起原因码与可恢复策略

### 9.4 设计约束

- curator 不能直接写 active binding
- curator 不能绕过 approval evidence
- curator 不能把 memory conflict 当作 artifact truth 自动修补

### 9.5 测试要求

- governance regression 能生成正确 recommendation
- patch / merge / routing / template recommendation 路径可区分
- 自动推进失败后进入 suspended / review，而不是 silent no-op

### 9.6 验收标准

- curator 能基于统一证据做更准确的 evolution 编排
- recommendation 不再局限于“artifact 本身坏了”

---

## Phase 6: 补齐 Runtime Explainability 与 Observability

### 10.1 目标

让 operator 能看见：

- 为什么选了这个 candidate
- 为什么没选别的 candidate
- 哪个 rollout / binding 在施加影响
- 哪类记忆 / 反思 / evolution 信号正在推高风险

### 10.2 代码范围

- runtime registry / router explain path
- reflection detail schema
- skill usage metadata
- rollout observation / metrics

### 10.3 实施步骤

1. 扩 usage metadata：
   - winner candidate
   - loser reason summary
   - confidence
   - fallback chain
   - template id
2. 扩 reflection detail：
   - routing evidence
   - template evidence
   - governance evidence
3. 扩 curator / rollout observability：
   - routing regression counts
   - low-confidence burst counts
   - corpus-trigger reflection counts
   - high-risk auto-sandbox counts
4. 给 operator surface 提供 drill-down 所需最小字段

### 10.4 设计约束

- 不把敏感 prompt / governance internals 泄露给 learner-facing API
- 不记录不必要的原始模型输出
- explainability 只陈述证据与决策，不伪造确定性解释

### 10.5 测试要求

- usage metadata 向后兼容
- runtime explain 字段在无 binding / 无 candidate 时也有 degrade path
- observability event 与 audit event 不冲突

### 10.6 验收标准

- runtime explain 可以展示 winner / loser / fallback chain
- reflection/evolution/operator 三侧看到的是同一套事实骨架

---

## 6. 推荐落地顺序

推荐顺序不是按子系统归属，而是按依赖关系：

1. 先做 Phase 1
   - 否则 memory repair 落地后，reflection 仍然只是被动系统
2. 再做 Phase 2
   - 否则 skill autonomy 落地后，reflection 看不懂 runtime failure
3. 再做 Phase 3
   - 否则 action 层仍会误把 system issue 变成 learner replan
4. 再做 Phase 4
   - 否则 evolution 无法治理新的 runtime 对象
5. 再做 Phase 5
   - 否则 curator 仍然停留在旧证据模型
6. 最后做 Phase 6
   - 把 explainability、observability、operator drill-down 收口

---

## 7. 非目标与边界

本计划不做：

1. 不重写整个 reflection record schema 为全新系统
2. 不绕开现有 proposal / sandbox / approval / rollout 治理链
3. 不让 reflection 直接改 active runtime behavior
4. 不让 curator 获得未审批的 privilege broaden 能力
5. 不在本轮开放任意 DAG tool orchestration
6. 不在本轮开放外部 skill 下载即启用

---

## 8. 完成标准

本计划完成后，系统应达到以下状态：

1. memory 修复不再只提升 retrieval，而是真正提升 proactive reflection
2. skill autonomy 不再只是 runtime 自治，reflection / evolution 也能理解并治理其失败模式
3. high-risk 变更可以更早进入 sandbox，但仍不能绕过 activation / replace gate
4. curator 能基于 memory、reflection、routing、template、rollout 统一证据推进受限演化
5. operator 能解释一次 runtime 失败究竟是 learner issue、memory issue、routing issue、template issue 还是 governance issue

如果这些条件达不到，那么 memory repair 和 skill autonomy 即使分别落地，整个系统仍然会停留在“局部增强、全局断裂”的状态。
