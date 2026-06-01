# testing.md

# Testing Rules

## General

- Add tests for new business logic
- Update tests when behavior changes
- Keep tests deterministic
- Prefer tests that exercise real application behavior over implementation details

---

## Test Style

- Prefer integration tests for service and workflow behavior
- Use unit tests for pure domain logic and validation logic
- Mock minimally
- Avoid snapshot abuse
- Use fixtures, fakes, or stubs for model providers and external tools in default test paths

---

## Agent And Workflow Coverage

- Test workflow success paths and failure paths
- Test validation and normalization of tool output and model output
- Test memory persistence behavior and guarded memory writes
- Test reflection depth limits
- Test approval gates and denied-path behavior
- Test error recovery for partial failures and retriable tasks

---

## Coverage

Must test:
- Validation
- Error states
- Edge cases
- Permissions
- Loading states when UI changes
- Unsafe input handling
- Memory write failures

---

## Forbidden

- No flaky tests
- No sleeping or time-based hacks
- No random test data without a seed
- No default test path that requires live external services or live model providers
