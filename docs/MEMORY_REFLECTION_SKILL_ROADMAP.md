# 长期记忆 / 反思进化 / Skill 串联路线图

## 文档定位

这份文档不再把长期记忆、反思进化、Skill 系统拆成三条独立路线审视。

它描述的是三者如何组成一个受控学习闭环：

```text
runtime behavior
-> memory evidence
-> reflection outcome / proposal
-> sandbox / evaluation / approval
-> rollout / binding
-> SkillArtifact
-> runtime resolution / usage
-> curator / review
-> memory evidence / reflection trigger
```

当前实现状态以这些文档和代码为准：

- [docs/PROGRESS_STATUS.md](./PROGRESS_STATUS.md)
- [docs/IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)
- [ARCHITECTURE.md](../ARCHITECTURE.md)

本文回答两个问题：

1. 这三个系统应该如何串联，避免自我污染。
2. 对照当前代码，下一步 Skill Evolution 应该优先补什么。

---

## 结论先行

现在的正确判断是：

> `memory -> reflection -> skill_package proposal -> sandbox/evaluation/approval -> rollout/binding -> SkillArtifact -> usage` 已形成最小受控链路。

但这还不是完整动态技能系统。

已落地的是“最小治理闭环”：

- 长期记忆可以沉淀 chat / task outcome / reflection outcome evidence。
- 反思可以把重复模式变成 proposal，并进入 sandbox / replay / evaluation / approval。
- `skill_package` proposal 可以交接到版本化 `SkillArtifact`。
- runtime 已能通过 resolver 选择 active / stable artifact，并记录 usage。
- suppress / restore / rollback 已具备最小安全治理语义。
- `SkillCuratorRecommendation` 已具备治理建议承载、operator review API、audit 和 lifecycle handoff。
- `SkillCuratorJob` MVP 已能由 worker tick 周期性消费 usage、rollout observation 和 rollout decision，保守生成 stabilize / review / rollback-review / archive-candidate recommendation。
- `archive_candidate / archive_deprecated` accept 已接入 lifecycle service，可完成 `deprecated -> archived`。
- `patch_needed / none` accept 已接入 reflection proposal service，可创建 reference-only `skill_patch_request` proposal，并继续走 sandbox / evaluation / approval；它不会直接修改 artifact，也不能 rollout 或创建 skill candidate。
- approved / effective `skill_patch_request` 已可通过 realization service / API 生成新的 replacement `skill_package` proposal；它复制 source artifact 可执行定义并保留 provenance，仍需继续走自己的 sandbox / evaluation / approval。
- artifact overlap / duplicate detection 已接入 `SkillCuratorJob`，可扫描同 name/scope 或同 implementation binding 的 governed artifacts，比较 `match_rules.task_types/topic_keys` 交集，并生成 `merge_candidate / none` recommendation；该步骤只产 recommendation，不修改 artifact。
- `merge_candidate / none` accept 已接入 reflection proposal service，可创建 merge-sourced replacement `skill_package` proposal；它复用 source artifact 的可执行基线，只合并 list-valued `match_rules`，仍需继续走 sandbox / evaluation / approval。
- approved / effective replacement `skill_package` proposal 已可通过 operator-protected staging API 复用 existing candidate / stage lifecycle，生成带 lineage / parent / supersedes 链接的 `staged` replacement artifact；该步骤不 activate，也不 replace source artifact。
- curator governance evidence v1 已接入 `SkillCuratorJob`，可聚合 memory conflict summary、reflection outcome evaluation 和 resolver health trend，生成或增强 `flag_for_review / none` recommendation；该步骤只产 recommendation，不修改 artifact。
- surface / topic coverage regression 已接入 `SkillCuratorJob`，可基于声明外 topic demand 与 governed binding gap 生成带 coverage evidence 的 `patch_needed / none` recommendation；该步骤只产 recommendation，不修改 artifact。
- skill observability 已接入 Prometheus / Grafana / alert 基线，可观测 skill usage、resolver failure、artifact status、curator pending backlog、recommendation rate 与 curator job p95。
- dynamic runtime registry V1 已统一 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 的 execution-plan resolution / usage metadata sourcing；当前会把 `dynamic_registry_version`、binding / rollout 标识和 source summary 写入 usage metadata。
- rollout auto-governance V1 已落地独立 decision job，并仅对 allowlisted workflow surfaces 自动执行 rollout `promote / rollback`；当前默认 allowlist 为 `review_scheduling / assessment_generation / replan`。
- rollout auto-governance 已支持环境变量配置开关与 surface allowlist，并已补 Prometheus / Grafana / alert 基线，可观测 auto decision queued / executed / skipped、auto rollback 速率与 decision skip 速率。

仍缺的是“长期治理闭环”：

- `SkillCuratorJob` 仍是保守 MVP，已接入 artifact overlap / duplicate detection、memory conflict summary、reflection outcome evaluation、resolver health trend、surface / topic coverage regression 和 staged replacement readiness；生产级 dashboard / alert 基线已落地，但自动执行与更重的运维编排仍未完成。
- `patch_needed` 和 `merge_candidate` 已完成到 replacement `skill_package` proposal / operator staging 到 `staged` replacement artifact / readiness / curator ready recommendation 的保守 MVP；activate / replace 仍需人工执行，不会自动触发。
- staged replacement readiness API 现会直接返回 `recommended_action`，并把 source anchor / rollout / usage / threshold 摘要作为统一 replacement readiness contract 暴露给 operator 与 curator recommendation。
- staged replacement recommendation accept 现是 lifecycle-first：若 `activate / replace` 执行失败，会写 `skill.curator.recommendation.accept_failed` durable audit，且 recommendation 维持 `pending`。
- dynamic runtime registry V1 已覆盖 `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 的 execution-plan consumption，tool-plan orchestration V2/V3 已补 internal executor 与保守 multi-step chain，但 active artifact 还不是完整动态 runtime registry。
- bundle / global rollout 还未实现。
- rollout auto-governance 仍只覆盖 allowlisted workflow surfaces；`chat / hint / quiz / plan_generation` 尚未进入自动 promote / rollback。
- artifact replacement 仍未自动执行；staged replacement 的 `activate / replace` 继续依赖 readiness / curator recommendation / operator action。

因此下一步 Skill 不应先扩展更多状态名，也不应让 reflection 直接改 runtime。

下一步应优先做：

```text
curator recommendation
-> reflection proposal / operator review
-> patch request / merge-sourced replacement skill_package proposal 或 archive lifecycle
-> lifecycle service / rollout decision
-> runtime resolution / usage
```

---

## 三系统职责边界

| 系统 | 应做什么 | 输出 | 禁止事项 |
|---|---|---|---|
| 长期记忆 | 记录事实、整理证据、保留 provenance、暴露 conflict / pattern | memory candidate、evidence link、reflection corpus、governance summary | 直接生成可执行 skill；自动恢复 suppressed memory |
| 反思进化 | 判断是否需要改变行为，生成可验证 proposal，评估 rollout outcome | reflection record、outcome evaluation、proposal、rollout / rollback 建议 | 直接修改 skill registry；绕过 sandbox / approval |
| Skill 系统 | 承载已验证的可复用能力，提供 runtime resolution 和 usage 记账 | versioned artifact、binding、usage event、lifecycle audit | 靠单次成功晋升；无 usage 直接 stable；curator 直接改生产行为 |

核心边界：

- Memory 是证据仓库，不是技能仓库。
- Reflection 是改动判断器，不是生产配置写入器。
- Skill 是受控能力资产，不是任意自修改脚本。

---

## 串联设计

### 1. Runtime 产生事实

入口包括：

- chat / hint / quiz
- plan generation
- review scheduling
- assessment generation
- replan
- task / workflow outcome

这些入口会产生：

- session message
- task attempt
- workflow run
- skill usage event
- audit event
- reflection evidence signal

要求：

- runtime 可以记录事实，但不能直接晋升 memory 或 skill。
- 模型输出、工具输出、retrieval 内容都必须经过 schema / policy 边界。
- 失败、跳过、blocked resolver 结果也要保留为 evidence。

### 2. Memory 沉淀证据

长期记忆当前已承担证据整理职责：

- chat turn 可从 profile-scoped `MemoryEvent` materialize candidate。
- task outcome 可写入 `task_attempt` evidence。
- reflection outcome 可写入 `reflection_outcome` evidence。
- `memory_evidence_links` 保留证据来源。
- `memory/reflection-corpus` 为反思提供结构化语料。
- suppressed memory 不会被自动 materialization 恢复。

后续 memory 的重点不是继续扩实体，而是提高证据质量：

- 更准确的 topic / behavior normalization。
- 更完整的 provenance 链。
- 更好的 conflict explanation。
- 更稳定的长期回归集。
- 更可读的 operator review 信息。

### 3. Reflection 判断是否要改

反思系统当前已接入：

- task failed / skipped
- assessment completed
- workflow failed
- replan completed
- periodic goal reflection
- reflection outcome evaluation sweep
- strategy card / reflective memory / long-term memory bridge

反思输出应继续保持 proposal-driven：

- prompt optimization
- workflow optimization
- skill package
- rollback recommendation

要求：

- proposal 必须进入 sandbox / replay / evaluation / approval。
- low / medium risk 可以自动进入 sandbox，但不能直接 active。
- high risk 必须 operator review。
- rollout 结果必须回写 observation / outcome，而不是只看 proposal 分数。

### 4. Skill 承接已批准能力

Skill 系统当前已经不是固定白名单草稿，而是具备版本化治理资产：

- `SkillArtifact`
  - `name / version / lineage_id`
  - `skill_type / scope / status`
  - `definition / runtime_directives / tool_plan`
  - `compatibility_contract`
  - `source_reflection_ids / source_memory_ids / source_proposal_id`
  - `quality_score`
- `SkillUsageEvent`
  - artifact attribution
  - learner / goal / session / task / workflow context
  - surface / topic / outcome / latency / cost
  - resolver status / selection reason / outcome signals

已落地生命周期：

```text
candidate
-> staged
-> active
-> stable
-> suppressed
-> restored previous selectable status

active / stable / suppressed
-> deprecated on source rollout rollback
```

已落地 replacement：

```text
staged replacement
-> active

old active / stable
-> deprecated
```

当前必须继续保持的安全语义：

- `candidate -> staged` 需要 approved + effective + score_delta evidence。
- `staged -> active` 需要 rollout / binding / observation / usage evidence。
- `active -> stable` 需要更强 usage 和 promote observation evidence。
- suppress 是按 `name + scope` 生效的 runtime kill switch。
- resolver 对 suppressed artifact fail-closed，不 fallback 到 active / stable。
- rollback 优先于 restore，rolled-back source artifact 不能被 restore 重新启用。

### 5. Usage 回流给治理

当前 usage surface 已覆盖：

- chat
- hint
- quiz / create_quiz
- plan_generation
- review_scheduling
- assessment_generation
- replan

usage 的下一步用途不是简单计数，而是为 curator 和 reflection 提供判断依据：

- selectable artifact 是否真的被 runtime 使用。
- blocked / incompatible / suppressed 是否影响目标链路。
- completed / skipped / failed / partial_success 是否改变 outcome。
- rollout binding metadata 是否能追溯到 proposal / rollout / binding / skill / surface。
- usage 退化是否应该触发 reflection 或 rollback review。

---

## 当前完成度对比

### 已完成：三系统最小串联

```text
Memory evidence
-> Reflection proposal
-> Sandbox / evaluation / approval
-> Rollout / goal binding
-> SkillArtifact handoff
-> Runtime resolver
-> SkillUsageEvent
-> SkillCuratorJob recommendation
```

具体已完成：

- 长期记忆 governance v2 主链路。
- memory evidence / reflection corpus / reflection outcome bridge。
- reflection record / action / evidence / outcome / strategy card / reflective memory。
- proposal queue / sandbox / replay-eval / approval。
- rollout / rollback 扩展到 `chat / hint / plan_generation / review_scheduling / assessment_generation / replan`。
- `skill_package` proposal 类型。
- `SkillArtifact` 版本化资产。
- `SkillUsageEvent` 使用记账。
- lifecycle：candidate / staged / active / stable / deprecated / suppressed / archived。
- suppress / restore runtime kill switch。
- source rollout rollback 联动 artifact deprecate。
- runtime resolver active/stable selection、suppressed fail-closed、compatibility blocking、static fallback。
- operator-protected skill artifact API 与 usage 查询。
- `SkillCuratorRecommendation` schema / service / API / audit 已落地，operator 可 list / get / accept / dismiss recommendation。
- `SkillCuratorJob` MVP 已落地：
  - worker tick 可调用 application service，阈值可配置。
  - active artifact 满足成功 usage + promote observation 时生成 `promote_candidate / stabilize_active`。
  - active / stable artifact 负向 usage、blocked、suppressed、incompatible 信号增多时生成 `flag_for_review / none`。
  - latest rollout observation 建议 rollback 且尚无后续 rollback decision 时生成 `rollback_review / none`。
  - deprecated artifact 长期无使用时生成 `archive_candidate / archive_deprecated`。
  - 日窗口 deterministic `source_job_id` 去重，recommendation 只写 evidence / metrics snapshot 与 audit，不直接修改 artifact。
- `patch_needed / none` accept 已落地：
  - operator accept 后创建 `skill_patch_request` proposal。
  - proposal payload 只引用 artifact、usage evidence、recommendation reason / metrics。
  - 缺少 `learner_goal_id` / `reflection_record_id` anchor 或 proposal 创建失败时，recommendation 保持 pending。
  - `skill_patch_request` 可 sandbox / evaluate / approve，但不可 rollout，也不能创建 skill candidate。
- `skill_patch_request` realization MVP 已落地：
  - 只接受 approved / effective `skill_patch_request`。
  - 要求 source artifact 存在且 name / scope / version anchor 匹配。
  - 生成新的 replacement `skill_package` proposal，并复制 source artifact 的 match_rules / runtime_directives / tool_plan / scoring_contract。
  - evidence_snapshot 记录 patch request、source artifact、recommendation、usage 和 evaluation provenance。
  - 不修改 active / stable artifact，不直接创建 candidate。

### 半完成：治理消费链

这些能力已有输入或局部机制，但还没有完整闭环：

- rollout observation 已能产生 promote / rollback recommendation，但还没有 auto promote / auto rollback。
- usage evidence 已能支持 activate / stabilize，也能被 `SkillCuratorJob` MVP 汇总；`patch_needed` 已能形成 reference-only patch request proposal，并可 realization 为 replacement `skill_package` proposal；artifact overlap / duplicate detection 已能自动形成 `merge_candidate` recommendation，`merge_candidate` 已能形成 merge-sourced replacement `skill_package` proposal；replacement proposal 可由 operator staging 为 `staged` replacement artifact，并继续进入 shared readiness evaluation / strict source-anchor gate / curator ready recommendation。
- deprecated artifact 已能通过 archive service / API / audit 进入 archived，`archive_candidate` accept 也会通过 lifecycle service 执行 archive。
- replacement lifecycle 已有，replacement proposal 到 staged replacement 的保守承接已打通；merge_candidate 到 merge-sourced replacement proposal 的治理路径已保守落地。
- active artifact resolver 已接 runtime gate，但 runtime behavior 仍主要依赖静态 implementation binding 和固定 registry。
- curator governance evidence v1 已接入 memory conflict summary、reflection outcome evaluation 和 resolver health trend；surface / topic coverage regression 与 skill observability dashboard / alert 基线也已落地。

### 未完成：长期 Skill Evolution

下一阶段仍缺：

- bundle / global rollout
- dynamic runtime skill registry
- auto promote / auto rollback

---

## 下一步 Skill 应做什么

### 已完成优先级 1：replacement proposal -> staged replacement handoff

`SkillCuratorJob` MVP 已经能生成保守 recommendation，`archive_candidate` accept 已经能进入 archive lifecycle，`patch_needed` accept 已经能创建 `skill_patch_request` proposal，approved / effective `skill_patch_request` 也已经能 realization 为新的 replacement `skill_package` proposal。现在该 replacement proposal 被再次 sandbox / evaluation / approval 后，已可通过 operator-protected staging API 生成 `staged` replacement artifact。

已落地的最小闭环：

- approved / effective replacement `skill_package` proposal 不直接改 active artifact，而是通过 existing candidate creation 和 stage lifecycle 承接为 `staged` replacement，并保留 source artifact lineage / parent / supersedes provenance。
- staging 停在 `staged`，不自动 activate / replace；后续仍必须走既有 evidence gates。

建议流程：

```text
patch_needed recommendation
-> operator accept
-> skill_patch_request proposal
-> sandbox / replay / evaluation
-> approval
-> replacement skill_package proposal
-> sandbox / replay / evaluation
-> approval
-> replacement candidate
-> lifecycle evidence gate
-> staged replacement
-> replace_selectable
```

约束：

- curator 不直接改变 active / stable / suppressed artifact。
- curator 只能写 recommendation；后续 patch request、merge-sourced replacement proposal 和已落地的 archive lifecycle 都必须通过明确 service 边界。
- operator accept recommendation 也不能绕过 artifact lifecycle service 和既有证据门禁。
- 所有 recommendation 必须有 evidence snapshot 和 audit。

### 已完成补充：deprecated -> archived

长期下线治理已补齐。

当前语义：

- 只允许 `deprecated -> archived`。
- archived 保留 provenance、usage history、source proposal、lineage。
- archived 不可 restore 为 selectable。
- archived 不参与 resolver fallback。
- archive 需要 operator 或 curator recommendation 驱动。

### 已完成优先级 2：merge_candidate proposal

不要让 curator 直接改 artifact。

已落地流程：

```text
merge_candidate recommendation
-> operator accept
-> merge-sourced replacement skill_package proposal
-> sandbox / replay / evaluation
-> approval
-> staged replacement
-> replace_selectable
```

merge 用于多个同 surface / topic overlap artifact 的合并候选。当前 proposal payload 复用 source artifact 的 runtime_directives / tool_plan / scoring_contract，只合并相关 artifact 中 list-valued `match_rules`；source artifact 必须是 active / stable，related artifact 可以是 candidate / staged / active / stable / deprecated，不能是 suppressed / archived / rejected。

### 已完成优先级 3：curator evidence 输入增强 v1

在扩展动态 runtime 前，curator 已能看见更完整的治理证据：

- memory conflict summary。
- reflection outcome evaluation。
- resolver health trend。

这些输入只影响 `flag_for_review / none` recommendation，不会直接触发 artifact 状态变更。

### 已完成优先级 4：coverage regression

coverage regression 已完成。现在 `SkillCuratorJob` 已能基于声明外 topic demand 与 governed binding gap 生成 `patch_needed` 输入。

### 已完成优先级 5：health dashboard

skill health dashboard / alert 已完成基线接入，当前可观测 skill usage、resolver failure、artifact status、curator pending backlog、recommendation rate 与 curator job p95。

### 已完成优先级 6：activate / replace evidence hardening

已补齐 staged governed replacement 的后续证据承接：

- shared replacement readiness evaluation service
- operator-protected readiness read API
- readiness API 直接返回 `recommended_action`
- strict source-anchor gate，replace 只能替换 staging 时锚定的 source artifact
- stronger readiness threshold：2 promote observation、3 successful usage、negative rate 上限
- `SkillCuratorJob` 可为 ready staged replacement 生成 `activate_candidate / activate_staged` 或 `replace_candidate / replace_selectable` recommendation
- recommendation accept 复用既有 lifecycle service 执行人工 activate / replace，且 accept 只有在 lifecycle 成功后才会落为 `accepted`

仍然保留的约束：

- 不自动 activate / replace
- 不绕过 rollout / binding / observation / usage evidence
- 不允许 source anchor 漂移后继续 replace

### 优先级 7：动态 runtime registry

在 patch / merge、curator evidence 输入和健康观测继续收敛前，不应急着把 active artifact 变成完全动态执行源。

等下列条件满足后再推进：

- resolver health 可观测。
- usage degradation 可触发 review。
- suppressed fail-closed 已覆盖所有 runtime surface。
- archived / deprecated 不会被 fallback 误选。
- artifact directives / tool_plan 已有稳定兼容检查。

当前已完成的最小 V1：

- `chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan` 已统一接入 governed `SkillExecutionPlan`
- autonomy surfaces 已消费 `implementation_binding / execution_kind / runtime_directives / binding metadata`
- `chat / quiz / plan_generation` 已与 task/autonomy 侧对齐到同一套 runtime usage metadata helper，不再各自维护分散的 execution-plan metadata 拼装
- task/autonomy fallback path 已统一复用 runtime registry contract builder，不再在 task service 本地重复拼 registry/source 摘要
- `review_scheduling / assessment_generation / replan` 已在 task/autonomy 端端到端保留 `RuntimeSkillExecutionPlan`
- `review_bias / assessment_bias / replan_bias / skill_directives` 已可经 execution plan 生效
- `tool_plan` 已可作为 internal-only 的 runtime executor 生效，并在 sandbox preview 与 autonomy runtime 上复用同一套模板变量校验与 payload 解析
- 当前已支持最多 2 步的 linear chain、显式 `step_id`、以及 prior-step output 引用；已开放的 multi-step 序列仍是保守白名单，当前标准样板是 `partial_replan -> review_scheduling`
- `replan` 主 surface 已补 sequence 级 usage metadata、step 级 audit 与 sandbox summary；prior-step output 引用已收紧到工具输出白名单
- `chat / hint / quiz / plan_generation` 的 rollout observation 已在成功路径接通：`chat / hint` 使用 assistant message id，`quiz` 使用 quiz id，`plan_generation` 使用成功 workflow run id；其中 `plan_generation` 的 observation 只在 plan/task 持久化成功后调度
- task/autonomy usage attribution 已统一收口到公共 helper；`review_scheduling / assessment_generation / replan` 共用同一套 usage payload shaping
- allowlisted autonomy workflow surface 的 rollout observation 已在成功路径接通；当前覆盖 `review_scheduling / assessment_generation / replan`
- `tool_plan` 仍不是通用 runtime tool orchestrator；branching、looping、DAG 和更通用的多步编排未实现

---

## 风险与反模式

禁止这些路径：

- 长期记忆直接创建 executable skill。
- reflection 直接修改 registry 或 active artifact。
- curator 直接 promote / archive 生产 artifact。
- 单次成功直接 stable。
- 无 usage evidence 做 promotion。
- suppressed artifact 被 fallback 绕过。
- rolled-back rollout 通过 restore 重新启用。
- archived artifact 重新进入 selectable。

这些都会破坏 `proposal -> sandbox -> evaluation -> approval` 这条治理路径。

---

## 健康闭环的验收标准

一个完整的 memory / reflection / skill 闭环应满足：

- Memory 能说明发生了什么、证据来自哪里、是否有冲突。
- Reflection 能说明为什么要改、风险是什么、如何验证。
- Skill 能说明改动如何复用、版本从哪里来、当前为何 selectable。
- Usage 能说明是否真实生效、结果好坏、是否退化。
- Curator 能说明为什么建议 promote / patch / merge / archive。
- Operator 能追溯每次 suppress / restore / replace / rollback / archive。
- Runtime 不会因为 fallback 绕过 suppressed、deprecated、archived 或 incompatible artifact。

---

## 简短结论

下一步不是单独增强长期记忆、单独增强反思，或单独扩 Skill 状态机。

下一步应补强三系统之间的治理回流：

```text
usage
-> curator
-> proposal / review
-> skill_patch_request / replacement skill_package proposal / merge-sourced replacement skill_package proposal 或已落地的 archive lifecycle
-> staged replacement / activate-replace evidence gates
-> runtime
-> memory / reflection evidence
```

这样 Skill Evolution 才会从“最小治理闭环”进入“长期可维护的动态能力系统”。
