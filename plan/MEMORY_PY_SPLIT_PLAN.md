# `memory.py` 拆分执行计划

## 1. 文档定位

本文档用于指导 `packages/agent_core/src/agent_core/application/services/memory.py` 的可执行拆分。

目标不是重写整个 Memory System，也不是在拆分过程中顺手改变 long-term memory 的治理语义，而是在保持现有 API、chat/runtime、reflection、worker、audit、测试语义兼容的前提下，把当前 5250 行的巨型 Memory Service 拆成职责清晰、边界稳定、可继续演进的后端服务模块。

拆分优先级：

1. 不改变生产行为。
2. 不弱化 memory governance、audit、suppression / archive fail-closed 规则。
3. 不改变既有 `MemoryService` 调用入口和关键结果类型导出。
4. 先迁移常量、结果类型、纯逻辑和只读路径，再迁移 governed write 与 batch 逻辑。
5. 每个阶段都能单独运行测试并可回滚。

## 2. 当前问题判断

`memory.py` 当前混合了以下职责：

- session memory event 写入。
- event embedding 写入与错误审计。
- learning signal 提取。
- knowledge / behavior candidate 构建。
- long-term memory upsert、identity race recovery、suppressed fail-closed 处理。
- session / profile / knowledge / behavior retrieval。
- knowledge / behavior browse、detail、annotation、suppress / restore。
- interpretation 构造。
- reflection corpus 构造。
- governance summary 构造。
- evidence link upsert。
- promotion eligibility 计算。
- knowledge / behavior governance 状态变更。
- compression。
- conflict set refresh / close / detail。
- reflection outcome bridge。
- maintenance batch orchestration。
- observability metrics 刷新。
- 大量 dataclass、阈值、权重、topic 对齐和 quality 规则。

这已经不是“文件长一点”的问题，而是多个受治理子系统被堆在同一个服务文件里。继续在这里叠加逻辑会直接带来：

- quality 规则、promotion readiness、retrieval 排序在不同分支中漂移。
- suppressed / archived fail-closed 规则更难被稳定保护。
- reflection corpus、governance summary、skill curator evidence 的下游契约更容易被静默破坏。
- batch / compression / conflict refresh 的问题很难定位到具体责任模块。
- 测试继续集中在单个超大 `tests/test_memory_service.py`，回归信号不利于定位。

## 3. 拆分原则

### 3.1 保留兼容 facade

短期保留 `agent_core.application.services.memory` 作为兼容入口。

第一阶段拆分后，以下导入方式必须继续可用：

```python
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.memory import MemoryInterpretationResult
from agent_core.application.services.memory import ReflectionCorpusResult
from agent_core.application.services.memory import MemoryMaintenanceBatchResult
from agent_core.application.services.memory import LongTermMemoryUpsertResult
```

原因很明确：当前 `planner`、`reflection`、`workspace`、`memory_maintenance`、`long_term_memory_materialization`、API dependencies、tests 都直接依赖 `memory.py` 的 service 或结果 dataclass。

最终状态不是马上删除 `memory.py`，而是：

- `memory.py` 保留为兼容 facade。
- `MemoryService` 保留 public API。
- 其内部实现逐步委托到拆出的窄模块。
- 顶层 dataclass 改为从新模块 re-export。

### 3.2 按业务边界拆，不按行数平均拆

每个新模块必须有明确所有权：

- 只处理结果类型。
- 只处理质量规则。
- 只处理 event record。
- 只处理 long-term upsert。
- 只处理 retrieval。
- 只处理 browse / detail 查询。
- 只处理 evidence。
- 只处理 governance。
- 只处理 batch / compression。
- 只处理 conflict。
- 只处理 interpretation。
- 只处理 reflection corpus。
- 只处理 observability。

禁止新建 `utils.py`、`helpers.py` 这类无所有权模块去继续堆积逻辑。

### 3.3 不与现有已拆模块重叠

当前已经存在：

- `memory_normalization.py`
- `memory_conflict_policy.py`
- `memory_extraction.py`
- `long_term_memory_materialization.py`
- `long_term_memory_materialization_replay.py`
- `memory_maintenance.py`

拆分 `memory.py` 时不得把这些已清晰存在的边界重新吸回去，也不应该重复实现它们的逻辑。

原则：

- 能复用现有模块的继续复用。
- 仅提取 `memory.py` 内部仍然拥挤的职责。
- 不在拆分中把 materialization orchestrator、maintenance worker service 再次混入新的“大内核模块”。

### 3.4 治理路径不能弱化

拆分不得改变以下约束：

- 自动 materialization 仍然只创建或刷新低信任 governed memory，不直接写 `active` / `stable`。
- `suppressed` / `archived` memory 不能被普通 upsert、replay、batch 或 compression 自动恢复。
- quality / readiness 缺证据时必须 fail-closed。
- reflection outcome bridge 只能写受控 evidence 和 candidate，不得绕过治理状态。
- operator suppress / restore / annotate 仍必须写 audit。
- conflict refresh、promotion、demotion、archive 的高风险状态变化仍必须保留 durable evidence。

### 3.5 事务边界不在拆分中隐式改变

拆分阶段只移动逻辑，不新增隐藏 `commit()`，不改变 repository update 顺序，不把 audit-required path 改成 best effort。

如果后续需要调整 transaction owner，必须作为独立重构处理，并补 rollback / partial failure 测试。

### 3.6 Python 包命名必须避开 `memory.py` 冲突

由于当前已经存在 `application/services/memory.py`，不能再在同级创建同名 `memory/` 包。

建议新增子包：

```text
packages/agent_core/src/agent_core/application/services/learner_memory/
```

这样可以：

- 避开 import resolution 冲突。
- 保留 `memory.py` 兼容入口。
- 明确这是 Memory 领域的内部模块集合，而不是新建一个与旧模块竞争的平行入口。

## 4. 目标目录结构

建议新增子包：

```text
packages/agent_core/src/agent_core/application/services/learner_memory/
  __init__.py
  constants.py
  result_types.py
  quality.py
  session_events.py
  candidate_builders.py
  upsert.py
  retrieval.py
  catalog.py
  evidence.py
  governance.py
  governance_batches.py
  conflicts.py
  interpretation.py
  reflection_corpus.py
  observability.py
```

保留兼容文件：

```text
packages/agent_core/src/agent_core/application/services/memory.py
```

短期最终状态：

- `memory.py` 继续定义 `MemoryService`。
- `MemoryService` 内部只保留 wiring / orchestration / compatibility wrapper。
- dataclass 与纯逻辑常量改为从 `learner_memory/*` 导入。
- 逐步把 public methods 的主体逻辑委托给对应子模块。

## 5. 模块职责设计

### 5.1 `learner_memory/constants.py`

承载 `memory.py` 顶部与 Memory Service 强相关的常量和权重 dataclass。

建议迁入：

- `KnowledgeEvidenceWeights`
- `BehaviorEvidenceWeights`
- `KNOWLEDGE_EVIDENCE_WEIGHTS`
- `BEHAVIOR_EVIDENCE_WEIGHTS`
- 仅属于 service 层的默认阈值和状态集合

边界要求：

- 只放常量、权重和默认阈值。
- 不放 repository / service / audit 逻辑。
- 已在 `memory_conflict_policy.py` 中的冲突规则继续留在原模块，不重复定义。

### 5.2 `learner_memory/result_types.py`

承载当前 `memory.py` 中的服务级结果 dataclass。

建议迁入：

- `LongTermMemoryWriteResult`
- `LongTermMemoryUpsertResult`
- `MemoryMaintenanceResult`
- `MemoryMaintenanceBatchResult`
- `MemoryConflictMemberDetail`
- `ReflectionCorpusMemoryItem`
- `ReflectionCorpusSummary`
- `ReflectionCorpusResult`
- `BrowseMemoriesResult`
- `MemoryGovernanceSummary`
- `MemoryInterpretationFact`
- `MemoryInterpretationResult`

边界要求：

- 只定义结果类型。
- 不包含行为逻辑和 repository 依赖。
- `memory.py` 顶层继续 re-export，保证外部导入不破。

### 5.3 `learner_memory/quality.py`

承载纯 quality / readiness 逻辑。

建议迁入：

- `_knowledge_quality_score`
- `_behavior_quality_score`
- `_quality_tier`
- `_knowledge_promotion_readiness`
- `_behavior_promotion_readiness`
- `_quality_reasons`
- `_memory_quality_snapshot_sync`
- `_governance_pressure`
- `_review_recommended`

职责：

- 根据 memory 当前字段计算 quality score、tier、promotion readiness、reason codes。
- 生成纯数据 quality snapshot。

边界要求：

- 不做 repository 读取。
- 不做状态变更。
- 不写 audit。
- 必须保持确定性，便于 fixture-based regression。

### 5.4 `learner_memory/session_events.py`

承载 session event 记录与 event-level embedding 协调。

建议迁入：

- `record_session_event` 主体逻辑。
- `_build_event_summary`
- `_build_profile_summary`
- `_build_tags`
- `_infer_struggle_note`
- `_infer_progress_note`
- `_infer_concept_focus`

职责：

- 生成 session / profile memory event。
- 写 event embedding。
- 记录 event 成功 / 失败 audit。

边界要求：

- 只处理 event 级别写入和 event metadata。
- 不构造 long-term knowledge / behavior memory。
- 不做 long-term governance 决策。

### 5.5 `learner_memory/candidate_builders.py`

承载 long-term memory candidate 构建与 topic 对齐辅助逻辑。

建议迁入：

- `build_knowledge_memory_candidate`
- `build_behavior_memory_candidate`
- `extract_learning_signals`
- `_build_knowledge_memory`
- `_build_behavior_memory`
- `_build_memory_details`
- `_build_knowledge_summary`
- `_build_behavior_summary`
- `_build_behavior_title`
- `_build_behavior_tags`
- `_build_knowledge_tags`
- `_build_behavior_intervention_effect`
- `_classify_knowledge_level`
- `_classify_knowledge_horizon`
- `_classify_behavior_category`
- `_classify_behavior_level`
- `_classify_behavior_horizon`
- `_normalize_key`
- `_topic_tokens`
- `_topic_matches`
- `_topic_alignment_score`

职责：

- 从 chat / task / reflection 等上游输入生成 `KnowledgeMemory` / `BehaviorMemory` candidate。
- 统一 topic key 和基础 metadata 构造。

边界要求：

- 只构造 candidate，不落库。
- 不做 evidence link 写入。
- 不做 promotion / demotion。

### 5.6 `learner_memory/upsert.py`

承载 long-term memory identity lookup、upsert 和 fail-closed refresh 逻辑。

建议迁入：

- `upsert_knowledge_memory`
- `upsert_behavior_memory`
- `_resolve_knowledge_identity_race`
- `_resolve_behavior_identity_race`
- `_record_knowledge_memory`
- `_record_behavior_memory`
- `_merge_knowledge_memory`
- `_merge_behavior_memory`
- `_sync_knowledge_embedding`
- `_sync_behavior_embedding`
- `_has_material_refresh_change`

职责：

- 查找现有 memory identity。
- 做 candidate create / refresh / evidence_only / skipped_suppressed 判定。
- 维护 long-term memory embedding。

边界要求：

- 不决定 `active` / `stable` promotion。
- 不做 conflict batch。
- 必须继续保留 suppressed / archived fail-closed 语义。

### 5.7 `learner_memory/retrieval.py`

承载 session / profile / long-term retrieval。

建议迁入：

- `retrieve_relevant_session_memories`
- `retrieve_relevant_profile_memories`
- `retrieve_relevant_knowledge_memories`
- `retrieve_relevant_behavior_memories`
- `_retrieve_memory_events`
- `_cosine_similarity`
- `_score_long_term_memory`
- `_freshness_decay`
- `_decay_freshness`
- `_clamp_score`

职责：

- 调 embedding provider。
- 做检索候选排序和裁剪。
- 输出 retrieval result。

边界要求：

- 只做 retrieval，不写 memory state。
- provider 失败仍由调用方按现有语义做 durable audit 或 fallback。
- 不引入新的网络路径或真实 provider 依赖。

### 5.8 `learner_memory/catalog.py`

承载 browse / detail / operator read 查询。

建议迁入：

- `get_knowledge_memory`
- `get_behavior_memory`
- `describe_knowledge_memory`
- `describe_behavior_memory`
- `browse_knowledge_memories`
- `browse_behavior_memories`
- `list_evidence_links`
- `list_governance_decisions`
- `list_annotations`
- `list_conflict_sets`
- `list_conflict_members`
- `list_conflict_member_details`

职责：

- 提供 memory 详情、列表、分页、运营读视图。

边界要求：

- 不做状态变更。
- 不写 audit。
- 必须保留 bounded query 和分页语义。

### 5.9 `learner_memory/evidence.py`

承载 evidence 计算和 evidence link upsert。

建议迁入：

- `upsert_session_memory_event_evidence`
- `upsert_task_attempt_evidence`
- `upsert_reflection_outcome_evidence`
- `_upsert_reflection_bridge_evidence`
- `_sync_knowledge_evidence_links`
- `_sync_behavior_evidence_links`
- `_list_relevant_attempts`
- `_get_relevant_mastery`
- `_list_relevant_events`
- `_compute_knowledge_evidence`
- `_compute_behavior_evidence`
- `_compute_knowledge_stability`
- `_compute_behavior_stability`
- `_adjust_knowledge_importance`
- `_adjust_knowledge_confidence`
- `_adjust_behavior_importance`
- `_adjust_behavior_confidence`
- `_merge_unique`
- `_select_highest_level`

职责：

- 从 event / attempt / mastery / reflection 聚合证据。
- 维护 evidence link 和 support / contradiction / stability 相关字段。

边界要求：

- 不做最终 governance transition。
- 不直接做 candidate create。
- evidence 缺失时保持 fail-closed，不制造假强信号。

### 5.10 `learner_memory/governance.py`

承载 operator 状态变更和 governed status transition。

建议迁入：

- `suppress_memory`
- `restore_memory`
- `annotate_memory`
- `_govern_knowledge_status`
- `_govern_behavior_status`
- `_apply_knowledge_status_transition`
- `_apply_operator_status_change`
- `_record_governance_decision`
- `_decision_type_for_transition`
- `_current_knowledge_eligibility`
- `_knowledge_transition_rationale`
- `_knowledge_transition_decision_type`
- `_knowledge_transition_trigger_source`
- `_knowledge_transition_reason_code`
- `_knowledge_transition_reason_note`
- `_knowledge_transition_metrics_snapshot`
- `_promotion_rationale`
- `_validation_status_for_memory`

职责：

- 处理 governed lifecycle transition。
- 记录 governance decision 和 audit 相关元数据。

边界要求：

- 状态变化必须保留现有 allowed / rejected / no-op 语义。
- 不把 operator change 与自动治理规则混成一套模糊逻辑。
- 不在模块内部新增 `commit()`。

### 5.11 `learner_memory/governance_batches.py`

承载 batch 级 governance、compression 和 profile cursor 流程。

建议迁入：

- `run_memory_maintenance`
- `list_maintenance_profile_ids`
- `_run_governance_batch`
- `_refresh_and_govern_memories`
- `_compress_memories_for_profile`
- `_compress_memories`
- `run_knowledge_governance_batch`
- `run_knowledge_promotion_eligibility_batch`
- `run_behavior_governance_batch`
- `compress_knowledge_memories_for_profile`
- `compress_behavior_memories_for_profile`
- `compress_knowledge_memories`
- `compress_behavior_memories`
- `_compress_knowledge_group`
- `_compress_behavior_group`
- `_refresh_knowledge_memory`
- `_refresh_behavior_memory`
- `_refresh_and_govern_knowledge`
- `_refresh_and_govern_behavior`
- `_evaluate_knowledge_promotion_eligibility`
- `_is_knowledge_promotion_candidate`
- `_is_behavior_promotion_candidate`
- `_knowledge_governance_multiplier`
- `_behavior_governance_multiplier`
- `_default_governance_config`
- `_summarize_governance_batch_change`

职责：

- 运行 profile-scoped batch。
- 组织 promotion eligibility、governance、compression 的 cursor 前进逻辑。

边界要求：

- `memory_maintenance.py` 仍然是 worker/job 层 orchestrator。
- 这里不处理 claim / retry / fail / durable job audit。
- batch 逻辑必须保留现有 cursor 语义和 processed / changed 统计。

### 5.12 `learner_memory/conflicts.py`

承载 conflict set 构造、刷新和关闭逻辑。

建议迁入：

- `refresh_conflict_sets_for_profile`
- `refresh_conflict_sets`
- `_upsert_profile_conflict_sets`
- `_close_inactive_conflict_sets`
- `_conflict_member_detail`

职责：

- 维护 open / closed conflict set。
- 构建 operator 可见 conflict detail。

边界要求：

- conflict refresh 只根据证据和可见状态计算，不自动恢复 memory。
- stale close 逻辑必须保持 fail-closed，不误关闭仍然有效的冲突。

### 5.13 `learner_memory/interpretation.py`

承载 planner / workspace / reflection 消费的解释层结果。

建议迁入：

- `build_interpretation`
- `_interpret_knowledge_memory`
- `_interpret_behavior_memory`
- `_interpretation_constraints`
- `_recommended_memory_use`

职责：

- 把 raw memory 转成适合 planner / reflection 使用的解释事实和推荐约束。

边界要求：

- 只读。
- 不写 memory。
- 输出契约要保持与 `application/interfaces/memory.py` 兼容。

### 5.14 `learner_memory/reflection_corpus.py`

承载 reflection corpus 和 governance summary 的构造。

建议迁入：

- `build_reflection_corpus`
- `build_governance_summary`
- `_memory_quality_snapshot`
- `_evidence_mix`
- `_build_reflection_corpus_item`
- `_reflection_priority_score`
- `_reflection_recommended_action`
- `_reflection_rationale`
- `_recommended_action_reason`
- `_topic_bucket_summary`
- `_build_compressed_summary`

职责：

- 为 reflection、operator review、curator evidence 提供结构化 Memory 视图。

边界要求：

- 只读构造。
- 依赖 `quality.py` 的纯规则，不重复实现。
- 输出契约变化必须同步测试，不允许静默漂移。

### 5.15 `learner_memory/observability.py`

承载 Memory observability metric 刷新。

建议迁入：

- `refresh_observability_metrics`

职责：

- 聚合 candidate backlog、open conflicts 等 metrics。

边界要求：

- 只读 repository 聚合并写 metrics。
- 不做治理决策。
- 不写 memory 状态。

## 6. `MemoryService` 最终形态

拆分完成后，`MemoryService` 不应继续承载 5000+ 行内部实现。

推荐形态：

- `MemoryService` 继续存在于 `memory.py`。
- 构造函数依赖保持兼容，不要求所有调用方立刻切换。
- 内部创建或接收以下窄协作者：
  - event recorder
  - candidate builder
  - upsert service
  - retrieval service
  - catalog service
  - evidence service
  - governance service
  - batch governance service
  - conflict service
  - interpretation service
  - reflection corpus service
  - observability service

`MemoryService` 只负责：

- 兼容 public API。
- 组装依赖。
- 协调少量跨模块调用。
- 保留必要的 static/class wrappers 兼容旧测试和旧调用。

特别注意：

- 当前测试直接调用 `MemoryService._topic_matches()`、`MemoryService._topic_alignment_score()`、`MemoryService._default_governance_config()`。
- 拆分后应在 `MemoryService` 中保留薄 wrapper，转调到新模块，而不是直接删除这些静态接口。

## 7. 推荐执行阶段

### Phase 0：校准事实与测试基线

目标：先确认当前 `memory.py` 的真实依赖面和回归基线。

执行：

1. 跑当前 Memory 相关测试：

   ```bash
   python3 -m pytest \
     tests/test_memory_service.py \
     tests/test_memory_maintenance_service.py \
     tests/test_long_term_memory_materialization_replay.py \
     -q
   ```

2. 盘点外部依赖面：

   - `chat.py`
   - `reflection.py`
   - `workspace.py`
   - `memory_maintenance.py`
   - `long_term_memory_materialization.py`
   - `api/routes/memory.py`
   - `api/dependencies.py`
   - `application/interfaces/memory.py`

3. 对齐与 [plan/MEMORY_QUALITY_REGRESSION_PLAN.md](/home/cl/agent-edu/plan/MEMORY_QUALITY_REGRESSION_PLAN.md) 的执行顺序：

   - 先有 regression baseline。
   - 再推进结构拆分。

### Phase 1：先迁结果类型、常量、纯质量逻辑

目标：先把最稳定、风险最低、最适合回归保护的部分挪出去。

执行：

1. 新建 `learner_memory/result_types.py`。
2. 新建 `learner_memory/constants.py`。
3. 新建 `learner_memory/quality.py`。
4. 在 `memory.py` 顶层改为 re-export。
5. 保留 `MemoryService` 静态 wrapper：

   - `_topic_matches`
   - `_topic_alignment_score`
   - `_default_governance_config`
   - 其他被测试或外部直接引用的纯函数入口

测试：

- 先补或执行 fixture-based quality regression。
- 确认 `tests/test_memory_service.py` 中现有 pure behavior 仍能通过。

### Phase 2：迁移只读路径

目标：优先拆出风险较低、事务副作用较少的读取与解释逻辑。

执行：

1. 迁出 `catalog.py`：
   - browse / detail / annotation / governance decision / evidence links / conflict detail 读取
2. 迁出 `retrieval.py`：
   - session / profile / knowledge / behavior retrieval
3. 迁出 `interpretation.py`
4. 迁出 `reflection_corpus.py`
5. 迁出 `observability.py`

边界：

- 不改变 API schema。
- 不改变 retrieval 评分语义。
- 不改变 reflection corpus 排序契约。

### Phase 3：迁移 candidate 构建与 upsert

目标：把 materialization 入口依赖的构建与 upsert 从主文件抽离。

执行：

1. 迁出 `session_events.py`。
2. 迁出 `candidate_builders.py`。
3. 迁出 `upsert.py`。

重点保护：

- `LongTermMemoryMaterializationService` 现有调用面不变。
- suppressed / archived fail-closed 继续成立。
- identity race 处理不回退。
- embedding 同步与错误 audit 行为不变。

### Phase 4：迁移 evidence、governance、conflicts、batches

目标：收口真正高风险的 governed write 和批处理逻辑。

执行：

1. 迁出 `evidence.py`。
2. 迁出 `governance.py`。
3. 迁出 `conflicts.py`。
4. 迁出 `governance_batches.py`。

重点保护：

- operator suppress / restore / annotate 语义不变。
- governance decision audit 不减弱。
- promotion eligibility 与 cursor batch 行为不漂移。
- compression 不误恢复 source memory。
- conflict refresh 不误关闭仍有效冲突。

### Phase 5：瘦身 `MemoryService`

目标：让 `memory.py` 从“巨型实现文件”降为“兼容 facade + 轻编排层”。

执行：

1. 删除已迁出逻辑的旧实现。
2. `MemoryService` 构造函数内部组装窄协作者。
3. public methods 改为直接委托。
4. 保留结果类型和必要 helper 的兼容导出。

完成后，`memory.py` 应主要包含：

- imports
- compatibility exports
- `MemoryService` 构造函数
- 少量 public wrapper / static wrapper

## 8. 预计技术难点

### 8.1 外部导入面广

问题：

- `memory.py` 被 application service、API、container、tests 多处直接引用。
- 不只是 `MemoryService`，还有 `MemoryInterpretationResult`、`ReflectionCorpusResult`、`MemoryMaintenanceBatchResult` 等结果类型。

应对：

- `memory.py` 保留兼容 re-export。
- 不在第一阶段批量修改外部导入点。
- 先移动实现，再在后续独立 PR 中考虑收敛导入路径。

### 8.2 `MemoryService` 当前既是 facade 又是实现体

问题：

- 直接删改容易让所有 public methods 同时受影响。

应对：

- 先抽纯逻辑与只读路径。
- 再用委托替换方法主体。
- 不一次性重写整个构造和注入方式。

### 8.3 测试直接依赖 private static helpers

问题：

- 现有测试直接断言 `_topic_matches`、`_topic_alignment_score`、`_default_governance_config`。

应对：

- 保留 wrapper。
- 等 regression fixtures 稳定后，再单独评估是否迁移测试。

### 8.4 governed write 与 batch 逻辑强耦合

问题：

- evidence、governance、compression、conflict refresh 之间共享大量内部 helper。

应对：

- 先抽 `quality.py` 和 `result_types.py`。
- 再按“写前计算 / 状态转移 / batch orchestration”拆。
- 允许短期保留少量共享私有 helper，但必须归属明确模块。

### 8.5 下游 contract 漂移风险高

问题：

- reflection corpus、governance summary、workspace memory summary 都依赖结构化结果。

应对：

- 结合 Memory regression plan，优先为这些输出建立 contract tests。
- 拆分时只移动代码，不主动改字段命名和统计口径。

## 9. 是否需要同步重构测试

需要，但应是“保护式重构”，不是“大换血”。

建议：

1. 保留现有：
   - `tests/test_memory_service.py`
   - `tests/test_memory_maintenance_service.py`
   - `tests/test_long_term_memory_materialization_replay.py`

2. 同步新增：
   - `tests/test_memory_quality_regression.py`
   - `tests/test_memory_fail_closed.py`
   - `tests/test_memory_downstream_contracts.py`

3. 中期再拆分现有超大测试文件：
   - 将 pure quality / pure builder / pure retrieval 场景外移
   - 让 `tests/test_memory_service.py` 只保留 service orchestration 主路径

## 10. 推荐实施顺序与验收标准

推荐顺序：

1. 先执行 [plan/MEMORY_QUALITY_REGRESSION_PLAN.md](/home/cl/agent-edu/plan/MEMORY_QUALITY_REGRESSION_PLAN.md) 的 baseline 部分。
2. 再做 `result_types.py`、`constants.py`、`quality.py`。
3. 再迁只读路径。
4. 再迁 candidate / upsert。
5. 最后迁 governance / conflicts / batches。

这样安排的原因：

- 先有测试护栏，再拆高风险治理代码，回归可控。
- 先迁纯逻辑和只读路径，风险最低。
- 最晚动 governed write 和 batch，避免在无基线时误伤生产语义。

## 11. 交付条件

完成标准：

1. `memory.py` 不再继续承载 5000+ 行业务实现。
2. `MemoryService` public API 兼容。
3. `MemoryInterpretationResult`、`ReflectionCorpusResult`、`MemoryMaintenanceBatchResult`、`LongTermMemoryUpsertResult` 等外部导入不破。
4. suppressed / archived / contested fail-closed 规则在拆分后回归通过。
5. retrieval、reflection corpus、governance summary、batch cursor 语义未漂移。
6. `memory_maintenance.py`、`long_term_memory_materialization.py`、`chat.py`、`reflection.py` 的现有调用方式不需要同步大改。
7. 默认测试路径不依赖真实 provider。

推荐验收命令：

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

## 12. 第一阶段建议直接执行的拆分范围

如果下一步就开始实现，建议先做最安全、收益最高的一批：

1. 新增 `learner_memory/result_types.py`
2. 新增 `learner_memory/constants.py`
3. 新增 `learner_memory/quality.py`
4. `memory.py` 顶层改为兼容导出
5. 为 `MemoryService` 保留静态 wrapper
6. 新增 fixture-based quality regression tests

原因：

- 这一步几乎不涉及事务和 DB 写路径。
- 但能立即降低主文件噪音。
- 也能为后续拆 governed write 建立稳定基础。
