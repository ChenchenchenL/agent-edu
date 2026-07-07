# Quiz Adaptive Memory Skill Enhancement Plan

## 1. 目标

当前系统已经具备 session memory、long-term memory candidate、reflection evidence、skill usage、curator 和 governed evolution 链路，但普通 quiz 答题还不是一等公民证据源。现状的 mastery 更新主要来自 `DailyTask` 的 `completed / failed / skipped` 终态，而不是每一道题的答题表现。

本计划目标是补齐以下闭环：

`quiz question -> answer attempt -> grading evidence -> topic/subskill mastery -> adaptive quiz policy -> reflection evidence -> memory candidate -> skill outcome feedback -> governed skill evolution`

落地后，系统应支持：

- 用户每次答题都有结构化、可审计的 attempt evidence。
- mastery 可以由题目级证据增量更新，而不是只靠任务终态。
- 下一次 quiz 可以按当前掌握度、近期错误、提示依赖和策略卡自动调整题目难度与题型。
- 答题失败、重复 misconception、提示后仍失败等信号能进入反思系统。
- skill router 和 skill curator 能看到 learning gain，而不是只看到运行成功率。
- LLM 批改结果不会直接写入高信任长期记忆或生产 skill 行为，仍然走 evidence、governance、reflection、proposal、sandbox、approval 路径。

## 2. 当前实现边界

### 2.1 已实现基础

- `QuizService.generate_quiz()` 会生成 `SessionQuiz` 和 `SessionQuizQuestion`。
- chat/hint 路径会写 `SessionMessage`、`MemoryEvent`，并尝试 materialize long-term memory candidate。
- `DailyTask` 状态更新会写 `TaskAttempt`，并更新 `LearnerTopicMastery`。
- `GoalAutonomyState.mastery_snapshot` 会保存 goal 下 topic mastery 摘要。
- review scheduling 会根据 mastery、confidence、recent failures 选择复习间隔。
- assessment generation 会根据 mastery 阈值和 strategy/rollout bias 决定是否生成 assessment。
- reflection evidence 已覆盖 session turn、task attempt、workflow run。
- skill runtime 已具备 capability/router/artifact/binding/template/tool-plan/usage attribution。
- skill curator/outcome feedback 已能根据 usage、artifact quality、memory conflict、reflection outcome、coverage drift 等生成 recommendation。

### 2.2 缺口

- 没有正式的 `SessionQuizAnswerAttempt` 持久化模型。
- 普通 quiz 的 learner answer 没有稳定的提交和批改 API。
- `LearnerTopicMastery` 没有题目级更新入口。
- `QuizService.generate_quiz()` 不读取 mastery 来自动调整 difficulty/question mix。
- skill router 虽有 `mastery_band/mastery_fit` 字段，但当前调用端基本未传入真实 mastery band。
- reflection evidence 没有专门建模 answer attempt 的 misconception、hint-after-failure、adaptive mismatch 等信号。
- skill outcome signal 缺少 mastery delta、hint dependency delta、answer correctness delta 等 learning gain 指标。

## 3. 设计原则

1. Grading output is evidence, not truth.
   LLM 或规则批改结果只能成为 `AnswerAttempt` evidence，不能直接写 active/stable memory，也不能直接改变 production skill registry。

2. Mastery update must be deterministic.
   mastery 更新策略必须在 domain/application service 中实现，不能由 LLM 自由决定分数变化。

3. Memory remains governed.
   answer attempt 可以生成 long-term memory candidate，但 promotion/suppression 仍由 memory governance job 执行。

4. Reflection remains bounded.
   answer attempt 可以触发 reflection evidence，但 reflection depth、dedupe、cooldown、needs_review 规则不能绕过。

5. Skill evolution remains governed.
   skill recommendation、proposal、sandbox、evaluation、approval、staging、activation/replacement 必须沿用既有治理路径。

6. Minimal runtime coupling.
   quiz 自适应策略应作为独立 application service，不应把大量业务逻辑塞进 route 或 LLM provider。

## 4. Phase 1: 答题提交与批改证据

### 4.1 数据模型

新增 `SessionQuizAnswerAttempt` domain entity 和 DB model。

建议字段：

- `id`
- `session_id`
- `quiz_id`
- `question_id`
- `learner_profile_id`
- `learner_goal_id`
- `daily_task_id`
- `topic_key`
- `subskill_keys`
- `question_prompt`
- `reference_answer`
- `learner_answer`
- `grading_status`: `graded / rejected / needs_review`
- `grading_source`: `deterministic / llm / hybrid`
- `score`: `0.0 - 1.0`
- `is_correct`
- `confidence`
- `rubric_feedback`
- `misconception_codes`
- `hint_used`
- `hint_count`
- `attempt_number`
- `metadata`
- `created_at`
- `updated_at`

Repository requirements:

- `create()`
- `get_by_id()`
- `list_by_quiz()`
- `list_recent_by_goal_topic()`
- `count_by_question()`
- bounded query limits on request and worker paths

### 4.2 API

新增 API:

`POST /api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts`

Request:

- `learner_answer`
- `hint_used`
- `hint_count`
- optional `client_context`

Response:

- attempt id
- score
- is_correct
- rubric feedback
- misconception codes
- updated topic mastery snapshot
- recommended next action: `continue / review / request_hint / easier_question / assessment_ready`

安全要求：

- route 只做 schema validation、access control、service call、commit/rollback。
- learner identity/profile/goal 必须从 session/authorized context 派生，不能信任客户端传入。
- 批改失败时 rollback attempt core write，或明确使用 split-phase durable failure record。
- 所有批改和 mastery 更新要有 audit。

### 4.3 Grading Service

新增 `AnswerGradingService`。

批改策略：

- 客观题或短答案优先 deterministic grading。
- 开放题使用 LLM structured output。
- LLM 输出必须经过 Pydantic/schema validation。
- validation failed 时 attempt 标为 `needs_review` 或拒绝，不更新 mastery。

输出结构：

- `score`
- `is_correct`
- `confidence`
- `rubric_feedback`
- `misconception_codes`
- `reasoning_quality`
- `needs_human_review`

禁止：

- LLM 直接返回 mastery delta。
- LLM 直接写 memory。
- LLM 直接触发 skill proposal。

### 4.4 测试

新增测试：

- API success path。
- question/session/quiz 不匹配时拒绝。
- invalid answer payload 拒绝。
- deterministic grading。
- LLM grading schema invalid 时 fail closed。
- grading service failure rollback。
- audit write failure 不返回成功。

## 5. Phase 2: 题目级 Mastery 更新

### 5.1 Domain 策略

扩展 `LearnerTopicMastery`：

- 新增 `update_from_question_attempt()`。
- 输入必须是结构化 `QuestionAttemptMasteryEvidence`，不要传 raw dict。

建议 evidence 字段：

- `topic_key`
- `subskill_keys`
- `score`
- `is_correct`
- `difficulty`
- `hint_used`
- `hint_count`
- `attempt_number`
- `confidence`
- `misconception_codes`

建议规则：

- 高难度答对提升更大。
- 低难度答错降低更明显。
- hint 后答对的 mastery gain 折扣。
- 多次 attempt 后才答对的 gain 折扣。
- 同一 misconception 连续出现时增加 contradiction pressure。
- confidence 低时降低 mastery delta 权重。

### 5.2 Service 集成

新增或扩展 `QuizAttemptService`：

1. 校验 session/quiz/question ownership。
2. 调用 `AnswerGradingService`。
3. 写 `SessionQuizAnswerAttempt`。
4. 更新 `LearnerTopicMastery`。
5. 刷新 `GoalAutonomyState.mastery_snapshot`。
6. 写 audit。
7. 派生 reflection evidence。
8. 可选调度 memory materialization replay 或直接 candidate materialization。

事务边界：

- attempt write、mastery update、required audit 必须同事务。
- long-term memory materialization 可用 savepoint 或 post-commit replay job，避免副作用失败破坏核心答题提交。

### 5.3 测试

新增测试：

- correct answer increases mastery。
- wrong answer decreases or holds mastery according to policy。
- hint-used correct answer produces smaller gain。
- repeated misconception produces stronger reflection evidence。
- mastery snapshot refreshed。
- transaction rollback preserves consistency。

## 6. Phase 3: Adaptive Quiz Policy

### 6.1 新增服务

新增 `AdaptiveQuizPolicyService`。

输入：

- learner profile id
- learner goal id
- session id
- topic key
- requested difficulty/question count
- current `LearnerTopicMastery`
- recent answer attempts
- active `StrategyCard`
- long-term memory interpretation
- rollout overlay/runtime directives

输出：

- effective difficulty
- question count
- topic/subskill distribution
- remediation focus
- desired misconception probes
- feedback style
- skill directives
- adaptation rationale

### 6.2 QuizService 集成

`QuizService.generate_quiz()` 在调用 LLM provider 前：

1. 读取 adaptive policy。
2. 合并 runtime directives。
3. 形成 effective quiz request。
4. 将 adaptation rationale 写入 audit 和 skill usage metadata。

覆盖规则：

- 用户显式 difficulty 是偏好，不是强制值。
- 如果 mastery 很低，系统可以降难度并增加 scaffolded questions。
- 如果 mastery 高且 confidence 高，系统可以提高难度或减少复习题。
- 如果近期同一 misconception 重复出现，优先生成 targeted remediation question。

### 6.3 推荐 mastery band

建议映射：

- `remedial`: mastery < 0.45 或 recent failures >= 2
- `reinforced`: mastery < 0.65
- `standard`: mastery < 0.75
- `stable`: mastery >= 0.75 且 confidence >= 0.65
- `advanced`: mastery >= 0.85 且 confidence >= 0.75 且 evidence_count >= 4

### 6.4 测试

新增测试：

- low mastery lowers difficulty。
- high mastery raises or preserves difficulty。
- repeated misconception changes topic/subskill mix。
- strategy card `difficulty_bias=supportive` affects policy。
- rollout runtime directives override default policy only when allowed。
- audit includes adaptation rationale。

## 7. Phase 4: Answer Attempt Memory Bridge

### 7.1 Materialization

扩展 `LongTermMemoryMaterializationService`：

- 新增 `materialize_from_answer_attempt()`。
- 只创建/刷新 `KnowledgeMemory` 和 `BehaviorMemory` candidate。
- provenance type 使用 `quiz_answer_attempt`。

候选示例：

- Knowledge candidate: "Learner struggles with matrix row-column multiplication alignment."
- Behavior candidate: "Learner often submits short guesses before requesting hints."

### 7.2 Evidence Link

扩展 `MemoryEvidenceLink` 支持：

- `evidence_source_type="quiz_answer_attempt"`
- payload 包含 score、difficulty、misconception codes、hint count、question id。

### 7.3 Governance

保持现有规则：

- candidate 不直接注入 learner-facing context。
- active/stable 由 maintenance governance 决定。
- contested/conflict-heavy 不直接注入 chat context。

### 7.4 测试

新增测试：

- answer attempt creates candidate only。
- suppressed memory 不被自动恢复。
- evidence link provenance 指向 attempt id。
- materialization failure schedules replay/durable audit。

## 8. Phase 5: Answer Attempt Reflection

### 8.1 Evidence Signal

扩展 `ReflectionEvidenceService`：

新增 `derive_from_answer_attempt()`。

建议 signal codes：

- `repeated_misconception`
- `hint_after_wrong_answer`
- `low_mastery_high_difficulty_mismatch`
- `assessment_regression_from_quiz`
- `short_guess_answer`
- `quiz_strategy_failure`

### 8.2 Trigger Policy

扩展 reflection trigger policy：

- 同 topic 连续 N 次 wrong answer。
- 同 misconception 连续出现。
- mastery 低但系统连续生成高难度题。
- hint_count 高且答题仍失败。
- 某 skill artifact 在 topic 上失败率持续高。

### 8.3 Reflection Actions

可能动作：

- enqueue review scheduling。
- enqueue assessment generation。
- enqueue partial replan。
- update strategy card candidate。
- enqueue skill curator review。

高风险动作继续进入 `needs_review`。

### 8.4 测试

新增测试：

- repeated misconception creates aggregate reflection。
- cooldown/dedupe 生效。
- high-risk action goes to needs_review。
- low-risk review scheduling job is idempotent。

## 9. Phase 6: Mastery-Aware Skill Routing

### 9.1 Router Request

扩展 runtime resolution：

- 在 `DynamicRuntimeRegistryService.resolve_capability_request()` 前解析当前 topic mastery。
- 将 mastery 转成 `mastery_band`。
- 传入 `SkillRouterRequest.mastery_band`。

### 9.2 Candidate Match Rules

允许 skill artifact 在 `match_rules` 或 compatibility contract 中声明：

- supported mastery bands
- excluded mastery bands
- topic/subskill coverage
- remediation capability

router ranker 使用 `mastery_fit` 影响总分。

### 9.3 Fallback

如果 mastery 缺失：

- 使用 `standard` 或 `unknown` band。
- 不因为缺 mastery 阻断 baseline builtin。
- audit/router decision metadata 记录 `mastery_band_missing`。

### 9.4 测试

新增测试：

- low mastery selects remedial artifact when eligible。
- high mastery avoids remedial-only artifact。
- missing mastery falls back safely。
- staged artifact 不因 mastery fit 绕过 `include_staged=False`。

## 10. Phase 7: Skill Outcome Learning Gain

### 10.1 Usage Signal 增强

扩展 `SkillUsageEvent.outcome_signals`：

- `mastery_before`
- `mastery_after`
- `mastery_delta`
- `answer_correctness_delta`
- `hint_dependency_delta`
- `misconception_reduction`
- `accepted_by_user`
- `user_correction_requested`

### 10.2 Aggregator

扩展 `SkillOutcomeAggregator`：

- 计算 learning gain rate。
- 区分 runtime success 和 learning success。
- 对低 failure 但低 learning gain 的 artifact 标记 review。

### 10.3 Curator

扩展 curator recommendation：

- `patch_needed` when learning gain low。
- `demote_candidate` when high runtime success but poor learning outcome。
- `promote_candidate` should require minimum learning gain evidence where available。

### 10.4 测试

新增测试：

- positive mastery delta improves artifact quality。
- high completion but negative learning gain creates review recommendation。
- missing learning gain does not crash existing curator path。

## 11. Phase 8: API/UI/Operator Observability

### 11.1 Learner-Facing API

新增或扩展：

- quiz attempt history。
- current topic mastery read endpoint。
- next recommended action。
- explanation of adaptation rationale，避免暴露内部 governance 细节。

### 11.2 Operator-Facing API

新增或扩展：

- answer attempt browse。
- grading needs_review queue。
- misconception trend。
- adaptive policy audit trail。
- skill learning gain dashboard input。

### 11.3 Metrics

新增指标：

- quiz attempt count。
- grading failure rate。
- schema validation failure rate。
- mastery delta distribution。
- adaptive difficulty changes。
- repeated misconception rate。
- answer-attempt memory materialization failure rate。
- skill learning gain rate。

## 12. 迁移与兼容

### 12.1 Migration

新增 alembic migration：

- `session_quiz_answer_attempts`
- indexes:
  - `(session_id, quiz_id)`
  - `(learner_goal_id, topic_key, created_at)`
  - `(question_id, attempt_number)`
  - `(grading_status, created_at)`

### 12.2 Backfill

不强制 backfill 历史普通 chat/hint 为 answer attempts。

可选后续 backfill：

- 从带 `related_quiz_id/question_prompt/learner_answer` 的 session messages 中生成 low-confidence historical attempts。
- backfilled attempts 不直接更新 mastery，只作为历史 evidence candidate。

### 12.3 Compatibility

- 原 `/quizzes/generate` 保持可用。
- 没有 answer attempts 时，系统退回现有 task-level mastery 行为。
- 没有 mastery 时，adaptive policy 使用 safe default。

## 13. 风险与控制

### 13.1 主要风险

- LLM 批改错误污染 mastery。
- 题目级更新导致 mastery 波动过大。
- 自适应策略过度降难度，用户无法进阶。
- answer attempt 生成过多 memory candidate，增加 governance backlog。
- skill curator 误把短期波动当成 skill 退化。

### 13.2 控制措施

- 批改 confidence 低时不更新 mastery 或降低权重。
- mastery delta 设置上下限。
- 连续证据和 confidence 才允许大幅调整。
- answer-attempt memory materialization 采样或阈值触发。
- curator 使用窗口聚合和 minimum evidence count。
- 所有高风险 skill/action 仍需 sandbox/approval/readiness。

## 14. 推荐实施顺序

1. Phase 1: 答题提交与批改证据。
2. Phase 2: 题目级 mastery 更新。
3. Phase 3: Adaptive quiz policy。
4. Phase 5: Answer attempt reflection。
5. Phase 4: Answer attempt memory bridge。
6. Phase 6: Mastery-aware skill routing。
7. Phase 7: Skill outcome learning gain。
8. Phase 8: Observability/API polish。

原因：

- 先建立可信 evidence 源，再让 mastery 和 adaptive policy 消费。
- reflection 可以较早接入，因为它只产生 evidence/action，不直接改变 production skill。
- memory bridge 放在 mastery 后，避免过早扩大 candidate backlog。
- skill routing 和 curator learning gain 依赖前面 answer attempt/mastery 数据稳定。

## 15. Definition of Done

### 15.1 功能完成

- 普通 quiz answer attempt 可提交、批改、审计、查询。
- mastery 可由题目级 attempt 更新。
- quiz generation 可根据 mastery 和 recent attempts 自动调整 effective difficulty/question mix。
- answer attempt 可生成 reflection evidence。
- answer attempt 可生成 governed memory candidate。
- skill usage 记录 learning gain。
- skill router 可消费 mastery band。

### 15.2 安全完成

- LLM grading output schema validation 全覆盖。
- untrusted grading output 不直接写 active/stable memory。
- untrusted grading output 不直接触发 production skill mutation。
- reflection/evolution 仍走 depth/dedupe/cooldown/sandbox/approval/readiness。
- audit failure 在 required path 上 fail closed。

### 15.3 测试完成

- Unit tests: grading policy、mastery update、adaptive policy、mastery band mapping。
- Service tests: attempt submit、transaction rollback、audit behavior、reflection evidence、memory candidate。
- API tests: validation、not found、ownership mismatch、success response。
- Worker/job tests: materialization replay、curator learning gain aggregation。
- Docker integration tests: answer attempt -> mastery -> adaptive quiz -> reflection evidence happy path。

## 16. 建议新增测试文件

- `tests/test_quiz_answer_attempts.py`
- `tests/test_answer_grading_service.py`
- `tests/test_quiz_mastery_update.py`
- `tests/test_adaptive_quiz_policy.py`
- `tests/test_answer_attempt_memory_bridge.py`
- `tests/test_answer_attempt_reflection.py`
- `tests/test_mastery_aware_skill_router.py`
- `tests/test_skill_learning_gain_feedback.py`

