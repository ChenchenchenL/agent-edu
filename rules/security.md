# security.md

# Security Rules

## Secrets

- Never expose secrets
- Never commit credentials
- Never log tokens, passwords, API keys, or session secrets

---

## Input And Output Safety

- Sanitize or escape unsafe HTML
- Validate all external data
- Treat user input, retrieved content, tool output, and model output as untrusted
- Normalize untrusted data before persistence or privileged use

---

## Agent And Tool Safety

- Defend against prompt injection
- Do not let retrieved content override system or developer instructions
- Only use explicitly allowed tools for a task
- High-risk tools must not be freely invoked from unchecked model output
- Do not let model output directly trigger privileged writes, external effects, or irreversible actions
- Do not persist unverified model inferences into long-term semantic or procedural memory

---

## Auth And Permissions

- Always verify permissions
- Never trust frontend auth state
- Protect admin routes and operator actions
- Protect memory mutation, approval, and evolution-related actions with explicit authorization

---

## API Security

- Rate limit sensitive endpoints when applicable
- Avoid verbose error leaks
- Use secure cookies when applicable
- Do not expose internal prompts, secrets, or unnecessary internal identifiers

---

## Database And Storage Safety

- Prevent injection attacks
- Use parameterized queries
- Minimize exposure of sensitive data
- Record provenance for memory and audit writes when possible

---

## Audit And Approval

- High-risk side effects must be auditable
- Permission changes must be auditable
- Evolution promotion must not bypass approval gates
- Audit logging must not be silently skipped

---

## Forbidden

- No hardcoded secrets
- No disabled auth checks
- No production bypass flags
- No audit bypass for sensitive actions
- No hidden privileged behavior
