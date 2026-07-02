# Reflection Outcome 到 Skill Evolution 闭环质量执行计划

## 1. 文档定位

本文档用于指导 `agent-edu` 当前 `reflection outcome -> proposal / curator evidence -> sandbox / evaluation / approval -> staged replacement / recommendation` 这条闭环的质量收口。

目标不是重写整套 reflection system，也不是提前完成完整动态 skill runtime，而是在保持现有 MVP 治理路径、artifact lifecycle、worker 语义和 operator review 语义兼容的前提下，把这条已经“最小可运行”的链路固化成：

- 可解释
- 可回归
- 可审计
- fail-closed
- 不易因后续 `skills.py` / `task.py` 拆分而漂移

本文档只负责闭环质量。

结构拆分与服务边界收口分别以以下文档为主：

- [plan/SKILLS_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/SKILLS_PY_SPLIT_PLAN.md)
- [plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md](/home/cl/agent-edu/plan/TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md)

三者关系：

- 先按本文档固化 `reflection outcome -> skill evolution` 的质量 contract 和 regression baseline。
- 再按 `SKILLS_PY_SPLIT_PLAN.md` 逐步拆出 curator / recommendation / readiness / lifecycle。
- autonomy job handler 与 legacy callback 的边界清理，按 `TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md` 推进，不在本计划中重新定义 transaction owner。

优先级：

1. 不绕过 `proposal -> sandbox -> evaluation -> approval` 治理路径。
2. 不让低质量 reflection outcome 直接推动 governed artifact 状态变更。
3. 不让 curator / auto-stage 因证据缺口、状态漂移或失败恢复不完整而误提权。
4. 不让 provenance、evidence snapshot 和 durable audit 在多服务协作中静默漂移。
5. 默认回归路径不依赖真实外部 provider。

## 2. 当前状态判断

当前代码已经具备一条最小但真实存在的闭环，不是“未来设计图”。

已落地事实：

- [packages/agent_core/src/agent_core/application/services/reflection_outcomes.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_outcomes.py) 已能对 `ReflectionRecord` 建立 outcome tracking，并基于 follow-up task attempt 计算 `effective / ineffective / inconclusive / pending`。
- [packages/agent_core/src/agent_core/application/services/reflection.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection.py) 的 `apply_outcome_feedback()` 已会：
  - 刷新 reflection priority/status
  - 更新 strategy card
  - 推进 reflective memory candidate
  - bridge reflection outcome 到 memory
  - 触发 long-term memory materialization
  - 对已有 proposal 做 replay-eval review
  - 在条件满足时创建 reflection-sourced `skill_package` proposal
- [packages/agent_core/src/agent_core/application/services/reflection_proposals.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_proposals.py) 已支持：
  - `create_skill_packages_from_reflection()`
  - `create_skill_patch_request_from_recommendation()`
  - approved / effective `skill_patch_request` realization 为 replacement `skill_package` proposal
- [packages/agent_core/src/agent_core/application/services/reflection_skill_evolution_curator.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/reflection_skill_evolution_curator.py) 已支持：
  - 自动变现 approved / effective patch request
  - 自动把低/中风险 replacement proposal 入 sandbox
  - 自动 reject failed / ineffective / inconclusive / negative-score 候选
  - 对受信 replacement 来源执行 guarded auto staging
- [packages/agent_core/src/agent_core/application/services/skills.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/skills.py) 中的 `SkillCuratorJob` 已能把 reflection outcome evaluation 作为 `governance_evidence` 输入 recommendation。
- [packages/agent_core/src/agent_core/application/services/task.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/task.py) 已能通过 autonomy job 触发 `reflection_skill_evolution_curator`。

已有测试并不弱，已经覆盖了这些点：

- reflection outcome evaluation 的基本分支。
- `apply_outcome_feedback()` 对 audit / memory / proposal replay 的主路径。
- reflection-sourced `skill_package` proposal 创建。
- `skill_patch_request` realization。
- curator auto realization / sandbox enqueue / auto stage / reject / suspend。
- task autonomy job dispatch 到 `reflection_skill_evolution_curator`。

但“有链路”不等于“质量收口”。

当前仍存在的关键问题：

1. reflection outcome 的质量 contract 过于隐含，目前仍主要藏在 `ReflectionOutcomeService.evaluate()` 的启发式分支里。
2. `apply_outcome_feedback()` 是多下游扇出点，memory、proposal replay、proposal creation 的失败保护和证据一致性缺少一套统一 regression baseline。
3. reflection-sourced proposal、curator recommendation-sourced patch request、realized replacement proposal 的 provenance 字段分布在多个 service 中，容易漂移。
4. low-quality / duplicate / low-evidence reflection 到 skill artifact 治理路径的“止损点”还没有形成统一矩阵。
5. curator job 消费 reflection outcome 作为 `governance_evidence`，但“何时只做 recommendation、何时允许继续走 staging”仍分散在多个服务规则中。
6. 当前 worker 路径仍部分依赖 legacy task core 边界，若后续在 `task.py` 和 `skills.py` 继续叠逻辑，回归面会继续放大。

## 3. 目标与非目标

### 3.1 目标

本次闭环质量收口应达成：

1. 把 reflection outcome 的状态、阈值、reason note 和 evidence contract 变成可显式回归的后端规则。
2. 固化 `reflection outcome -> proposal / recommendation / staging` 的 fail-closed 边界。
3. 为 reflection-sourced proposal 与 curator governance evidence 建立稳定的 provenance / evidence snapshot contract。
4. 提供一组端到端闭环 fixtures，覆盖 `effective / ineffective / inconclusive / duplicate / rate-limited / missing-evidence` 代表场景。
5. 让 operator、worker、audit、tests 对“为什么推进/为什么阻断”给出一致答案。

### 3.2 非目标

本次不应做：

- 不新增新的 reflection 或 proposal status。
- 不改变现有 proposal type、artifact lifecycle status、audit event type 名称。
- 不把 reflection outcome 直接接到 runtime auto activate / auto replace。
- 不让 auto stage 扩展为自动 activate / replace。
- 不在本计划中完成 `skills.py` 的全量结构拆分。
- 不引入真实 provider 作为默认验证路径。
- 不把 bundle / global rollout 拉进当前闭环范围。

## 4. 闭环定义与关键边界

### 4.1 当前闭环定义

当前应被视为“闭环质量对象”的链路是：

1. `ReflectionRecord` 建立 outcome tracking。
2. `ReflectionOutcomeService` 评估 outcome。
3. `ReflectionService.apply_outcome_feedback()` 应用 outcome。
4. outcome 影响：
   - reflection record 聚合状态
   - strategy card
   - reflective memory / long-term memory bridge
   - proposal replay review
   - reflection-sourced `skill_package` proposal 创建
5. curator / proposal service / staging service 再把受控 proposal 推入：
   - sandbox
   - evaluation
   - approval
   - staged replacement
   - curator recommendation / operator review

这条链路的“闭环”不是自动激活 artifact，而是：

- reflection outcome 能进入受控治理系统；
- 低质量输入会被阻断在合适位置；
- 高质量输入能形成可审计、可复查的 governed candidate；
- 后续 runtime usage / rollout evidence 又能反向进入 curator recommendation。

### 4.2 信任边界

- reflection outcome 属于中低信任治理信号，不是高信任 artifact 变更命令。
- `effective` outcome 可以触发 proposal creation 或 curator evidence 强化，但不能直接修改 production runtime behavior。
- `ineffective / inconclusive / pending` outcome 默认只能作为 evidence 或阻断信号，不能自动提权。
- `SkillCuratorJob` 消费 reflection evidence 时，只能产生 recommendation，不得直接改 artifact lifecycle。

### 4.3 治理边界

- 所有 reflection-driven skill changes 仍必须经过 `proposal -> sandbox -> evaluation -> approval`。
- 只有受信 replacement proposal source 才允许进入 auto stage 评估。
- high-risk proposal 必须人工 review，不得自动入沙箱或自动 staging。
- staged replacement 仍要经过 readiness / source-anchor / operator action，不能被本文档范围内的新逻辑绕过。

### 4.4 事务与失败边界

- `apply_outcome_feedback()` 仍是扇出 orchestrator，不应在本计划中偷偷改变其 transaction owner。
- nested savepoint 保护必须继续用于可独立失败的 materialization / auto-stage 路径。
- 如果 proposal review、materialization、staging 或 curator recommendation 失败，必须留下 durable audit 或 replay entry，不得报告为成功。

### 4.5 Provenance 边界

- `source`
- `source_skill_patch_request_id`
- `recommendation_id`
- `reflection_record_id`
- `related_artifact_ids`
- `metrics_snapshot`
- `governance_evidence`

这些字段在 reflection、proposal、curator、staging 之间必须保持语义稳定。

不能出现：

- 同一来源对象被不同字段名表达。
- `skill_patch_request_realization` 与 `skill_curator_merge_recommendation` 的 source 语义混用。
- operator/manual action 与 system auto action 共用同一 reason code 但实际含义不同。

## 5. 需要增强的核心问题

### 5.1 Reflection outcome evaluation contract 仍过薄

当前 `ReflectionOutcomeService.evaluate()` 主要基于最近 task attempts 的完成/失败数量做启发式判断。

现有问题：

- topic 对齐过于依赖 `topic_key` 精确匹配。
- `window_size`、`observed_attempt_count`、`improvement_score` 与最终 `evaluation_status` 的 contract 没有独立样例集。
- `pending -> effective/ineffective/inconclusive` 的状态转换虽存在，但缺少显式的边界测试矩阵。
- “没有足够 attempt 时为什么保持 pending / inconclusive” 目前更像代码行为，不像稳定规则。

需要增强：

- outcome evaluation 的 golden fixtures。
- 状态转换矩阵测试。
- no-evidence、mixed-evidence、wrong-topic、stale-attempts 代表样例。
- score / note / snapshot 字段的一致性断言。

### 5.2 `apply_outcome_feedback()` 是高风险扇出点

当前 `apply_outcome_feedback()` 已经同时影响：

- reflection record
- strategy card
- reflective memory
- long-term memory bridge / materialization
- proposal replay-eval
- reflection-sourced `skill_package` proposal creation

这意味着任何小改动都可能同时影响多个下游。

当前缺口：

- 没有一套闭环 fixture 同时断言这些下游是否被正确触发或被正确跳过。
- materialization 失败时虽已存在 replay/scheduled fallback，但 proposal review 和 proposal creation 的相互影响缺少统一 baseline。
- `effective` outcome 下已有 proposal 的 replay review 与新 proposal 创建之间，没有显式的次序/失败语义文档。

需要增强：

- `effective` / `ineffective` / `inconclusive` 三类闭环 fixture。
- proposal replay、proposal creation、memory bridge 的触发矩阵。
- failure-path audit / replay baseline。

### 5.3 Reflection-sourced proposal admission contract 容易漂移

当前 reflection 可以通过两条路径进入 skill evolution：

1. reflection 直接创建 `skill_package` proposal。
2. reflection outcome 先变成 curator evidence / recommendation，再由 `patch_needed` 等 recommendation 创建 `skill_patch_request`，再 realization 为 replacement `skill_package` proposal。

当前问题：

- 两条路径的证据快照字段结构不完全一致。
- “何时直接创建 reflection-sourced skill package、何时只产生 recommendation” 的质量边界还不够清晰。
- duplicate/high-priority 逻辑写在 `apply_outcome_feedback()` 中，后续很容易被误改。

需要增强：

- 直接 proposal 与 recommendation-sourced proposal 的 source/provenance 对照样例。
- duplicate_count / priority_score 阈值的固定样例。
- `ineffective / inconclusive / low-priority` 不创建 skill package 的 fail-closed 样例。

### 5.4 Curator 与 auto-stage 的自动治理边界需要再固化

当前 `ReflectionSkillEvolutionCuratorService` 已具备自动推进能力，这本身就是高风险区。

当前风险点：

- `approved_by` 缺失、非 system approver、non-trusted source、high risk、savepoint 缺失、24h limit 超限等条件分散在多个分支。
- 如果后续 `skills.py` 拆分或 `task.py` job dispatch 收口时漏掉其中一条，就可能出现误 staging。
- 当前已有点状测试，但还缺一个完整的 auto-governance gate matrix。

需要增强：

- auto realization / sandbox enqueue / auto stage 的 gate matrix。
- system auto action 与 operator manual action 的 reason code / audit matrix。
- “被 suspend / reject 后不得继续推进”的回归断言。

### 5.5 Curator governance evidence 还缺统一输出 contract

当前 `SkillCuratorJob` 已消费：

- memory conflict summary
- reflection outcome evaluation
- resolver health trend
- coverage regression

但这批 evidence 目前仍聚在 `skills.py` 大文件内，容易随实现细节变化而漂移。

特别是 reflection outcome evidence：

- 需要明确最小字段集。
- 需要固定 ineffective / inconclusive 触发 review 的阈值语义。
- 需要确保 recommendation 只增强 review/suppress 类建议，不越权执行 artifact lifecycle。

### 5.6 End-to-end regression 仍不成体系

当前测试覆盖点很多，但仍以 service-level case 为主。

缺少的不是“更多单测”，而是“几个代表性闭环场景的稳定样例”。

至少还需要这些闭环样例：

- effective reflection -> proposal created -> sandbox admitted -> approved/effective -> staged replacement。
- ineffective reflection -> governance evidence only -> curator flags review -> no artifact mutation。
- duplicate but low-priority reflection -> no skill package created。
- patch_needed recommendation -> skill_patch_request -> realization -> trusted replacement proposal -> guarded auto staging。
- high-risk / non-trusted / rate-limited replacement proposal -> suspended，不继续推进。

## 6. 推荐技术实现

### 6.1 总体策略

原则是：

1. 先固化 contract。
2. 再补闭环 fixtures。
3. 再做窄提取。
4. 最后把结构拆分与 worker 边界收口接上。

不要反过来先大拆 `skills.py` 或 `task.py`，否则很容易在尚未有基线时把治理规则拆散。

### 6.2 允许的最小重构

为让闭环质量可长期维护，建议只做两类窄提取：

1. 提取 reflection outcome 的纯评估 contract。
2. 提取 proposal / curator 的 provenance / evidence snapshot builder。

推荐目标新增：

```text
packages/agent_core/src/agent_core/application/services/
  reflection_outcome_policy.py
  reflection_provenance.py
```

作用划分：

- `reflection_outcome_policy.py`
  - 只承载纯评估逻辑
  - 不持有 repository / audit / db session
  - 输出确定性的 status / score / snapshot / note
- `reflection_provenance.py`
  - 只承载 reflection-sourced proposal / recommendation evidence builder
  - 统一 source / ids / metrics / governance_evidence 结构

说明：

- 这不是强制立即拆 package。
- 如果后续按 `SKILLS_PY_SPLIT_PLAN.md` 落地 `skill/curator_job.py`、`skill/recommendation.py`，这两个纯模块可以直接复用。
- `reflection.py`、`reflection_proposals.py`、`reflection_skill_evolution_curator.py` 仍保持 orchestration owner，不在本阶段迁移 transaction ownership。

### 6.3 测试样例目录

建议目标新增：

```text
tests/fixtures/reflection_skill_evolution/
  outcome_evaluation_cases.json
  reflection_feedback_cases.json
  reflection_skill_package_cases.json
  curator_auto_stage_cases.json
  governance_evidence_cases.json
```

说明：

- 这些是目标新增，不代表当前仓库已存在。
- fixtures 用于把“输入 -> 预期 status / reason / source / audit”固化下来。
- 默认仅使用 stub repository / fake session / mock provider。

### 6.4 闭环验证入口

建议目标新增一组聚焦验证入口：

```bash
python3 -m pytest tests/test_reflection_service.py -q
python3 -m pytest tests/test_skill_service.py -q
python3 -m pytest tests/test_task_service.py -q
```

如果后续补专门回归文件，建议进一步收口为：

```bash
python3 -m pytest tests/test_reflection_skill_evolution_regression.py -q
```

目标是让这条闭环不必每次靠全量大测试定位。

## 7. 推荐执行阶段

### Phase 0：冻结当前闭环事实

目标：先把当前真实行为冻结成基线。

执行：

1. 搜索现有 event type、reason code、source 字段：

   ```bash
   rg -n "reflection\\.outcome|skill_patch_request|auto_staged|governance_evidence|source_skill_patch_request_id|recommendation_id" packages/agent_core/src tests
   ```

2. 列出当前关键 contract：
   - outcome statuses
   - proposal sources
   - curator recommendation reason codes
   - auto-stage suspend / reject reason codes
3. 为现有已覆盖行为补“文档化样例”，避免后续改动把当前规则悄悄改掉。

完成标准：

- 有一份明确的 status/source/reason code 基线表。
- 文档与当前代码/测试口径一致。

### Phase 1：固化 reflection outcome 评估 contract

目标：把 outcome evaluation 从“代码里的一组 if/else”提升为稳定规则。

执行：

1. 为 `pending / effective / ineffective / inconclusive` 建立样例。
2. 固化这些输入维度：
   - `window_size`
   - `topic_key`
   - `observed_attempt_count`
   - `success_count`
   - `failure_count`
3. 若实现允许，提取纯评估 helper 到 `reflection_outcome_policy.py`。
4. 为 `evaluation_note`、`outcome_snapshot`、`improvement_score` 建立断言。

完成标准：

- outcome evaluation 在纯 stub 输入下可稳定重复。
- 状态转换矩阵具备回归测试。
- 没有 attempt、topic 不匹配、证据混杂时的行为有明确预期。

### Phase 2：固化 `apply_outcome_feedback()` 扇出语义

目标：明确不同 outcome 状态会触发哪些下游、跳过哪些下游。

执行：

1. 为 `effective / ineffective / inconclusive` 建立反馈矩阵：
   - reflection priority/status
   - strategy card refresh
   - reflective memory candidate
   - long-term memory bridge / materialization
   - proposal replay review
   - skill package creation
2. 固化失败保护：
   - materialization 失败 -> replay/audit
   - proposal replay/eval 失败 -> 不得伪成功
3. 为 duplicate/high-priority 门槛补样例。

完成标准：

- `apply_outcome_feedback()` 的各分支有明确下游断言。
- failure-path 有 durable evidence。
- direct skill package creation 的触发条件不再隐含。

### Phase 3：固化 reflection-sourced proposal / provenance contract

目标：让 proposal 来源、证据和 lineage 在多服务之间不漂移。

执行：

1. 为这几类来源建立统一样例：
   - reflection direct `skill_package`
   - `skill_curator_recommendation` -> `skill_patch_request`
   - `skill_patch_request_realization` -> replacement `skill_package`
   - `skill_curator_merge_recommendation` -> replacement `skill_package`
2. 统一校验：
   - `source`
   - `reflection_record_id`
   - `recommendation_id`
   - `source_skill_patch_request_id`
   - `artifact_id`
   - `related_artifact_ids`
   - `metrics_snapshot`
3. 若实现允许，抽出 `reflection_provenance.py`。

完成标准：

- 每类 proposal source 的 evidence snapshot 均有固定 contract。
- provenance 字段不再散落为“测试里顺手断言的偶然结构”。

### Phase 4：固化 curator auto-governance gate matrix

目标：把自动推进能力收口为显式、可验证的门。

执行：

1. 为 `ReflectionSkillEvolutionCuratorService` 建立 gate matrix：
   - high risk
   - sandbox failed/cancelled
   - evaluation ineffective/inconclusive
   - negative score delta
   - approver missing
   - approver non-system
   - non-trusted replacement source
   - savepoint unavailable
   - 24h limit reached
2. 固化三类结果：
   - `rejected`
   - `suspended`
   - `staged`
3. 固化对应 audit / metrics / event type。

完成标准：

- 自动治理路径默认 fail-closed。
- 没有任何一个 gate 丢失会导致误 staging 而不被测试发现。

### Phase 5：固化 curator governance evidence 与 recommendation contract

目标：让 reflection outcome 进入 curator recommendation 时仍保持可解释和不越权。

执行：

1. 固化 reflection outcome evidence 最小字段集。
2. 为 ineffective / inconclusive 阈值建立样例。
3. 断言 recommendation 只会：
   - 生成/增强 `flag_for_review`
   - 或保持 `none`
4. 禁止 reflection evidence 直接触发 artifact lifecycle side effect。

完成标准：

- curator evidence 输出结构稳定。
- review recommendation 与 artifact lifecycle 之间仍有人工/治理隔离。

### Phase 6：形成端到端闭环回归集

目标：把前面几阶段串成少量高信号场景。

建议至少保留 5 个代表性端到端场景：

1. `effective` reflection 促进 governed replacement 候选进入 staging。
2. `ineffective` reflection 只触发 review evidence，不修改 artifact。
3. duplicate 但未达优先级阈值的 reflection 不创建 skill package。
4. patch-needed recommendation 经 patch request realization 后进入 trusted replacement auto-stage。
5. auto-stage 因 rate limit / source / approval 缺口被 fail-closed 阻断。

完成标准：

- 端到端场景可独立执行。
- 失败时能快速定位到 reflection、proposal、curator、staging、task worker 哪一层。

## 8. 关键难点与应对

### 8.1 同一闭环跨多个大服务文件

难点：

- 当前逻辑横跨 `reflection.py`、`reflection_proposals.py`、`reflection_skill_evolution_curator.py`、`skills.py`、`task.py`。

应对：

- 本阶段不大拆 orchestrator。
- 先提取纯 contract 和 provenance builder。
- 用 regression baseline 压住拆分风险。

### 8.2 低信任信号与 governed 状态之间容易误提权

难点：

- reflection outcome 本质上是启发式治理信号，不是 artifact lifecycle 命令。

应对：

- 所有自动路径都必须通过 gate matrix。
- `ineffective / inconclusive / pending` 默认只做 evidence 或阻断。
- staging 之前必须复核 source、approval、evaluation、savepoint、rate limit。

### 8.3 失败恢复既要保守，又不能吞掉证据

难点：

- nested savepoint、replay fallback、audit 写入和 recommendation pending 之间容易出现“局部失败但外部看上去成功”。

应对：

- 明确每类失败的落点：
  - audit
  - replay
  - pending recommendation
  - suspended proposal
- 不以 best effort 成功覆盖保护路径失败。

### 8.4 `skills.py` 巨型文件会放大质量漂移

难点：

- curator governance evidence 和 recommendation contract 还在大文件里，后续拆分时很容易顺手改语义。

应对：

- 本计划先把输出 contract 固化。
- 再按 `SKILLS_PY_SPLIT_PLAN.md` 把 curator job / recommendation 拆出。

## 9. 边界与依赖关系

本计划与其他计划的边界如下：

- 与 `SKILLS_PY_SPLIT_PLAN.md`
  - 本文档不负责 `skills.py` 的结构拆分顺序。
  - 但会为 curator / readiness / recommendation 拆分提供质量基线。
- 与 `TASK_AUTONOMY_CALLBACK_BOUNDARY_PLAN.md`
  - 本文档不负责移除 task/autonomy callback。
  - 但会定义 `reflection_skill_evolution_curator` job 的行为基线。
- 与 `MEMORY_QUALITY_REGRESSION_PLAN.md`
  - reflection outcome 到 memory bridge 属于共享边界。
  - 如果该边界发生行为变更，两份文档都要同步更新。
- 与 `MVP_VALIDATION_BASELINE_PLAN.md`
  - 本文档产出的端到端样例，后续应纳入 MVP smoke / regression 基线。

## 10. 交付条件

完成本计划，至少应交付：

1. 一组 reflection outcome evaluation 的稳定样例与测试。
2. 一组 `apply_outcome_feedback()` 的下游触发矩阵测试。
3. 一组 proposal source / provenance / evidence snapshot contract 测试。
4. 一组 curator auto-governance gate matrix 测试。
5. 一组端到端闭环 regression 场景。
6. 文档化的 status/source/reason code 基线。

验收标准：

- 低质量 reflection 不会自动推进到 governed artifact staging。
- 高质量 reflection 的受控推进路径可重复执行且有 durable audit。
- recommendation、proposal、staging 的 provenance 字段稳定可查。
- 相关测试默认不依赖真实 provider。
- 后续拆分 `skills.py` / `task.py` 时，闭环规则漂移会被回归测试直接打断。

## 11. 推荐实施顺序

推荐落地顺序：

1. Phase 0：冻结 contract 事实。
2. Phase 1：固化 outcome evaluation。
3. Phase 2：固化 feedback fan-out。
4. Phase 3：固化 provenance / proposal source。
5. Phase 4：固化 auto-governance gates。
6. Phase 5：固化 curator evidence contract。
7. Phase 6：形成闭环 regression 入口。

不要先做：

- 大规模重写 reflection service。
- 提前做 auto activate / auto replace。
- 在 `skills.py` 还未拆分前继续堆新的 product-critical auto governance 分支。
