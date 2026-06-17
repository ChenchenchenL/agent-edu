# security.md

# Security Rules

These rules apply to Web frontend code, backend APIs, workers, tools,
memory/reflection/evolution flows, and all governed runtime paths.

`security.md` defines non-bypassable safety constraints.
`backend.md` and `frontend.md` define engineering boundaries.
When those files overlap with `security.md`, the stricter security rule wins.

Default posture: fail closed.
If authentication, authorization, audit, approval, readiness, allowlist, or
governance evidence is missing or invalid, do not continue into the risky path.

---

## Scope And Security Model

- Treat security boundaries as explicit system behavior, not as optional review
  advice.
- High-risk actions must be authenticated, authorized, auditable, attributable,
  and interruptible.
- Safety, approval, and governance flows must be modeled explicitly in code
  flow; they must not live only in comments or operator convention.
- Do not trade away governance for convenience on production paths.
- Default to blocking or degrading safely when a security precondition fails.

---

## Secrets And Sensitive Data

- Never expose secrets.
- Never commit credentials.
- Never log tokens, passwords, API keys, session secrets, or raw access keys.
- Do not return raw secrets in API responses, UI payloads, error bodies, audit
  data, or debug output.
- When identity tracing needs a stable identifier, derive a safe identifier
  from the secret instead of storing or emitting the secret itself.
- Do not expose internal prompts, approval notes, governance internals, or
  unnecessary internal identifiers to frontend clients or external callers.

---

## Authentication And Authorization

- Always verify permissions.
- Always authenticate operator actions explicitly.
- Protect admin routes and operator actions.
- Protect memory mutation, approval, rollout, replacement, and evolution
  actions with explicit authorization.
- Keep learner, operator, and system identities distinct.
- Do not hardcode operator, actor, or system identities when a real
  authenticated actor exists.
- Do not allow fallback logic, default contexts, or debug shortcuts to degrade
  a protected path into anonymous or implicit privileged access.
- Never trust frontend auth state as the source of truth.
- Authorization failures must fail closed.

---

## Input, Output, And Content Safety

- Validate all external data.
- Treat user input, retrieved content, tool output, and model output as
  untrusted.
- Normalize untrusted data before persistence or privileged use.
- Do not let retrieved content override system or developer instructions.
- Do not let unchecked model output directly trigger privileged writes,
  external effects, irreversible actions, or governed status changes.
- Sanitize or escape unsafe HTML and rich content before rendering.
- Do not push unvalidated external payloads directly into durable memory,
  governance state, or browser UI state.

---

## Backend And API Security

- Sensitive API paths must be explicitly authenticated, authorized, and
  auditable.
- Use validated request schemas at API boundaries.
- Avoid verbose error leaks.
- Do not expose internal prompts, secrets, or unnecessary internal identifiers.
- Do not allow audit-required API paths to return success if their required
  audit write fails.
- Do not use default privileged actors, hardcoded operator identities, or
  anonymous high-privilege fallbacks in routes or service entrypoints.
- Rate limit sensitive endpoints when applicable.
- Use secure cookies when applicable.
- API security checks must fail closed.

---

## Frontend And Browser Security

- Frontend visibility is not authorization.
- Do not rely on hidden or disabled controls as the real protection for
  sensitive actions.
- Treat backend permission responses as the authority.
- Do not store or expose secrets, prompts, governance internals, or
  unnecessary sensitive identifiers in the browser.
- Render model-generated and user-generated rich content only through safe UI
  paths.
- Minimize persistence of sensitive client-side state.
- Browser-side safety checks are usability aids, not a replacement for backend
  enforcement.

---

## Tool And External Execution Safety

- Only use explicitly allowed tools for a task.
- Tool execution must go through governed application paths.
- High-risk tools must not be freely invoked from unchecked model output.
- External HTTP or third-party tool execution must be allowlisted or otherwise
  policy-controlled.
- Tool inputs and outputs must remain auditable and attributable.
- Do not let tool execution bypass approval, authorization, audit, or governed
  lifecycle checks.
- When tool safety checks fail, block execution rather than best-effort
  continuing.

---

## Memory, Reflection, And Evolution Safety

- Memory writes must go through governed interfaces.
- Do not persist unverified model inferences into long-term semantic or
  procedural memory as selectable truth.
- Automatic materialization may create or refresh governed candidates, but it
  must not auto-promote data into higher-trust governed states.
- Suppressed memories and suppressed artifacts must not be automatically
  restored.
- Reflection must remain bounded and traceable.
- Reflection must not directly modify production runtime behavior or skill
  registry behavior.
- Evolution must follow `proposal -> sandbox -> evaluation -> approval`.
- High-risk changes require explicit approval.
- Curator, rollout, replacement, and readiness flows must not bypass sandbox,
  approval, or evidence gates.
- Rollback, suppression, and replacement safety rules must fail closed; do not
  use restore or fallback behavior to silently re-enable rolled-back or
  suppressed production objects.

---

## Audit, Provenance, And Accountability

- High-risk side effects must be auditable.
- Permission changes must be auditable.
- Authentication failures, authorization failures, approval denials, and
  sensitive lifecycle actions should leave durable evidence when the path is
  security-relevant.
- Audit logging must not be silently skipped.
- Record provenance for memory, tool, rollout, and audit-relevant writes when
  possible.
- Keep actor identity explicit and end-to-end traceable.
- Do not mix provenance anchors that represent different source objects or
  different trust levels.
- Audit and provenance gaps must fail closed when the path requires them as a
  contract.

---

## Failure Mode And Default Safety Posture

- Default to fail closed.
- If authentication fails, stop.
- If authorization fails, stop.
- If allowlist validation fails, stop.
- If approval or readiness evidence is missing on a governed path, stop.
- If required audit cannot be recorded, do not report the protected action as
  successful.
- Do not use fallback paths that increase privilege or weaken governance.
- Do not execute first and repair the audit or approval trail later.

---

## Forbidden

- No hardcoded secrets.
- No disabled auth checks.
- No production bypass flags.
- No audit bypass for sensitive actions.
- No hidden privileged behavior.
- No hardcoded operator or system identity standing in for a real actor.
- No unchecked model output driving privileged writes or irreversible actions.
- No bypass of sandbox, approval, rollout, readiness, or other governed gates.
- No automatic restoration of suppressed or rolled-back governed objects.
- No unrestricted external tool execution on production paths.
