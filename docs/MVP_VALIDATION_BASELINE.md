# MVP Validation Baseline

This document is the single source of truth for the MVP release gate. It
records what to run, what each layer verifies, and how to triage failures.

Last updated: P2 completion (runtime protection + quiz observability).

## 1. Command Ladder

Commands are layered so developers can run the cheapest useful check and
release engineering can run the full gate.

| Target | Scope | Typical duration | When to use |
|---|---|---|---|
| `make mvp-smoke` | `test_mvp_acceptance.py` only | ~2s | During development; fast feedback on the main chain. |
| `make mvp-regression` | acceptance + api_integration + worker_runtime + task_runtime_skill | ~20s | Before opening a PR; covers core backend regression. |
| `make mvp-check` | `mvp-regression` + `docker-api-test` | ~30s | Default local release gate. |
| `make frontend-build` | `tsc -b && vite build` | ~2s | After any frontend change. |
| `make release-check` | `lint` + `frontend-build` + `mvp-check` | ~35s | Full release gate (no Docker blackbox). |
| `make docker-mvp-check` | HTTP-only blackbox against running stack | ~variable | After stack is up with mock provider. See §4. |
| `make real-provider-regression` | Gated real-provider chain | variable | Only with `AGENT_EDU_RUN_REAL_PROVIDER_REGRESSION=1`. |

## 2. Test Layers

### 2.1 Service / unit layer

- `tests/test_quiz_answer_attempts.py`
- `tests/test_answer_grading_service.py`
- `tests/test_adaptive_quiz_policy.py`
- `tests/test_answer_attempt_memory_bridge.py`
- `tests/test_answer_attempt_reflection.py`
- `tests/test_phase6_mastery_routing.py`
- `tests/test_phase7_learning_gain.py`
- `tests/test_embedding_circuit_breaker.py`
- `tests/test_runtime_protection_alert_bridge.py`

### 2.2 API integration layer

- `tests/test_api_integration.py`
- `tests/test_phase8_observability_api.py`
- `tests/test_error_contract.py`
- `tests/test_rate_limit_security.py`

### 2.3 MVP acceptance layer

- `tests/test_mvp_acceptance.py` — single chained test covering
  profile → goal → plan → task → session → chat/hint/quiz → answer attempt →
  operator observability → memory → worker → audit.

### 2.4 Worker / job layer

- `tests/test_worker_runtime.py`
- `tests/test_task_runtime_skill.py`
- `tests/test_memory_maintenance_service.py`

### 2.5 Frontend layer

- `packages/frontend/src/api/client.test.ts` — error contract.
- `packages/frontend/src/pages/learning/components/*.test.tsx` — quiz feedback, question card, quiz panel.

### 2.6 Docker blackbox layer

- `tests/test_docker_blackbox.py` — HTTP smoke against running API.
- `tests/test_mvp_blackbox.py` — HTTP-only MVP main path.

### 2.7 End-to-end contract smoke

- `tests/e2e_quiz_contract_smoke.py` — 27 contract checks against a live API.

## 3. Current Baseline (recorded at P2 completion)

```
Backend in-process:   1091 passed, 1 skipped, 14 warnings
Frontend test:run:    24 passed (4 files)
Frontend build:       OK (tsc -b && vite build)
Frontend lint:        0 errors, 7 warnings (react-hooks/exhaustive-deps class)
MVP acceptance:       1 passed (strengthened with P0/P1 chain)
MVP regression:       43 passed (acceptance + api_integration + worker + task)
E2E contract smoke:   27 passed (against mock-provider API)
```

## 4. Docker Blackbox Limitation

`docker compose`'s `.env` file takes precedence over `--env-file`. In the
current dev setup, `.env` pins `AGENT_EDU_LLM_PROVIDER=dashscope_compatible`,
so the Docker blackbox inherits real-provider settings and becomes slow /
credential-dependent.

Workaround:

```bash
cp .env.example .env.blackbox
# edit .env.blackbox: set AGENT_EDU_LLM_PROVIDER=mock, etc.
docker compose --env-file .env.blackbox up -d postgres redis api
docker compose --env-file .env.blackbox --profile test run --rm \
    -e AGENT_EDU_API_BASE_URL=http://api:8000 \
    tester pytest tests/test_mvp_blackbox.py -q
```

Until the compose stack supports a dedicated blackbox profile,
`docker-mvp-check` is not included in `release-check`.

## 5. Failure Triage Order

When a check fails, use this order to locate the layer:

1. **API / readiness**: `curl /healthz` and `/readyz`, then `docker compose logs api`.
   Typical causes: DB down, migration not applied, settings missing.
2. **Worker / job**: search audit for `autonomy.job.*`, `memory_maintenance.job.*`,
   `skill_curator.job.failed`. Check `attempt_count` and `lease_owner`.
3. **Memory / reflection / skill**: search audit for `memory.*`,
   `reflection.*`, `skill.*`. Verify schema stability; MVP does not require
   production-grade quality, only stable shape and no write failures.
4. **Frontend spinner**: check `VITE_API_BASE_URL` / dev proxy, browser
   network tab, React Query error / empty handling.
5. **Provider**: only relevant for `real-provider-regression`; classify as
   credential / network / timeout / rate-limit / contract-drift.

## 6. Invariants Enforced by the Baseline

- Default path does not depend on real LLM / embedding providers.
- One command (`make release-check`) runs the full local gate.
- Every protected path has an audit assertion.
- Operator key is supplied via env, never hard-coded.
- No `sleep` or flaky timing in any test.
- No test shortcut bypasses auth, audit, approval, or governed lifecycle.

## 7. Related Documents

- `docs/DOCKER_VALIDATION.md` — Docker validation and observability runbook.
- `docs/AGENT_EDU_MVP_GAPS.md` — MVP gap tracker (G1/G3/G4/G5 closed, G2 partial).
- `docs/QUIZ_ATTEMPT_OBSERVABILITY_CONTRACT.md` — frozen API contract for
  quiz attempt + observability endpoints.
- `plan/MVP_VALIDATION_BASELINE_PLAN.md` — original plan.
- `plan/COST_RATE_LIMIT_CIRCUIT_BREAKER_ALERTING_PLAN.md` — P2 runtime protection.
