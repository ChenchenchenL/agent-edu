# backend.md

# Backend Rules

These rules apply to backend implementation paths, including FastAPI routes,
application services, workers, repositories, workflow orchestration, and
memory/reflection/evolution execution flows.

`backend.md` is the primary execution rule source for backend code changes.
Use `security.md` for deeper auth, secret, and approval-safety requirements.
Use `testing.md` for test expectations. Use `review.md` for review posture.

---

## API Boundaries

- Validate all external input.
- Treat user input, webhook payloads, tool output, model output, and retrieved
  content as untrusted data.
- In Python/FastAPI, use `pydantic` models for request and response boundaries
  whenever the payload is structured.
- Do not pass raw `dict[str, Any]` across service boundaries when a stable
  schema is warranted.
- Return consistent error shapes.
- Keep routes thin: accept input, enforce access control, call services,
  commit/rollback, and map responses.
- Do not put business decisions, lifecycle transitions, or multi-step
  orchestration in routes.

---

## Layering And Coupling

- Domain logic must remain framework-agnostic.
- Domain code must not depend directly on FastAPI, SQLAlchemy sessions, Redis,
  HTTP clients, or model provider SDKs.
- Application services may depend on domain code and explicit interfaces, not
  on transport-layer request/response concerns.
- Infrastructure code implements storage, network, and provider integrations;
  it must not own business policy.
- Routes should call services, not repositories, unless the path is a tightly
  bounded read-only exception with no business logic.
- Do not call another service's private methods.
- Temporary callbacks used during refactors are migration bridges, not
  long-term architecture. Do not spread new callback dependencies when a direct
  service contract is more appropriate.

---

## Services And Workflow Orchestration

- Business logic belongs in services, use-cases, workflows, or domain
  transitions.
- Repositories persist and load data; they do not make approval, permission,
  or lifecycle decisions.
- Keep orchestration logic separate from pure domain logic.
- Make side effects explicit in service boundaries.
- When a method mixes core state writes with follow-up coordination, split the
  code into explicit phases such as `core write` and `post-update` or
  `post-commit coordination`.
- Model output and tool output must be validated and normalized before they can
  influence governed writes or privileged behavior.

---

## Transactions, Rollback, And Side Effects

- Every write path must have a clear transaction owner.
- By default, transaction ownership belongs to the request-scoped application
  boundary or explicit unit-of-work boundary, not to ad hoc helper code.
- HTTP routes may trigger final `commit()` or `rollback()` only as thin
  transport adapters for that boundary; they must not become the place where
  transaction policy lives.
- Services must not perform hidden `commit()` calls unless the service is
  explicitly designed as the transaction or unit-of-work boundary.
- On write-path errors, rollback must happen before the exception leaves the
  application boundary that owns the transaction.
- Core state mutations, required audit writes, and mandatory pre-transition
  checks must complete before commit.
- Do not commit state and then perform additional required side effects that
  can fail and leave the system inconsistent.
- If later coordination can fail independently, either keep it in the same
  transaction, use a savepoint, or defer it to an explicit post-commit job or
  coordination path.
- Do not hide side effects in helpers with unclear transaction behavior.

---

## Audit And Identity Propagation

- Operator or actor identity must be derived from the authenticated request or
  access context and passed through to the service layer.
- Do not hardcode operator, actor, or system identities in routes or services
  when a real authenticated identity exists.
- Do not log raw secrets, API keys, or tokens. When identity tracing requires a
  stable identifier, use a safe derived identifier rather than the raw secret.
- Audit-relevant actions must not silently skip logging.
- Sensitive backend paths should record audit events, including high-risk
  writes, governed lifecycle actions, tool execution, and access denials where
  applicable.
- If a path requires audit as part of its contract, audit failure must not be
  treated as success.

---

## Repository And Query Rules

- Never run migrations unless asked.
- Avoid N+1 queries.
- Prefer explicit selects and explicit loaded relations.
- Use parameterized queries.
- Keep persistence models from leaking into UI contracts.
- Do not use unbounded list queries on request paths or worker hot paths.
- List and browse queries should expose `limit`, pagination, or a clearly
  bounded filter.
- Prefer repository-level filtering, aggregation, and existence checks over
  loading batches into memory and filtering in Python.
- Add focused repository methods for cases such as recent items, max-version,
  count, or existence checks instead of reusing broad list APIs for everything.
- Raw SQL is allowed only when ORM/query-builder paths are insufficient and the
  reason is justified in the change.

---

## State Transitions, Idempotency, And Concurrency

- Governed status changes must go through service or domain transition methods,
  not ad hoc field assignment in routes, jobs, or repositories.
- Each lifecycle transition should define allowed source states, required
  validation, and idempotency behavior.
- Before deactivation, archival, replacement, or similar destructive lifecycle
  steps, check for active references or in-flight dependencies when applicable.
- Repeated operations must have clear semantics: reject, no-op, or refresh
  metadata. Do not hide repeated actions behind ambiguous event names.
- Worker and scheduler code must define reentry behavior. Use leases, locks,
  compare-and-set updates, or equivalent guards when duplicate execution would
  corrupt state.
- Retry paths must be safe against duplicate side effects.

---

## Reuse, Abstraction, And Splitting

- Extract shared logic when the same business or governance semantics appear in
  three or more places, or when drift would create audit, permission, or
  lifecycle inconsistencies.
- Do not abstract small local differences just to remove a few repeated lines.
- Do not create catch-all utility modules with unclear ownership.
- Introduce a `Protocol` or similar interface when multiple implementations,
  test substitution, or cross-module contracts justify the abstraction.
- Do not add empty wrapper layers that only forward calls without clarifying a
  boundary.
- Avoid adding new responsibilities to known god objects or oversized modules
  when the behavior can be placed in a narrower service.

---

## Size And Complexity Thresholds

- Keep functions and methods under 80 effective lines by default.
- Keep nesting depth to 4 levels or fewer.
- Keep ordinary backend files under 800 lines by default.
- Files over 1200 lines are refactor candidates. Do not keep adding unrelated
  functionality to them without extracting responsibility or documenting the
  exception in the change.
- Keep service constructor dependency counts under 15.
- Keep single classes under 20 public methods by default.
- Crossing a threshold does not require instant large-scale rewrites, but new
  changes must avoid making the oversize area worse without a clear reason.

---

## Python Backend Conventions

- Python backend functions, methods, variables, and fields use `snake_case`.
- Public interfaces and service/domain/repository code must use explicit type
  hints.
- Do not spread `Any` through core business logic; confine it to boundary or
  adapter cases where it is genuinely necessary.
- Prefer `async/await` for I/O-heavy paths when the runtime supports it.
- Use Google-style docstrings for public service entrypoints, protocol methods,
  repository public methods, and complex orchestration methods.
- Private short helpers do not need docstrings if the code is self-explanatory.
- When comments are needed, explain why the code exists or what invariant it
  protects, not what each line does.

---

## Forbidden

- No business logic in routes, controllers, or endpoints.
- No hidden side effects.
- No direct approval, audit, or safety bypasses.
- No unvalidated model output written directly into long-term memory.
- No hidden `commit()` ownership.
- No unbounded list queries on critical paths.
- No repository-layer permission or lifecycle policy decisions.
- No cross-service private-method calls.
