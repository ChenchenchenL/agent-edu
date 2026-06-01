# backend.md

# Backend Rules

## API Design

- Validate all external input
- Validate user input, webhook payloads, tool output, and model output
- Use explicit schemas at service boundaries
- In TypeScript, prefer `zod` for request and payload validation
- In Python/FastAPI, prefer `pydantic` models for request and payload validation
- Return consistent error shapes
- Never trust client data or model-produced data

---

## Services And Workflows

- Business logic belongs in services, use-cases, or workflows
- Controllers, routes, and endpoints stay thin
- Keep orchestration logic separate from pure domain logic
- Avoid duplicated logic across routes, workers, and agents
- Make side effects explicit in service boundaries

---

## Agent System Constraints

- Tool execution must go through explicit application services
- Memory writes must go through governed interfaces
- Reflection must remain bounded and traceable
- Evolution must follow `proposal -> sandbox -> evaluation -> approval`
- Model output must not directly trigger privileged side effects
- Audit-relevant actions must never bypass logging

---

## Database

- Never run migrations unless asked
- Avoid N+1 queries
- Use transactions when needed
- Prefer explicit selects and explicit loaded relations
- Use parameterized queries
- Keep persistence models from leaking into UI contracts

---

## Architecture

- Keep domain logic framework-agnostic
- Infrastructure handles external systems
- Application services coordinate workflows, permissions, and side effects
- Avoid leaking ORM or storage types across architectural boundaries
- Keep approval and audit paths explicit in code flow

---

## Node.js / TypeScript

- Prefer explicit typing
- Never use `any`
- Prefer `async/await`
- Keep route, service, and repository boundaries clear
- Validate unknown data before narrowing types

---

## Python

- Public interfaces and domain/service code must use type hints
- Keep FastAPI endpoints thin
- Prefer `pydantic` models for boundary validation
- Use async patterns for I/O-heavy code when the runtime supports them
- Keep framework-specific concerns out of domain logic

---

## Forbidden

- No business logic in controllers, routes, or endpoints
- No raw SQL unless necessary and justified
- No hidden side effects
- No direct approval, audit, or safety bypasses
- No unvalidated model output written directly into long-term memory
