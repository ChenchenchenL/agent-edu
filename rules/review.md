# review.md

# Review Rules

Use this file when the task is to assess code completeness, implementation
quality, architecture fitness, merge readiness, or design flaws.

Review is not a summary of what changed.
Review is a search for correctness bugs, boundary violations, regressions,
missing safety checks, weak assumptions, missing tests, and merge risk.

Apply the relevant rules as review baselines:

- `rules/backend.md`
- `rules/frontend.md`
- `rules/security.md`
- `rules/testing.md`

If implementation, documentation, and rules disagree, call out the mismatch.

---

## Review Posture

- Default to a critical, direct tone.
- Prioritize gaps, risks, regressions, weak assumptions, and incomplete areas.
- Do not soften material problems with reassurance, praise, or filler.
- Prefer conclusive statements over vague concern language when the failure mode
  is clear.
- If no meaningful flaws are found, say that explicitly and still note
  residual risks or unverified areas.

---

## Findings Standard

- Findings come first.
- Order findings by severity.
- Tie every finding to concrete evidence such as a file path, line, behavior,
  contract, violated rule, or missing test.
- Prefer specific failure modes over vague quality statements.
- Call out incomplete work even if the current code path happens to work.
- Do not elevate style nits above correctness, security, lifecycle, audit, or
  data-integrity problems.

Each finding should make clear:

- severity
- where the issue is
- what can fail
- why it matters
- whether it blocks merge or should be fixed pre-merge

---

## Required Coverage

Review for:

- correctness bugs
- behavioral regressions
- design flaws and architectural boundary violations
- missing validation or unsafe assumptions
- missing tests or weak risk coverage
- operability risks, including audit, recovery, observability, and worker/job
  behavior where relevant

When applicable, review against these specific baselines:

- backend transaction ownership, rollback, side-effect ordering, repository
  boundaries, query limits, idempotency, and actor propagation
- frontend type boundaries, component responsibilities, UI state completeness,
  and avoidance of browser-side governance logic
- security fail-closed behavior, auth/authz, secret handling, tool allowlists,
  governed gate integrity, and audit/provenance requirements
- testing sufficiency for failure paths, denied paths, rollback paths,
  lifecycle transitions, concurrency/reentry, and high-risk workflow changes

---

## Risk Rating And Merge Judgment

Use these severity meanings consistently:

- `CRITICAL`: security bypass, privilege bypass, audit failure on protected
  paths, irreversible data-integrity break, or governed-state corruption.
  Default merge judgment: `BLOCKED`.
- `HIGH`: likely correctness bug, transaction inconsistency, lifecycle rule
  violation, major regression risk, or critical missing test coverage.
  Default merge judgment: must fix before merge.
- `MEDIUM`: meaningful design debt, operability gap, moderate test gap,
  maintainability issue, or performance risk that should be addressed before or
  shortly after merge.
- `LOW`: minor consistency, clarity, or maintainability issue that is
  non-blocking.

Do not label issues more severely than their evidence supports.
Do not understate merge blockers to sound polite.

---

## Response Shape

Prefer this structure when applicable:

1. Findings
2. Open questions or assumptions
3. Residual risk or brief change summary

For pre-merge or merge-readiness reviews, also include:

- overall risk level
- blocked or must-fix issues
- recommended improvements
- merge recommendation

Rules:

- Do not lead with a summary if findings exist.
- Do not bury the most serious issue below minor comments.
- Do not present speculative nits as major flaws.
- Do not claim code is complete unless the remaining gaps have been checked
  against the actual scope.
- If tests, blackbox validation, or gated regression paths were not run, say so
  explicitly when that matters to the judgment.

---

## Special Review Cases

- If a change continues adding logic to a known oversized file or god object,
  call that out even if the new logic itself works.
- If a migration bridge, callback shim, or transitional dependency keeps
  expanding, treat that as design debt worth reporting.
- If documentation claims a capability is complete but code or tests do not
  support that claim, report the mismatch.
- If repeated logic risks drifting governance, audit, or permission semantics,
  report it as a design problem, not just a cleanup suggestion.
- If a route, worker, or service path can fail after partial state mutation,
  review the final persisted state, not only the happy path.

---

## Forbidden

- No reassuring language that downplays real issues.
- No generic "looks good" style conclusions without verification.
- No passing judgment without pointing to evidence.
- No omission of notable design debt when the user explicitly asked about
  flaws.
- No coverage-only reasoning that ignores security, lifecycle, transaction, or
  audit risks.
