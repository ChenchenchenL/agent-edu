# Quality Checklist

完整的代码质量检查清单，在审查时逐项验证。

---

## Code Quality

- [ ] **No code smells**
  - No functions >50 lines
  - No nesting >3 levels
  - No magic numbers (use named constants)
  - No commented-out code blocks

- [ ] **Error handling**
  - Try/except with specific exceptions (not bare `except:`)
  - Proper error messages with context
  - No silent failures

- [ ] **Edge cases**
  - Null/None handling
  - Empty collection handling
  - Boundary values (0, -1, max)
  - Concurrent access (if applicable)

- [ ] **Single Responsibility**
  - Functions do one thing
  - Classes have clear purpose
  - No God objects

---

## Testing

- [ ] **Unit tests exist**
  - >80% coverage for core business logic
  - Test names clearly describe what they test
  - Tests are deterministic (no race conditions)

- [ ] **Integration tests**
  - Happy path covered
  - Edge cases covered
  - Error conditions covered

- [ ] **Mocking strategy**
  - External dependencies mocked
  - Not over-mocked (don't mock domain logic)
  - Mock behavior matches real behavior

- [ ] **Test quality**
  - Arrange-Act-Assert structure
  - No test interdependencies
  - Fast execution (<5s for unit tests)

---

## Documentation

- [ ] **Public APIs**
  - Docstrings present (Google style for Python)
  - Parameters documented
  - Return values documented
  - Exceptions documented

- [ ] **Complex logic**
  - Inline comments explain **WHY** (not what)
  - Non-obvious algorithms explained
  - Business rule references included

- [ ] **Project docs**
  - README.md updated if user-facing changes
  - ARCHITECTURE.md updated if structural changes
  - API docs regenerated if schema changes

---

## Security (AI System Specific)

- [ ] **SQL injection**
  - Use parameterized queries
  - No string concatenation in SQL
  - ORM used correctly

- [ ] **Prompt injection**
  - User input sanitized before LLM
  - No direct concatenation into prompts
  - Output validation applied

- [ ] **Input validation**
  - All external data validated (Pydantic schemas)
  - Type checking enforced
  - Range/format validation applied

- [ ] **Secrets management**
  - No hardcoded secrets
  - Environment variables used
  - .env not committed to git

- [ ] **Audit logging**
  - Auth events logged
  - Memory writes logged
  - Tool execution logged
  - Sensitive operations logged

---

## Architecture

- [ ] **Layer boundaries**
  - UI doesn't access DB directly
  - Domain logic framework-agnostic
  - Infrastructure isolated

- [ ] **Dependencies**
  - No circular dependencies
  - Dependency injection used
  - Coupling minimized

- [ ] **Governance**
  - Approval flows not bypassed
  - Sandbox constraints enforced
  - Evaluation pipelines intact

---

## Performance

- [ ] **Database**
  - No N+1 queries
  - Proper indexes used
  - SELECT specific columns (not *)
  - Transaction boundaries clear

- [ ] **Async behavior**
  - Cancellation safe
  - Timeout configured
  - Resource cleanup guaranteed
  - No unbounded concurrency

- [ ] **Resource usage**
  - No memory leaks
  - File handles closed
  - DB connections returned to pool

---

## Logging & Observability

- [ ] **Log levels appropriate**
  - DEBUG: verbose details
  - INFO: significant events
  - WARNING: recoverable issues
  - ERROR: failures

- [ ] **Log content**
  - Operational context included
  - No secrets/tokens/PII leaked
  - Structured format (JSON if possible)

- [ ] **Metrics**
  - Key operations instrumented
  - Error rates tracked
  - Latency measured

---

## Python-Specific

- [ ] **Type hints**
  - Public interfaces fully typed
  - Service/domain code typed
  - Use of `Any` justified

- [ ] **Pydantic schemas**
  - API requests/responses use Pydantic
  - Validation rules defined
  - No raw dicts for structured data

- [ ] **SQLAlchemy**
  - Sessions properly closed
  - Relationships loaded efficiently
  - Migrations reversible

---

## TypeScript-Specific

- [ ] **Type safety**
  - No `any` usage
  - No unsafe type assertions
  - Strict null checks passed

- [ ] **React**
  - Props properly typed (interfaces)
  - Hooks dependencies complete
  - Component return types explicit

---

## Deployment Safety

- [ ] **Rollback plan**
  - Changes reversible
  - Migration downgrade implemented
  - Feature flags used if needed

- [ ] **Backward compatibility**
  - API changes backward compatible
  - Database schema changes safe
  - Configuration changes graceful

- [ ] **Monitoring**
  - Alerts configured
  - Dashboards updated
  - Runbooks documented
