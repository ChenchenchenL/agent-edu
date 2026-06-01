# review.md

# Review Rules

Use this file when the task is to assess code completeness, implementation quality, architecture fitness, or design flaws.

## Review Posture

- Default to a critical, direct tone
- Prioritize gaps, risks, regressions, weak assumptions, and incomplete areas
- Do not soften material problems with reassurance, praise, or filler
- If no meaningful flaws are found, say that explicitly and still note residual risks or unverified areas

---

## Output Priorities

- Findings come first
- Order findings by severity
- Tie every finding to concrete evidence such as a file path, line, behavior, contract, or missing test
- Prefer specific failure modes over vague quality statements
- Call out incomplete work even if the current code path happens to work

---

## Required Coverage

Review for:

- Correctness bugs
- Behavioral regressions
- Design flaws and architectural boundary violations
- Missing validation or unsafe assumptions
- Missing tests or weak test coverage
- Operability risks, including audit, recovery, and observability gaps where relevant

---

## Response Shape

Prefer this structure when applicable:

1. Findings
2. Open questions or assumptions
3. Brief change summary or residual risk

Rules:

- Do not lead with a summary if findings exist
- Do not bury the most serious issue below minor comments
- Do not present speculative nits as major flaws
- Do not claim code is complete unless the remaining gaps have been checked against the actual scope

---

## Forbidden

- No reassuring language that downplays real issues
- No generic "looks good" style conclusions without verification
- No passing judgment without pointing to evidence
- No omission of notable design debt when the user explicitly asked about flaws
