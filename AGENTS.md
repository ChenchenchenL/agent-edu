# AGENTS.md

# =========================================================
# Global Rules
# =========================================================

You are working on a production-grade educational agent codebase.

Priorities:
1. Correctness
2. Safety and policy compliance
3. Maintainability
4. Minimal diffs
5. Architecture consistency

---

# =========================================================
# Rule Loading
# =========================================================

Additional project rules exist in:

- ./rules/frontend.md
- ./rules/backend.md
- ./rules/testing.md
- ./rules/security.md
- ./rules/review.md

You MUST read and follow relevant rule files
before making changes.

Apply rules based on the files being modified and the risks involved.

Examples:
- UI/components/pages -> frontend.md
- API/services/db/workers/agents/memory/workflow -> backend.md
- Tests -> testing.md
- Auth/input handling/tool execution/memory writes/reflection/evolution approvals -> security.md
- Code review, completion assessment, design critique -> review.md

If a change touches multiple areas, load all relevant rule files.
Security-sensitive work always requires loading `security.md`.

---

# =========================================================
# Architecture Constraints
# =========================================================

Engineering layers:
1. UI
2. Application
3. Domain
4. Infrastructure

Rules:
- UI cannot access databases, queues, or model providers directly
- Business logic belongs in application services and workflows
- Domain logic must stay framework-agnostic
- Infrastructure handles storage, network, model, and third-party integrations
- Avoid circular dependencies

System-level constraints are defined in `ARCHITECTURE.md` and must not be bypassed.
This includes constitutional rules, audit requirements, reflection limits,
memory governance, and the path:

`proposal -> sandbox -> evaluation -> approval`

---

# =========================================================
# General Engineering Rules
# =========================================================

- In TypeScript, never use `any`
- In Python, public interfaces and service/domain code must use explicit type hints
- Prefer explicit schemas and validated boundaries
- Prefer async/await or equivalent asynchronous patterns when I/O is involved
- Avoid unnecessary refactors
- Preserve existing style
- Modify minimum code necessary
- When asked about code completeness or design flaws, answer in a critical, direct tone that prioritizes gaps, risks, and incomplete areas over reassurance
- Avoid hidden side effects
- Do not bypass safety, approval, or audit paths

---

# =========================================================
# Completion Checklist
# =========================================================

Before completing:
- Relevant lint passes
- Relevant typecheck passes
- Relevant tests pass
- No debug logs remain
- If checks could not be run, state that clearly
