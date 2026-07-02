# Memory 质量与回归增强执行技术计划

## 1. 文档定位

本文档用于指导 `agent-edu` 当前 long-term memory 链路的质量增强与回归基线固化。

目标不是重写整套 memory system，也不是提前做第三阶段的“强自治记忆网络”，而是在保持现有 MVP 行为、治理边界、API 语义和 worker 语义兼容的前提下，把 Memory 的质量规则、失败保护和回归验证做成可重复执行、可定位故障、可安全迭代的一套后端基线。

本文档只负责质量与回归基线。

`memory.py` 的结构拆分以 [plan/MEMORY_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/MEMORY_PY_SPLIT_PLAN.md) 为主。

两者关系：

- 先按本文档固化 regression baseline。
- 再按 `MEMORY_PY_SPLIT_PLAN.md` 推进结构拆分。
- 拆分落地时，优先执行 `result_types.py -> constants.py -> learner_memory/quality.py` 这一批低风险改动。

优先级：

1. 不改变 `candidate -> active/stable/suppressed/archived` 的治理规则。
2. 不让自动 materialization 直接写入高信任状态。
3. 不让 suppressed / archived memory 被自动恢复。
4. 不让 quality 规则继续只藏在 `memory.py` 私有方法里而无法稳定回归。
5. 默认回归路径不依赖真实外部 provider。

## 2. 当前状态判断

当前 Memory 主链路已经具备最小完整闭环：

- chat turn 后会写 `session_memory_events`，并可写 embedding。
- 回复前会做 session / profile memory retrieval，并回注上下文。
- long-term memory 已区分 `KnowledgeMemory` / `BehaviorMemory`。
- 自动沉淀默认写入 `candidate`，而不是直接写入 `active` / `stable`。
- evidence links、governance decisions、annotations、conflict sets、operator suppress / restore 已存在。
- `MemoryMaintenanceService` 已有 job seeding、claim、retry/backoff、durable audit。
- reflection outcome 与 long-term memory 已有 bridge。

当前实现事实：

- [packages/agent_core/src/agent_core/application/services/memory.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/memory.py) 已达 5250 行。
- [packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py) 负责 chat / task / reflection / structured extraction materialization。
- [packages/agent_core/src/agent_core/application/services/memory_maintenance.py](/home/cl/agent-edu/packages/agent_core/src/agent_core/application/services/memory_maintenance.py) 负责 governance / compression / conflict refresh job。
- [tests/test_memory_service.py](/home/cl/agent-edu/tests/test_memory_service.py) 已有大量 Memory 主链路测试，但已膨胀到 3348 行。
- [tests/test_memory_maintenance_service.py](/home/cl/agent-edu/tests/test_memory_maintenance_service.py) 与 [tests/test_long_term_memory_materialization_replay.py](/home/cl/agent-edu/tests/test_long_term_memory_materialization_replay.py) 已覆盖 maintenance / replay 主路径。

现有覆盖并不弱，已经覆盖了这些关键行为：

- session event 写入、embedding 写入、durable audit。
- retrieval ranking。
- long-term candidate upsert 去重与 identity race。
- suppressed memory 不会在普通 upsert 中被自动恢复。
- chat / task / reflection materialization。
- structured extraction validation。
- governance threshold、promotion eligibility、promotion / suppress 物理状态变更。
- conflict refresh 与 resolved / stale close。
- replay executor 重建 source records。

但剩余问题仍然明显：

1. quality 规则散落在 `memory.py` 私有方法中，修改一处很容易误伤 promotion、retrieval、reflection corpus。
2. 现有测试覆盖了“行为点”，但没有形成稳定的 Memory 回归样例集和 golden baseline。
3. topic normalization、topic alignment、evidence mix、quality tier、promotion readiness 没有被当作一套显式 contract 管理。
4. suppressed / archived fail-closed 虽已有局部测试，但没有覆盖 chat、task、reflection、structured extraction、replay 五类入口的全链路不恢复语义。
5. memory changes 对 downstream 的 reflection corpus、governance summary、skill curator evidence 的影响还缺少回归护栏。

## 3. 目标与非目标

### 3.1 目标

本次增强应达成：

1. quality 规则显式化，可在不依赖 repository 的前提下稳定回归。
2. 建立一套可复用的 Memory regression fixtures，覆盖 chat / task / reflection / structured extraction / maintenance。
3. 把 suppressed / archived / contested / candidate promotion 等高风险状态边界补成 fail-closed 测试矩阵。
4. 固化 retrieval、promotion、conflict、reflection corpus、governance summary 的最小输出契约。
5. 提供一个独立的 Memory 验证入口，避免每次都依赖超大综合测试定位问题。

### 3.2 非目标

本次不应做：

- 不新增新的 long-term memory status。
- 不改变 memory API 路由名、audit event type、job type 名称。
- 不把 memory governance 改写成新的 workflow engine。
- 不引入真实 provider 依赖作为默认测试路径。
- 不在本计划中强行完成 `memory.py` 全量拆分。

如果为了质量回归必须做重构，只允许做“窄边界、纯逻辑、可回滚”的提取。

## 4. 关键边界

### 4.1 写入边界

- 自动 materialization 只能写 `candidate` 或刷新已有 governed memory。
- promotion 到 `active` / `stable` 只能通过治理路径完成。
- structured extraction 仍然属于低信任输入，必须先校验，再落 `candidate`。

### 4.2 状态边界

- `suppressed` 和 `archived` 不能在自动 upsert / replay / maintenance 中被静默恢复。
- `contested` 或高 contradiction memory 不能被 promotion 逻辑误提权。
- `candidate` 缺证据时必须保持 `candidate`，不能因质量计算漂移而误升。

### 4.3 审计边界

- memory event、promotion、suppression、restore、maintenance failure、replay failure 的 durable audit 语义不能弱化。
- 如果 quality / governance 计算失败，必须保留失败证据，而不是 best effort 吞掉。

### 4.4 下游边界

- reflection corpus 的字段契约不能随 quality 重构发生静默漂移。
- memory governance summary 的聚合字段不能破坏 operator 端已有消费。
- skill curator 消费的 memory conflict summary / governance evidence 输出必须保持兼容。

### 4.5 Provider 边界

- 默认 regression 必须使用 stub embedding provider。
- provider 失败路径只验证 fail-closed 和 durable audit，不把网络波动当作默认质量信号。

## 5. 需要增强的核心问题

### 5.1 Topic 对齐与 normalization 规则

当前系统已有 `MemoryNormalizer`，但 topic normalization、separator 兼容、token 对齐、behavior category / semantic category 归一规则仍然是 Memory 质量的高敏感区。

需要增强：

- 常见 topic key 变体的归一回归集。
- `Matrices` / `matrix-multiplication` / `matrix multiplication` 一类变体的对齐基线。
- behavior category、semantic category、evidence role 的固定输入输出样例。
- normalization 的 reject / degrade case，而不只验证 happy path。

### 5.2 Quality score 与 readiness contract

当前 `memory.py` 中已经有：

- `_knowledge_quality_score`
- `_behavior_quality_score`
- `_quality_tier`
- `_knowledge_promotion_readiness`
- `_behavior_promotion_readiness`
- `_quality_reasons`
- `_memory_quality_snapshot_sync`

这些逻辑已经是隐含 contract，但还没有被单独固化。

需要增强：

- 明确 quality score 的输入维度、阈值和 reason code。
- 为 knowledge / behavior 分别建立 golden fixtures。
- 固化“同一输入数据必须得到同一 tier / readiness / reasons”的回归测试。
- 为 threshold 调整保留“预期变化必须显式更新样例”的门槛。

### 5.3 Evidence 质量与退化检测

当前 evidence 已覆盖 session event、task attempt、reflection outcome 等来源，但仍缺：

- evidence mix 是否失衡的明确检测。
- evidence 过旧、过少、矛盾升高时的质量退化回归。
- `source_event_ids / source_memory_ids / provenance_source_id` 是否保持一致的跨入口断言。

需要增强：

- 证据充足、证据不足、证据冲突、证据过旧四类代表场景。
- memory quality snapshot 的结构化断言。
- promotion eligibility 与 evidence degradation 的联动回归。

### 5.4 Fail-closed 生命周期保护

当前最重要的安全要求不是“多升几个 memory”，而是“不要误恢复、误提权、误合并”。

需要增强：

- 自动 materialization 遇到 suppressed / archived 目标时的统一跳过语义。
- conflict refresh 后 contested memory 的维持和关闭条件。
- compression 不把被 suppress 的 source 或已归档 source 混进新的可见聚合结果。
- replay 不因为 source 重放而突破已有 suppress / archive 边界。

### 5.5 下游消费回归

memory 不只是存储层，它已经影响：

- reflection corpus。
- governance summary。
- reflection outcome bridge。
- skill curator governance evidence。

需要增强：

- 代表性 Memory 样例对 reflection corpus 输出排序和 recommended action 的回归。
- governance summary 的统计口径和 topic bucket summary 的回归。
- conflict summary 对 skill curator 可见字段的最小兼容断言。

## 6. 推荐技术实现

### 6.1 总体策略

原则是“先显式 contract，再补测试，再做窄重构”，不要反过来。

推荐顺序：

1. 固化现有行为样例。
2. 先为拆分准备兼容承载层，再把纯质量逻辑从大服务里窄提取。
3. 补全高风险 fail-closed 测试矩阵。
4. 再考虑增量优化 normalization 或 evidence scoring。

### 6.2 允许的最小重构

为了让回归可以长期维护，并与 [plan/MEMORY_PY_SPLIT_PLAN.md](/home/cl/agent-edu/plan/MEMORY_PY_SPLIT_PLAN.md) 对齐，建议目标新增：

```text
packages/agent_core/src/agent_core/application/services/learner_memory/
  result_types.py
  constants.py
  quality.py
```

其中：

- `result_types.py` 负责承载当前 `memory.py` 对外暴露的结果 dataclass。
- `constants.py` 负责承载 Memory 质量与 evidence 权重等纯配置数据。
- `quality.py` 只承载纯质量逻辑，不持有 repository、session、audit 依赖。

建议迁入 `quality.py`：

- quality score 计算。
- quality tier 判定。
- promotion readiness 判定。
- quality reasons 生成。
- quality snapshot 的纯数据构造。

`memory.py` 继续作为 orchestration owner：

- repository 读写。
- evidence upsert。
- governance transition。
- audit。
- maintenance batch 组织。

这样做的理由：

- 质量规则最适合做确定性回归。
- 先补 `result_types.py` / `constants.py` 可以降低后续 `memory.py` facade 改造风险。
- 纯逻辑提取风险比拆 service 小得多。
- 可以先不动 API 和 repository 边界。

### 6.3 测试样例目录

建议目标新增：

```text
tests/fixtures/memory/
  normalization_cases.json
  quality_knowledge_cases.json
  quality_behavior_cases.json
  promotion_readiness_cases.json
  retrieval_ranking_cases.json
  conflict_cases.json
  reflection_corpus_cases.json
```

样例要求：

- 全部使用确定性文本和确定性分数。
- 不依赖真实时间漂移，必要时固定 `created_at` / `updated_at`。
- 不依赖真实 embedding provider。
- 每个 case 都显式写出预期的 tier / readiness / reasons / recommended action。

### 6.4 测试文件拆层

建议目标新增或拆分为以下测试文件，而不是继续把回归全堆进 `tests/test_memory_service.py`：

```text
tests/test_memory_quality_regression.py
tests/test_memory_fail_closed.py
tests/test_memory_downstream_contracts.py
tests/test_memory_regression_fixtures.py
```

职责建议：

- `test_memory_quality_regression.py`
  - quality score
  - tier
  - readiness
  - reason codes
  - evidence degradation

- `test_memory_fail_closed.py`
  - suppressed / archived 不自动恢复
  - candidate 不因 replay 或 compression 被误提权
  - contested memory 不误 promotion

- `test_memory_downstream_contracts.py`
  - reflection corpus
  - governance summary
  - conflict summary
  - bridge output contract

- `test_memory_regression_fixtures.py`
  - fixtures schema
  - fixture runner
  - golden output regression

### 6.5 Makefile 验证入口

建议目标新增：

```makefile
memory-check:
	python3 -m pytest \
		tests/test_memory_service.py \
		tests/test_memory_maintenance_service.py \
		tests/test_long_term_memory_materialization_replay.py \
		tests/test_memory_quality_regression.py \
		tests/test_memory_fail_closed.py \
		tests/test_memory_downstream_contracts.py \
		-q
```

如果后续执行时间过长，再拆：

```makefile
memory-smoke:
	python3 -m pytest \
		tests/test_memory_service.py \
		tests/test_memory_maintenance_service.py \
		tests/test_long_term_memory_materialization_replay.py \
		-q

memory-regression:
	python3 -m pytest \
		tests/test_memory_quality_regression.py \
		tests/test_memory_fail_closed.py \
		tests/test_memory_downstream_contracts.py \
		-q
```

## 7. 分阶段实施计划

### Phase 0：校准基线

目标：先把当前 Memory 系统的真实覆盖和输出样例固定下来。

执行：

1. 跑现有 Memory 测试：

   ```bash
   python3 -m pytest \
     tests/test_memory_service.py \
     tests/test_memory_maintenance_service.py \
     tests/test_long_term_memory_materialization_replay.py \
     -q
   ```

2. 盘点当前已受保护行为：

   - retrieval ranking
   - upsert dedupe
   - suppression fail-closed
   - materialization
   - promotion eligibility
   - governance transition
   - conflict refresh
   - replay

3. 选出首批固定回归样例：

   - knowledge candidate ready
   - knowledge candidate blocked by contradiction
   - behavior candidate ready
   - stale active memory
   - contested memory
   - suppressed memory hit by repeated source
   - archived memory hit by replay

输出物：

- 一份 Memory regression case 清单。
- 一组固定 fixture 文件。

### Phase 1：固化纯质量逻辑

目标：先补足与结构拆分兼容的承载层，再把最容易漂移、最适合回归的逻辑显式化。

执行：

1. 新增 `learner_memory/result_types.py`。
2. 新增 `learner_memory/constants.py`。
3. 新增 `learner_memory/quality.py`。
4. 在 `memory.py` 顶层增加兼容 re-export。
5. 从 `memory.py` 中提取纯函数到 `learner_memory/quality.py`：

   - knowledge / behavior quality score
   - quality tier
   - readiness
   - quality reasons
   - quality snapshot pure builder

6. 保持 `MemoryService` 的 public API 不变，仅改内部调用。
7. 为提取后的纯函数建立 fixture-based regression tests。

边界：

- 不在此阶段改 repository。
- 不在此阶段改 audit event type。
- 不在此阶段改 DB schema。
- 不在此阶段推进 `memory.py` 的完整结构拆分；完整拆分顺序以 `MEMORY_PY_SPLIT_PLAN.md` 为准。

### Phase 2：补 fail-closed 生命周期矩阵

目标：保证质量增强不会突破治理边界。

执行：

1. 为以下入口补统一回归：

   - `materialize_from_chat_turn`
   - `materialize_from_task_outcome`
   - `materialize_from_reflection_outcome`
   - `materialize_from_structured_extraction`
   - `LongTermMemoryMaterializationReplayExecutor.replay`

2. 每个入口都验证：

   - 遇到 suppressed 目标不会恢复。
   - 遇到 archived 目标不会恢复。
   - evidence 只追加到允许状态的 memory。
   - conflict / contested 状态不会被 promotion 绕过。

3. 补 compression 与 conflict refresh 的交叉场景：

   - source 被 suppress 后不应作为可见聚合来源重新激活。
   - conflict set stale close 不应误关仍然可见的冲突。

### Phase 3：补下游 contract 回归

目标：Memory 质量增强后，下游依赖结果不发生静默变形。

执行：

1. 为 `build_reflection_corpus()` 固化：

   - 排序
   - `recommended_action`
   - `recommended_action_reason`
   - `contested`
   - `review_recommended`

2. 为 `build_governance_summary()` 固化：

   - status 计数
   - candidate / active / stable / suppressed / archived 分布
   - topic bucket summary

3. 为 conflict summary 与 reflection bridge 固化最小兼容字段。

边界：

- 只固化结构化输出，不把文案措辞做成脆弱快照。
- 尽量断言字段和值域，而不是整块字面量 snapshot。

### Phase 4：增强 observability 与发布验证入口

目标：让 Memory 回归结果可被运维和发布流程消费。

执行：

1. 新增 `memory-check` Makefile 入口。
2. 在文档中加入 triage 顺序：

   - quality fixture fail
   - service behavior fail
   - maintenance / replay fail
   - provider stub mismatch
   - downstream contract fail

3. 如有必要，补充以下观测断言：

   - `memory_maintenance.job.*`
   - `long_term_memory.materialization.replayed`
   - `memory.*` audit
   - observability metrics 关键名称未丢失

## 8. 技术难点与应对

### 8.1 `memory.py` 过大，质量逻辑与 orchestration 紧耦合

难点：

- 直接大拆分风险高。
- repository、audit、governance、retrieval、reflection corpus 混在同一服务里。

应对：

- 只先提取纯逻辑到 `learner_memory/quality.py`。
- 保持 `MemoryService` 作为 orchestration facade。
- 不在本计划中一次性拆 repository coordination。

### 8.2 时间衰减与 freshness 容易导致测试脆弱

难点：

- `_freshness_decay`、`_decay_freshness` 与时间有关。

应对：

- fixture 中固定时间戳。
- 测试中注入固定当前时间或使用可控时间边界。
- 避免使用“当前时间自然流逝”断言。

### 8.3 Embedding / retrieval 容易被 provider 差异污染

难点：

- retrieval 排序依赖向量，相似度轻微变化就可能导致脆弱。

应对：

- 默认 regression 统一使用 stub embedding provider。
- golden cases 使用固定向量，不用真实 provider。
- 只在 gated real-provider regression 中验证 provider contract。

### 8.4 多来源 materialization 容易出现 provenance 漂移

难点：

- chat、task、reflection、structured extraction、replay 各自的 provenance anchor 不同。

应对：

- 为每个 source type 固定 provenance contract 测试。
- 显式断言 `provenance_type / provenance_source_id / source_event_ids / source_memory_ids`。
- 禁止不同来源对象被混用为同一高信任锚点。

### 8.5 下游 contract 变化隐蔽但影响大

难点：

- memory quality 的小改动，可能改变 reflection corpus 排序或 curator evidence。

应对：

- 为下游输出加单独 contract tests。
- 对排序仅断言关键优先级，不做过脆的整块快照。
- 若确实需要变更下游行为，必须同步更新文档与 fixtures。

## 9. 是否需要重构

需要，但只做以下受控重构：

1. 必做：
   - 先补 `learner_memory/result_types.py` 与 `learner_memory/constants.py`。
   - 提取 `learner_memory/quality.py` 这类纯逻辑模块。
   - 为 regression fixtures 建测试辅助层。
   - 将新增回归测试从 `tests/test_memory_service.py` 外移，避免继续膨胀。

2. 可选：
   - 后续把 `build_reflection_corpus`、`build_governance_summary` 的纯解释逻辑再抽出。

3. 暂不做：
   - 不在本阶段拆整个 `MemoryService`。
   - 不在本阶段调整 DB schema。
   - 不在本阶段修改 maintenance job 类型和调度模型。

## 10. 推荐测试矩阵

必须覆盖的最小场景：

1. normalization
   - topic separator 变体
   - semantic / behavior category 标准化
   - evidence role 分类

2. quality / readiness
   - 高质量 candidate ready
   - 低 relevance blocked
   - 高 contradiction blocked
   - stale active degradation
   - behavior recurrence ready

3. fail-closed lifecycle
   - suppressed 不恢复
   - archived 不恢复
   - contested 不 promotion
   - candidate 无 eligibility 不 promotion

4. retrieval
   - weighted ranking
   - eligible candidate lower weight but visible
   - profile/session scope 不串线

5. materialization / replay
   - chat turn
   - task outcome
   - reflection outcome
   - structured extraction
   - replay source reconstruction

6. maintenance
   - governance batch
   - promotion eligibility batch
   - compression
   - conflict refresh
   - retry / fail / durable audit

7. downstream
   - reflection corpus
   - governance summary
   - bridge_reflection_outcome
   - conflict summary contract

## 11. 交付条件

完成标准：

1. 新增 Memory regression fixtures 已落地并被测试消费。
2. quality / readiness 纯逻辑已从超大 service 中窄提取，或至少被 fixture-based tests 直接保护。
3. chat / task / reflection / structured extraction / replay 五类入口都覆盖 suppressed / archived fail-closed 语义。
4. reflection corpus、governance summary、conflict summary 的最小输出契约已有回归测试。
5. `memory-check` 或等价入口可在默认本地环境跑通。
6. 默认路径不依赖真实 provider。
7. 所有新增行为保持 audit、governance、transaction 语义不弱化。

落地后的目标验收命令：

```bash
python3 -m pytest \
  tests/test_memory_service.py \
  tests/test_memory_maintenance_service.py \
  tests/test_long_term_memory_materialization_replay.py \
  tests/test_memory_quality_regression.py \
  tests/test_memory_fail_closed.py \
  tests/test_memory_downstream_contracts.py \
  -q
```

如果还要做 MVP 链路回归，追加：

```bash
python3 -m pytest tests/test_mvp_acceptance.py -q
```

## 12. 推荐执行顺序

建议按以下顺序推进：

1. 先做 regression fixtures 和 `memory-check` 入口。
2. 再补 `learner_memory/result_types.py`、`learner_memory/constants.py`。
3. 再提取 `learner_memory/quality.py` 纯逻辑。
4. 再补 fail-closed 生命周期矩阵。
5. 最后补下游 contract 回归和 observability 护栏。

原因很直接：

- 先有基线，再改质量逻辑，回归才可控。
- 先有兼容承载层，再拆 quality 逻辑，和 `MEMORY_PY_SPLIT_PLAN.md` 的结构顺序一致。
- 先补 fail-closed，再调评分阈值，风险最低。
- 不先建立独立 Memory 验证入口，就会继续依赖超大综合测试定位问题，迭代成本过高。
