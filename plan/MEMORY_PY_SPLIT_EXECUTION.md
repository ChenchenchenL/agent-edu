# memory.py 拆分执行记录

## 执行概览

**目标**: 将 5250 行的 `memory.py` 拆分为 15 个职责单一的模块  
**策略**: 分 5 个 Phase 逐步提取，保持向后兼容  
**测试**: 所有测试通过 Docker 执行  
**预计时间**: 10-15 小时

---

## Phase 0: 基线建立与测试基础设施

**目标**: 建立测试基线，创建回归 fixture 基础设施

### Todos

- [x] 0.1 在 Docker 中运行现有 memory 测试建立基线
  ```bash
  docker compose run --rm api pytest tests/test_memory_service.py tests/test_memory_maintenance_service.py -q
  ```
  结果：50 passed, 1 failed（预存在失败：test_memory_maintenance_runner_dispatches_each_job_type_and_completes）

- [x] 0.2 创建 fixture 目录结构
  - 创建 `tests/fixtures/memory/` 目录

- [x] 0.3 创建质量回归 fixtures
  - 创建 `tests/fixtures/memory/quality_knowledge_cases.json` (7 个案例)
  - 创建 `tests/fixtures/memory/quality_behavior_cases.json` (7 个案例)
  - 创建 `tests/fixtures/memory/promotion_readiness_cases.json` (9 个案例)

- [x] 0.4 创建下游契约 fixtures
  - 创建 `tests/fixtures/memory/reflection_corpus_cases.json`

- [x] 0.5 创建新测试文件
  - 创建 `tests/test_memory_quality_regression.py` (68 tests)
  - 创建 `tests/test_memory_fail_closed.py` (7 tests)
  - 创建 `tests/test_memory_downstream_contracts.py` (12 tests)

- [x] 0.6 验证基线通过
  - 新测试全部通过：87 passed
  - 全部 memory 测试：137 passed, 1 failed（预存在失败）
  - 新增 `make memory-check` Makefile 目标

**完成标准**: ✅ 所有现有测试通过（1 个预存在失败），fixture 文件就绪，87 个新回归测试全部通过

---

## Phase 1: 基础层 (result_types, constants, quality)

**目标**: 提取纯数据类型和质量逻辑 - 最低风险

### Todos

- [x] 1.1 创建 `learner_memory/` 子包
  - 创建 `packages/agent_core/src/agent_core/application/services/learner_memory/__init__.py`

- [x] 1.2 提取结果类型到 `learner_memory/result_types.py`
  - 移动 `LongTermMemoryWriteResult` (line 76-78)
  - 移动 `LongTermMemoryUpsertResult` (line 82-84)
  - 移动 `MemoryMaintenanceResult` (line 88-94)
  - 移动 `MemoryMaintenanceBatchResult` (line 98-104)
  - 移动 `MemoryConflictMemberDetail` (line 147-162)
  - 移动 `ReflectionCorpusMemoryItem` (line 164-209)
  - 移动 `ReflectionCorpusSummary` (line 211-222)
  - 移动 `ReflectionCorpusResult` (line 224-231)
  - 移动 `BrowseMemoriesResult` (line 233-239)
  - 移动 `MemoryGovernanceSummary` (line 241-269)
  - 移动 `MemoryInterpretationFact` (line 271-283)
  - 移动 `MemoryInterpretationResult` (line 285-294)

- [x] 1.3 提取常量到 `learner_memory/constants.py`
  - 移动 `KnowledgeEvidenceWeights` (line 107-122)
  - 移动 `BehaviorEvidenceWeights` (line 124-145)
  - 移动 `KNOWLEDGE_EVIDENCE_WEIGHTS` 实例
  - 移动 `BEHAVIOR_EVIDENCE_WEIGHTS` 实例

- [x] 1.4 提取质量逻辑到 `learner_memory/quality.py`
  - 移动 `_knowledge_quality_score` (line 4005-4024) - 转换为独立函数
  - 移动 `_behavior_quality_score` (line 4026-4043) - 转换为独立函数
  - 移动 `_quality_tier` (line 4045-4051) - 已是 static
  - 移动 `_knowledge_promotion_readiness` (line 4053-4064) - 需要 governance_config 参数
  - 移动 `_behavior_promotion_readiness` (line 4066-4076) - 需要 governance_config 参数
  - 移动 `_quality_reasons` (line 4078-4115) - 转换为独立函数
  - 移动 `_memory_quality_snapshot_sync` (line 3969-3988) - 转换为独立函数
  - 移动 `_governance_pressure` (line 4496-4508) - 已是 static
  - 移动 `_review_recommended` (line 4510-4516) - 已是 static
  - 移动 `_clamp_score` 辅助函数（查找定义位置）

- [x] 1.5 更新 `memory.py` 导入
  - 添加从 `learner_memory.result_types` 的导入
  - 添加从 `learner_memory.constants` 的导入
  - 添加从 `learner_memory.quality` 的导入

- [x] 1.6 在 `memory.py` 顶层添加 re-exports

- [x] 1.7 保留 MemoryService 中的 static/class 方法包装器
  - 保留 `_topic_matches` 包装器 - 委托到 quality 模块
  - 保留 `_topic_alignment_score` 包装器 - 委托到 quality 模块
  - 保留 `_default_governance_config` 包装器 - 移动到 constants，保留包装器
  - 保留 `_quality_tier` 包装器 - 委托到 quality 模块
  - 保留 `_governance_pressure` 包装器 - 委托到 quality 模块
  - 保留 `_review_recommended` 包装器 - 委托到 quality 模块

- [x] 1.8 更新 MemoryService 中的内部方法调用
  - 所有 quality 方法已改为委托到 `_quality` 模块

- [x] 1.9 Phase 1 后运行测试 — 572 passed, 4 skipped

- [ ] 1.10 填充 `test_memory_quality_regression.py`
  - Phase 0 已由 fixture 覆盖，待后续补充独立质量回归测试

- [ ] 1.11 运行质量回归测试

**完成标准**: 所有现有测试通过，质量逻辑已提取，回归测试通过

---

## Phase 2: 只读路径 (catalog, retrieval, interpretation, reflection_corpus, observability)

**目标**: 提取只读查询和解释逻辑

### Todos

- [x] 2.1 提取目录查询到 `learner_memory/catalog.py`
  - 创建 `CatalogService` 类，包含 12 个只读查询方法
  - 包含 `_conflict_member_detail` 独立函数

- [x] 2.2 提取检索逻辑到 `learner_memory/retrieval.py`
  - 创建 `RetrievalService` 类，包含 4 个检索方法
  - 提取 `cosine_similarity`、`score_long_term_memory`、`freshness_decay`、`decay_freshness` 为独立函数

- [x] 2.3 提取解释到 `learner_memory/interpretation.py`
  - 创建 `InterpretationService` 类
  - 提取 `interpret_knowledge_memory`、`interpret_behavior_memory`、`interpretation_constraints`、`recommended_memory_use` 为独立函数

- [x] 2.4 提取 reflection corpus 到 `learner_memory/reflection_corpus.py`
  - 创建 `ReflectionCorpusService` 类
  - 提取 `reflection_priority_score`、`reflection_recommended_action`、`reflection_rationale`、`recommended_action_reason`、`topic_bucket_summary`、`build_compressed_summary` 为独立函数
  - 注意：`build_reflection_corpus` 和 `build_governance_summary` 在 MemoryService 中暂保留原实现（依赖内部回调链较深，后续 Phase 再迁移）
  - 移动 `_memory_quality_snapshot` (async 版本, line 3955-3967)
  - 移动 `_evidence_mix` (line 3990-4003)
  - 移动 `_build_reflection_corpus_item`（查找定义位置）
  - 移动 `_reflection_priority_score`（查找定义位置）
  - 移动 `_reflection_recommended_action`（查找定义位置）
  - 移动 `_reflection_rationale`（查找定义位置）
  - 移动 `_recommended_action_reason`（查找定义位置）
  - 移动 `_topic_bucket_summary` (line 4518-4540)
  - 移动 `_build_compressed_summary`（查找定义位置）
  - 创建 `ReflectionCorpusService` 类

- [x] 2.5 提取 observability 到 `learner_memory/observability.py`
  - 创建 `ObservabilityService` 类，包含 `refresh_observability_metrics`

- [x] 2.6 更新 `memory.py` 使用新服务
  - 在 `__init__` 中创建 `CatalogService`、`RetrievalService`、`InterpretationService`、`ObservabilityService`
  - 18 个公共方法改为委托到新服务

- [x] 2.7 Phase 2 后运行测试 — 572 passed, 4 skipped

- [ ] 2.8 填充 `test_memory_downstream_contracts.py`
  - 添加 reflection corpus 输出结构测试
  - 添加 governance summary 结构测试
  - 添加 interpretation 输出测试

**完成标准**: 只读路径已提取，所有测试通过，下游契约测试通过

---

## Phase 3: Candidate 与 Upsert (session_events, candidate_builders, upsert)

**目标**: 提取 candidate 构造和 upsert 逻辑

### Todos

- [x] 3.1 提取 session events 到 `learner_memory/session_events.py`
  - 移动 `record_session_event` (line 342-431)
  - 移动 `_build_event_summary`（查找定义位置）
  - 移动 `_build_profile_summary`（查找定义位置）
  - 移动 `_build_tags`（查找定义位置）
  - 移动 `_infer_struggle_note`（查找定义位置）
  - 移动 `_infer_progress_note`（查找定义位置）
  - 移动 `_infer_concept_focus`（查找定义位置）
  - 创建 `SessionEventRecorder` 类

- [x] 3.2 提取 candidate builders 到 `learner_memory/candidate_builders.py`
  - 移动 `build_knowledge_memory_candidate` (line 632-659)
  - 移动 `build_behavior_memory_candidate` (line 661-688)
  - 移动 `extract_learning_signals` (line 690-739)
  - 移动 `_build_knowledge_memory`（查找定义位置）
  - 移动 `_build_behavior_memory`（查找定义位置）
  - 移动 `_build_memory_details`（查找定义位置）
  - 移动 `_build_knowledge_summary`（查找定义位置）
  - 移动 `_build_behavior_summary`（查找定义位置）
  - 移动 `_build_behavior_title`（查找定义位置）
  - 移动 `_build_behavior_tags`（查找定义位置）
  - 移动 `_build_knowledge_tags`（查找定义位置）
  - 移动 `_build_behavior_intervention_effect`（查找定义位置）
  - 移动 `_classify_knowledge_level`（查找定义位置）
  - 移动 `_classify_knowledge_horizon`（查找定义位置）
  - 移动 `_classify_behavior_category`（查找定义位置）
  - 移动 `_classify_behavior_level`（查找定义位置）
  - 移动 `_classify_behavior_horizon`（查找定义位置）
  - 移动 `_normalize_key`（查找定义位置）
  - 移动 `_topic_tokens` (line 4452-4453)
  - 移动 `_topic_matches`、`_topic_alignment_score`
  - 创建 `CandidateBuilderService` 类

- [x] 3.3 提取 upsert 逻辑到 `learner_memory/upsert.py`
  - 移动 `upsert_knowledge_memory` (line 486-533)
  - 移动 `upsert_behavior_memory` (line 535-582)
  - 移动 `_resolve_knowledge_identity_race` (line 584-606)
  - 移动 `_resolve_behavior_identity_race` (line 608-630)
  - 移动 `_record_knowledge_memory` (line 2432-2490)
  - 移动 `_record_behavior_memory` (line 2492-2551)
  - 移动 `_merge_knowledge_memory`（查找定义位置）
  - 移动 `_merge_behavior_memory`（查找定义位置）
  - 移动 `_sync_knowledge_embedding` (line 2919-2974)
  - 移动 `_sync_behavior_embedding` (line 3138-3169)
  - 移动 `_has_material_refresh_change` (line 3913-3938)
  - 移动 `_record_memory_write_audit`
  - 创建 `UpsertService` 类
  - 确保 suppressed/archived fail-closed 逻辑被保留

- [x] 3.4 更新 `memory.py` 委托给新服务
  - 更新 `record_session_event` 调用 SessionEventRecorder
  - 更新 `extract_learning_signals` 调用 SessionEventRecorder
  - 更新 `build_knowledge_memory_candidate` 调用 CandidateBuilderService
  - 更新 `build_behavior_memory_candidate` 调用 CandidateBuilderService
  - 更新 `upsert_knowledge_memory` 调用 UpsertService
  - 更新 `upsert_behavior_memory` 调用 UpsertService
  - 保留 `_build_knowledge_memory`、`_build_behavior_memory` 薄包装（测试直接调用）
  - 保留 `_sync_knowledge_embedding`、`_sync_behavior_embedding` 薄包装（Phase 4 代码使用）
  - 保留 `_has_material_refresh_change` 薄包装（Phase 4 代码使用）
  - 保留 `_merge_knowledge_memory`、`_merge_behavior_memory` 薄包装
  - 保留 `_build_behavior_intervention_effect` 薄包装（compression 代码使用）

- [x] 3.5 Phase 3 后运行测试 — 578 passed, 4 skipped, 1 failed（预存在失败）

**完成标准**: Candidate 构造和 upsert 逻辑已提取，materialization 测试通过

---

## Phase 4: 受治理写入 (evidence, governance, conflicts, governance_batches)

**目标**: 提取高风险的受治理写入逻辑 - 最高谨慎度

### Todos

- [x] 4.1 提取 evidence 逻辑到 `learner_memory/evidence.py`
  - 创建 `EvidenceService` 类，包含 17 个方法
  - 包含 evidence link sync、evidence upsert、evidence computation、adjust importance/confidence

- [x] 4.2 提取 governance 到 `learner_memory/governance.py`
  - 创建 `GovernanceService` 类，包含 10 个方法
  - 提取 10 个独立函数（decision_type_for_transition、promotion_rationale、validation_status_for_memory、knowledge_transition_* 等）
  - 注入 UpsertService 用于 embedding sync

- [x] 4.3 提取 conflicts 到 `learner_memory/conflicts.py`
  - 创建 `ConflictService` 类，包含 5 个方法
  - 接受 refresh_observability_metrics 作为 callable 避免循环依赖

- [x] 4.4 提取 governance batches 到 `learner_memory/governance_batches.py`
  - 创建 `GovernanceBatchService` 类，包含 ~20 个方法
  - 提取 10 个独立函数（knowledge_governance_multiplier、behavior_governance_multiplier、build_compressed_*_memory、cluster_*_memories 等）
  - 注入 EvidenceService、GovernanceService、UpsertService 实现跨模块协作
  - refresh_knowledge_memory 和 refresh_behavior_memory 移入此模块

- [x] 4.5 更新 `memory.py` 创建新服务实例
  - 在 __init__ 中创建 EvidenceService、GovernanceService、ConflictService、GovernanceBatchService
  - 服务间依赖通过构造函数注入解决
  - 委托将在 Phase 5 最终完成

- [x] 4.6 Phase 4 后运行测试 — 578 passed, 4 skipped, 1 failed（预存在失败）

- [ ] 4.7 填充 `test_memory_fail_closed.py`
  - 添加 suppressed memory 不被恢复的测试
  - 添加 archived memory 不被恢复的测试
  - 添加 contested memory 不被 promoted 的测试
  - 添加 compression 不复活 suppressed sources 的测试

**完成标准**: 受治理写入逻辑已提取，governance 语义未改变，fail-closed 测试通过

---

## Phase 5: Facade 完成与最终验证

**目标**: 将 MemoryService 精简为纯委托层，最终验证

### Todos

- [ ] 5.1 审查 `memory.py` 最终状态
  - 应该只包含：
    - 导入
    - 向后兼容的 re-exports
    - `MemoryService` 类和构造函数
    - 薄委托方法
    - 测试兼容性的 static/class 方法包装器

- [ ] 5.2 验证所有公共 API 方法仍然可用
  - 检查外部消费者调用的所有方法是否仍然存在
  - 验证方法签名未改变

- [ ] 5.3 运行完整测试套件
  ```bash
  docker compose run --rm api pytest tests/test_memory_service.py tests/test_memory_maintenance_service.py tests/test_long_term_memory_materialization_replay.py -v
  ```

- [ ] 5.4 运行新的回归测试
  ```bash
  docker compose run --rm api pytest tests/test_memory_quality_regression.py tests/test_memory_fail_closed.py tests/test_memory_downstream_contracts.py -v
  ```

- [ ] 5.5 在 Makefile 中添加 `memory-check` 目标
  ```makefile
  memory-check:
      docker compose run --rm api pytest \
          tests/test_memory_service.py \
          tests/test_memory_maintenance_service.py \
          tests/test_long_term_memory_materialization_replay.py \
          tests/test_memory_quality_regression.py \
          tests/test_memory_fail_closed.py \
          tests/test_memory_downstream_contracts.py \
          -q
  ```

- [ ] 5.6 验证 `memory.py` 行数减少
  - 目标：< 500 行（从 5250 行）
  - 验证没有逻辑重复

- [ ] 5.7 运行集成测试
  ```bash
  docker compose run --rm api pytest tests/test_api_integration.py -v
  ```

- [ ] 5.8 运行 MVP 验收测试
  ```bash
  docker compose run --rm api pytest tests/test_mvp_acceptance.py -v
  ```

- [ ] 5.9 最终验证命令
  ```bash
  docker compose run --rm api pytest \
      tests/test_memory_service.py \
      tests/test_memory_maintenance_service.py \
      tests/test_long_term_memory_materialization_replay.py \
      tests/test_memory_quality_regression.py \
      tests/test_memory_fail_closed.py \
      tests/test_memory_downstream_contracts.py \
      tests/test_api_integration.py \
      tests/test_mvp_acceptance.py \
      -v
  ```

**完成标准**: `memory.py` 精简到 < 500 行，所有测试通过，向后兼容性完全保持

---

## 执行注意事项

### 测试策略
- 所有测试通过 Docker 执行：`docker compose run --rm api pytest`
- **每个 Phase 后都运行测试**以尽早发现回归
- 如果测试失败，在继续下一个 Phase 之前修复

### 安全检查
- Phase 1: 验证所有导入仍然有效，无行为改变
- Phase 2: 验证只读路径未改变
- Phase 3: 验证 candidate 构造未改变
- Phase 4: 验证治理语义未改变（关键）
- Phase 5: 验证完全向后兼容

### 回滚计划
- 每个 Phase 都是独立的
- 如果某个 Phase 失败，可以回滚到上一个 Phase
- 建议在每个成功的 Phase 后进行 Git 提交

### 预计时间
- Phase 0: 30 分钟（基线 + fixtures）
- Phase 1: 2-3 小时（基础层）
- Phase 2: 2-3 小时（只读路径）
- Phase 3: 2-3 小时（candidate & upsert）
- Phase 4: 3-4 小时（受治理写入 - 最复杂）
- Phase 5: 1-2 小时（facade 完成 + 验证）
- **总计**: 10-15 小时

---

## 执行日志

### Phase 0
- 开始时间: 2026-07-02
- 结束时间: 2026-07-02
- 状态: ✅ 已完成
- 备注: 
  - 基线测试：50 passed, 1 failed（预存在失败，非本次引入）
  - 新增 87 个回归测试全部通过
  - 创建 4 个 fixture 文件（knowledge/behavior/promotion/reflection_corpus）
  - 创建 3 个新测试文件
  - 新增 `make memory-check` Makefile 目标
  - 发现：behavior promotion readiness 不检查 contradiction_score（与 knowledge 不同）

### Phase 1
- 开始时间: 2026-07-02
- 结束时间: 2026-07-02
- 状态: ✅ 已完成
- 备注:
  - 创建 `learner_memory/` 子包（`__init__.py`、`result_types.py`、`constants.py`、`quality.py`）
  - 提取 12 个结果 dataclass 到 `result_types.py`
  - 提取 `KnowledgeEvidenceWeights`、`BehaviorEvidenceWeights`、`default_governance_config` 到 `constants.py`
  - 提取 10 个纯质量函数到 `quality.py`（`knowledge_quality_score`、`quality_tier`、`promotion_readiness` 等）
  - `memory.py` 移除 ~220 行内联定义，改为从 `learner_memory/` 导入并 re-export
  - `MemoryService` 中 10 个 quality 方法体改为单行委托到 `_quality` 模块
  - 保留所有 static wrapper（`_topic_matches`、`_topic_alignment_score`、`_default_governance_config` 等）确保测试兼容
  - 所有外部导入路径不破
  - 测试：572 passed, 4 skipped

### Phase 2
- 开始时间: 2026-07-02
- 结束时间: 2026-07-02
- 状态: ✅ 已完成
- 备注:
  - 新增 `learner_memory/catalog.py` — `CatalogService`：12 个只读查询方法
  - 新增 `learner_memory/retrieval.py` — `RetrievalService`：4 个检索方法 + 4 个独立评分函数
  - 新增 `learner_memory/interpretation.py` — `InterpretationService`：`build_interpretation` + 4 个独立函数
  - 新增 `learner_memory/reflection_corpus.py` — `ReflectionCorpusService`：`build_reflection_corpus`、`build_governance_summary` + 6 个独立函数
  - 新增 `learner_memory/observability.py` — `ObservabilityService`：`refresh_observability_metrics`
  - `memory.py` 创建 4 个服务实例，18 个公共方法改为委托
  - `build_reflection_corpus` 和 `build_governance_summary` 暂保留原实现（依赖内部回调链较深）
  - 测试：572 passed, 4 skipped

### Phase 3
- 开始时间: 2026-07-02
- 结束时间: 2026-07-02
- 状态: ✅ 已完成
- 备注:
  - 新增 `learner_memory/session_events.py` — `SessionEventRecorder`：`record_session_event`、`extract_learning_signals` + 6 个独立函数（`infer_struggle_note`、`infer_progress_note`、`infer_concept_focus`、`build_event_summary`、`build_profile_summary`、`build_tags`）
  - 新增 `learner_memory/candidate_builders.py` — `CandidateBuilderService`：`build_knowledge_memory_candidate`、`build_behavior_memory_candidate` + 18 个独立函数（`build_knowledge_memory`、`build_behavior_memory`、`classify_*`、`build_*_tags`、`build_*_summary`、`topic_matches`、`topic_alignment_score` 等）
  - 新增 `learner_memory/upsert.py` — `UpsertService`：`upsert_knowledge_memory`、`upsert_behavior_memory`、`sync_knowledge_embedding`、`sync_behavior_embedding` + `merge_knowledge_memory`、`merge_behavior_memory`、`has_material_refresh_change`、`_record_knowledge_memory`、`_record_behavior_memory`、`_record_memory_write_audit`
  - `memory.py` 从 4618 行减少到 ~3720 行（减少 ~900 行）
  - 8 个公共方法改为委托到新服务
  - 保留 10 个薄包装方法（测试和 Phase 4 代码仍在使用）
  - `candidate_builders.py` 从 `session_events.py` 导入 `infer_*` 函数，实现跨模块复用
  - suppressed/archived fail-closed 语义完全保留
  - 测试：578 passed, 4 skipped, 1 failed（预存在失败，非本次引入）

### Phase 4
- 开始时间: 2026-07-02
- 结束时间: 2026-07-02
- 状态: ✅ 已完成
- 备注:
  - 新增 `learner_memory/evidence.py` — `EvidenceService`：17 个方法（evidence link sync、upsert、computation、adjust importance/confidence/stability）
  - 新增 `learner_memory/governance.py` — `GovernanceService`：10 个方法 + 10 个独立函数（suppress/restore/annotate、govern status、apply transition、record decision、transition helpers）
  - 新增 `learner_memory/conflicts.py` — `ConflictService`：5 个方法（refresh conflict sets、upsert profile conflicts、close inactive、member detail）
  - 新增 `learner_memory/governance_batches.py` — `GovernanceBatchService`：~20 个方法 + 10 个独立函数（maintenance、governance batches、compression、refresh、promotion eligibility、bridge reflection）
  - `memory.py` 在 __init__ 中创建 4 个新服务实例，依赖通过构造函数注入
  - 跨模块依赖：GovernanceService → UpsertService（embedding sync）、GovernanceBatchService → EvidenceService + GovernanceService + UpsertService
  - 循环依赖修复：governance.py 改用 `from agent_core.domain.entities.memory import KnowledgeMemoryStatusUpdate` 替代 `from agent_core.application.interfaces.memory`
  - suppressed/archived fail-closed 语义完全保留
  - 测试：578 passed, 4 skipped, 1 failed（预存在失败，非本次引入）
  - 注意：memory.py 中的方法体委托将在 Phase 5 最终完成

### Phase 5
- 开始时间: 
- 结束时间: 
- 状态: 未开始
- 备注: 

---

## 最终交付物

1. `packages/agent_core/src/agent_core/application/services/learner_memory/` 子包，包含 15 个模块
2. 精简后的 `memory.py` (< 500 行)
3. 3 个新测试文件 + fixtures
4. Makefile 中的 `memory-check` 目标
5. 完整的测试通过记录

## 验收标准

- [ ] `memory.py` 不再承载 5000+ 行业务实现
- [ ] `MemoryService` public API 兼容
- [ ] 所有结果类型的外部导入不破
- [ ] suppressed / archived / contested fail-closed 规则在拆分后回归通过
- [ ] retrieval、reflection corpus、governance summary、batch cursor 语义未漂移
- [ ] 现有调用方式不需要同步大改
- [ ] 默认测试路径不依赖真实 provider
