# Quiz Attempt & Observability API Contract

Frozen contract for the quiz attempt submission flow and operator/learner observability endpoints. Frontend and operator UI consume these endpoints; backend must not change shape without a coordinated version bump.

## 1. Learner-Facing Endpoints

### 1.1 Submit Answer Attempt

```
POST /api/v1/sessions/{session_id}/quizzes/{quiz_id}/questions/{question_id}/attempts
```

**Request body** (`SubmitAnswerAttemptRequest`):

| Field | Type | Constraint |
|---|---|---|
| `learner_answer` | string | `min_length=1, max_length=4000` |
| `hint_used` | bool | default `false` |
| `hint_count` | int | `ge=0, le=20`, default `0` |
| `client_context` | object \| null | optional opaque client metadata |
| `grading_strategy` | string | enum `deterministic \| llm \| hybrid`, default `hybrid` |

**Response** (`AnswerAttemptResponse`, status `201`):

```json
{
  "attempt_id": "string",
  "session_id": "string",
  "quiz_id": "string",
  "question_id": "string",
  "attempt_number": 1,
  "grading": {
    "grading_status": "graded | needs_review | rejected",
    "grading_source": "deterministic | llm | hybrid | null",
    "score": 0.0,
    "is_correct": true,
    "confidence": 0.9,
    "rubric_feedback": "string | null",
    "misconception_codes": ["string"],
    "needs_human_review": false
  },
  "mastery_snapshot": {
    "topic_key": "string",
    "mastery_score": 0.65,
    "confidence": 0.7,
    "evidence_count": 5,
    "last_attempt_status": "string | null",
    "last_assessed_at": "ISO8601 | null"
  },
  "recommended_next_action": "continue | review | request_review | request_hint | easier_question | assessment_ready | generate_quiz | review_scheduling",
  "created_at": "ISO8601"
}
```

**Error codes**:

| Status | Meaning |
|---|---|
| `404` | session / quiz / question not found or not owned by learner |
| `422` | request body validation failure |
| `500` | unexpected server error (attempt NOT committed) |

**Transaction contract**:

- `attempt` write + required audit `quiz.answer_attempt.submitted` are in the **same transaction**.
- `commit()` happens after both succeed.
- `skill_usage` recording is best-effort (failure does not roll back attempt).
- `reflection_evidence` and `long_term_memory_materialization` run **after commit** in their own savepoints; failures are logged and surfaced via durable audit, never as HTTP errors.

### 1.2 Learner Attempt History

```
GET /api/v1/quizzes/attempts/history?limit=100&offset=0
```

Response: `{ "attempts": [ObservabilityAttemptRecord] }`

### 1.3 Learner Topic Mastery

```
GET /api/v1/learner/mastery/{topic_key}
```

Response: `TopicMasteryResponse` — always returns a value (defaults to `0.0` when no mastery exists).

### 1.4 Learner Next Action

```
GET /api/v1/quizzes/next-action
```

Response: `{ "recommended_next_action": "review_scheduling | generate_quiz", "rationale": "string" }`

### 1.5 Quiz Adaptation Rationale

```
GET /api/v1/quizzes/rationale/{quiz_id}
```

Response: `{ "quiz_id": "string", "adaptation_rationale": "string" }`

Returns `404` if quiz not found or not owned by the caller's learner profile.

## 2. Operator-Facing Endpoints

All require `X-Operator-Key` header matching `AGENT_EDU_OPERATOR_API_KEY`.

### 2.1 Browse Attempts

```
GET /api/v1/operator/quizzes/attempts?limit=100&offset=0
```

Response: `{ "attempts": [ObservabilityAttemptRecord], "total_count": int }`

### 2.2 Grading Queue

```
GET /api/v1/operator/quizzes/grading/needs-review?limit=100&offset=0
```

Response: `{ "queue": [ObservabilityAttemptRecord] }`

### 2.3 Misconception Trend

```
GET /api/v1/operator/quizzes/misconceptions/trend?limit=1000
```

Response: `{ "trends": [{ "misconception_code": "string", "count": int }] }`

Windowed estimate over the most recent `limit` attempts. Sorted by count descending in the UI.

### 2.4 Adaptive Policy Audit Trail

```
GET /api/v1/operator/quizzes/adaptive-policy/audit?limit=100&offset=0
```

Response: `{ "audit_trail": [AdaptivePolicyAuditRecord] }`

### 2.5 Learning Gain Dashboard

```
GET /api/v1/operator/skills/learning-gain?limit=1000
```

Response: `{ "learning_gains": [{ "skill_name": "string", "average_learning_gain": float, "sample_size": int }] }`

Windowed estimate over the most recent `limit` skill usage events.

## 3. Shared Record Shapes

### ObservabilityAttemptRecord

```json
{
  "id": "string",
  "session_id": "string",
  "quiz_id": "string",
  "question_id": "string",
  "score": "float | null",
  "is_correct": "bool | null",
  "misconception_codes": ["string"],
  "created_at": "ISO8601"
}
```

### AdaptivePolicyAuditRecord

```json
{
  "id": "string",
  "event_type": "string",
  "resource_id": "string | null",
  "event_data": {},
  "created_at": "ISO8601"
}
```

## 4. Invariants

1. **Ownership is server-derived.** `learner_profile_id`, `learner_goal_id`, `daily_task_id`, `topic_key`, `subskill_keys` are all derived from the learning session and quiz, never from the client payload.
2. **Grading output is evidence, not truth.** `grading_status="needs_review"` means the result does not update mastery and does not trigger downstream automation.
3. **LLM output is Pydantic-validated.** Schema-invalid LLM output becomes `grading_status="needs_review"` with `validation_error` populated; it never silently poisons mastery.
4. **Audit fail-closed.** Required audit failure rolls back the attempt. Post-commit diagnostic audit failure is logged and durable-audited, never surfaced as HTTP error.
5. **Pagination is bounded.** `limit` is clamped server-side (attempts: 1000; misconceptions/gains: 10000).
6. **Recommended next action is deterministic.** Given the same `(grading_status, is_correct, hint_used, hint_count, attempt_number)` tuple, the same action is returned.

## 5. Frontend Consumption

- Types: `packages/frontend/src/types/quiz.ts` (learner), `packages/frontend/src/types/quiz-observability.ts` (operator).
- Hooks: `useSubmitAnswerAttempt`, `useOperatorAttempts`, `useMisconceptionTrend`, `useLearningGainDashboard`, etc.
- Pages: `packages/frontend/src/pages/learning/components/quiz-panel.tsx` (learner), `packages/frontend/src/pages/operator/{quiz-attempts,misconceptions,learning-gains}-page.tsx` (operator).

## 6. Change Policy

Any change to:

- field names,
- field types,
- enum values,
- HTTP status codes,
- transaction semantics,

requires:

1. Update this document.
2. Update `packages/frontend/src/types/{quiz,quiz-observability}.ts`.
3. Update `packages/agent_core/src/agent_core/domain/schemas/quiz.py`.
4. Add or update tests in `tests/test_quiz_answer_attempts.py` and `tests/test_phase8_observability_api.py`.
5. Run `tests/e2e_quiz_contract_smoke.py` against a live API.
