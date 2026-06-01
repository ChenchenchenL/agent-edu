# CONVENTIONS.md

## Summary

This document defines repository-wide implementation and collaboration defaults.
It exists to keep future code, docs, schemas, and automation consistent as the project grows from architecture into implementation.

## Document Responsibilities

- `README.md`: project vision, mission, phase roadmap, and high-level framing
- `ARCHITECTURE.md`: system blueprint, canonical concepts, major flows, and safety boundaries
- `CONVENTIONS.md`: naming, structure, dependency, testing, and configuration defaults
- `AGENTS.md`: AI working rules for repository tasks
- `docs/CODE_REVIEW_TEMPLATE.md`: default response template for code completeness and design flaw reviews

Do not duplicate the same rule in multiple documents unless one document is summarizing another.

## Language And Writing

- Documentation is Chinese-first unless a task explicitly requires bilingual or English-first output.
- Code identifiers should use English.
- Prefer precise domain terms over marketing vocabulary.
- Reuse canonical terms from `ARCHITECTURE.md` for concepts that cross modules.

## Naming

- Directories: `kebab-case`
- General file names: `kebab-case`
- Classes, types, interfaces, and schemas: `PascalCase`
- Functions, methods, variables, and fields: `camelCase`
- Constants and environment variables: `UPPER_SNAKE_CASE`
- Agent role identifiers: `TutorAgent`, `PlannerAgent`, `MemoryAgent`, `SafetyAgent`
- Skill identifiers: `verb_noun`, such as `create_quiz` or `diagnose_weakness`
- Event names: dot notation, such as `memory.recorded`, `reflection.completed`, `evolution.proposed`

## Repository Structure

- Keep runnable applications separate from shared libraries and domain packages.
- Keep domain logic separate from transport, persistence, and infrastructure concerns.
- Keep safety and approval code visibly separated from convenience helpers.
- Avoid dumping new features into the repository root.

## Dependency Boundaries

- Domain models must not depend directly on infrastructure adapters.
- Workflow orchestration should consume explicit domain interfaces rather than hidden side effects.
- Memory, reflection, and evolution operations should be mediated through governed services or interfaces.
- Approval and audit paths must remain explicit in control flow.

## Configuration

- Use `.editorconfig` as the baseline cross-language formatting contract.
- Prefix environment variables with `AGENT_EDU_`.
- Favor explicit, typed, or schema-validated configuration once application code exists.
- Do not hardcode secrets, API keys, or model credentials.

## Logging And Audit

- Prefer machine-readable structured logs for operational events.
- Use JSON or similarly parseable formats for services and workers.
- Treat `AuditEvent` records as append-oriented history, not mutable state.
- Do not hide approval, safety, or policy-relevant actions behind debug-only logging.

## Testing

- Write unit tests for pure logic, planning rules, transformations, and validation.
- Write integration tests for storage, queues, model adapters, and external service boundaries.
- Write scenario or end-to-end tests for workflows, multi-agent coordination, and safety gates.
- Add regression tests for bugs involving memory corruption, approval bypass, infinite loops, or reflection depth failures.

## Phase Discipline

- Implement the smallest slice that fits the current phase.
- Do not pull later-phase autonomy into early-phase features without an explicit decision.
- Leave clear extension points instead of speculative abstractions when the next phase is not yet active.

## Change Management

- Keep terminology consistent when adding new modules, tables, events, or APIs.
- Update documentation when a change introduces new canonical concepts or repository rules.
- Prefer additive evolution over destructive rewrites unless the rewrite is the task.
- If a design tradeoff is unresolved, record the assumption close to the change.
