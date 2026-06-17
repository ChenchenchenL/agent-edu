# testing.md

# Testing Rules

These rules apply to backend services, Web frontend code, workers, tools,
memory/reflection/evolution flows, and governed runtime paths.

`testing.md` defines minimum testing requirements.
If behavior changes, governed state transitions change, security boundaries
change, or transaction behavior changes, testing obligations apply.

Pure documentation or rule-file changes do not require tests by default.
If a documentation change also changes implementation behavior, acceptance
criteria, or expected operating procedure, add the relevant validation or state
clearly what was not run.

---

## Scope And Testing Policy

- Add tests for new business logic.
- Update tests when behavior changes.
- Prefer tests that exercise real application behavior over implementation
  details.
- Prioritize risk coverage over superficial coverage volume.
- Do not treat coverage percentages as a substitute for critical-path
  validation.

---

## Test Layers And Ownership

- Use unit tests for pure domain logic, validation logic, normalization logic,
  and deterministic transformations.
- Use integration tests for service behavior, repositories, transactions,
  audit behavior, permissions, and worker coordination.
- Use scenario or end-to-end style tests for user-visible workflows, governed
  lifecycle flows, API contracts, and blackbox validation.
- Do not rely on a large number of shallow tests to stand in for missing
  critical-path coverage.
- High-risk behavior must be covered by at least one realistic test layer.

---

## Backend Testing Requirements

- Service changes must cover success paths and failure paths.
- API or route changes must cover authentication, authorization, validation,
  error mapping, and transaction outcome behavior where relevant.
- Repository changes must cover query boundaries such as filtering, limits,
  pagination, aggregation, or existence checks where relevant.
- State-transition changes must cover allowed, rejected, and idempotent
  behavior.
- Transaction and side-effect ordering changes must test consistency, not just
  happy-path completion.
- Audit and durable-failure paths must be tested when they are part of the
  contract.

---

## Frontend Testing Requirements

- Add tests for complex Web interactions and stateful UI flows.
- Cover loading, empty, error, and permission-denied states when UI behavior
  changes.
- Test forms, filters, pagination, confirmation flows, and mutation feedback
  when those behaviors are added or changed.
- Prefer tests that exercise user-visible behavior over implementation details.
- Do not use snapshot-heavy tests as a substitute for real interaction
  coverage.
- Frontend testing requirements apply even if the exact future test tooling is
  still undecided.

---

## Security And Permission Testing

- Test authentication failures and authorization failures.
- Test learner, operator, and other protected identity boundaries where they
  affect behavior.
- Test fail-closed behavior on protected paths.
- Test rejection of unsafe, unvalidated, or policy-disallowed inputs when those
  paths are security-relevant.
- Test approval, sandbox, readiness, rollout, and other governed gate denials
  when those paths are changed.
- Do not ship high-risk changes with success-path-only security coverage.

---

## Lifecycle And Governance Testing

- Test governed lifecycle transitions for memory, reflection proposals,
  rollouts, skill artifacts, and curator recommendations when their behavior
  changes.
- Cover allowed transitions, rejected transitions, repeated operations, and
  boundary conditions.
- Test suppression, rollback, replacement, archive, and restore safety rules
  when those paths change.
- Test that failed governed actions retain the correct pending or blocked state
  when that behavior is part of the contract.
- Do not rely on manual reasoning alone for lifecycle-heavy changes.

---

## Worker, Job, And Concurrency Testing

- Test worker success paths and failure paths.
- Test retry, lease recovery, idempotency, duplicate execution, or reentry
  protection where applicable.
- Test partial-failure recovery when the worker or job contract supports it.
- Test state progression consistency for scheduled jobs, maintenance jobs,
  sandbox jobs, or curator jobs when their logic changes.
- Do not ignore concurrency risks just because they are hard to reproduce
  manually.

---

## Data Integrity And Transaction Testing

- Test commit and rollback boundaries when write behavior changes.
- Test savepoint or same-transaction protection when that logic is introduced
  or modified.
- Test that required side effects do not leave committed state inconsistent when
  they fail.
- Test durable audit behavior when the path depends on it for failure
  visibility.
- Test split-phase write flows to confirm the final persisted state under both
  success and failure conditions.

---

## Test Quality And Determinism

- Keep tests deterministic.
- Mock minimally.
- Avoid snapshot abuse.
- Use fixtures, fakes, or stubs for model providers and external tools in
  default test paths.
- No flaky tests.
- No sleeping or time-based hacks.
- No random test data without a seed.
- No default test path that requires live external services or live model
  providers.

---

## Coverage Priorities

Highest priority:

- permissions and protected identity boundaries
- governed state transitions
- transaction integrity and rollback behavior
- audit and durable-failure behavior
- failure recovery and fail-closed behavior

Medium priority:

- query boundaries
- UI loading and error states
- tool output and model output validation

Lower priority:

- trivial accessors
- obvious framework glue with no meaningful branching

Do not replace high-risk coverage with easy low-value tests.

---

## Required Scenarios Checklist

Must cover when applicable:

- success path
- validation error
- auth rejected or permission denied
- not found
- duplicate or idempotent request
- rollback or partial failure
- concurrency or reentry behavior
- loading, empty, and error UI states
- governed gate denial

---

## Non-Default Validation Paths

- Default test paths should not depend on live external providers.
- Docker blackbox validation is a higher-level supplemental path for API
  contract, container integration, and cross-layer behavior checks.
- Real-provider regression is a gated supplemental path for provider
  integrations, prompt/output contracts, and real external behavior checks.
- These supplemental paths are not required for every change by default.
- When a change materially affects those surfaces, evaluate whether the
  supplemental path should be run and state the result clearly.

---

## Forbidden

- No happy-path-only test coverage for high-risk changes.
- No flaky tests.
- No sleeping or time-based hacks.
- No default-path dependency on live providers.
- No snapshot-heavy pseudo coverage in place of real behavior checks.
- No mocking of domain logic as a substitute for testing behavior.
- No skipping regression coverage for high-risk state, permission, audit, or
  lifecycle changes.
