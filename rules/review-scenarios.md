# Review Scenarios & Templates

常见代码审查场景的详细指南和用户询问模板。

---

## Scenario 1: Quick PR Review (Small Changes)

**User says:**
- "Review this PR"
- "帮我 review 一下"
- "快速看一下这个变更"

**Action:**
1. Check which files changed (`git diff`)
2. Determine code area:
   - Backend → Load `rules/backend.md`
   - Frontend → Load `rules/frontend.md`
   - Auth/memory/tools → Load `rules/security.md`
   - Tests → Load `rules/testing.md`
3. Run `/review` (gstack)
4. Report findings in standard format

**Skill used:** `/review`

---

## Scenario 2: Code Quality & Design Check

**User says:**
- "检查代码质量和设计"
- "是否有冗余代码"
- "Check for code smells and architecture issues"

**Action:**
1. Run `/design-review` (gstack)
   - Check for duplicate code (DRY violations)
   - Verify layer boundaries
   - Assess module coupling
   - Check for over-engineering

2. Run `/qa` (gstack)
   - Long functions (>50 lines)
   - Deep nesting (>3 levels)
   - High complexity
   - Unused imports/variables
   - Test coverage

3. Run `/review` (gstack) for code details

4. Synthesize findings across all three

**Skills used:** `/design-review` + `/qa` + `/review`

---

## Scenario 3: Redundancy-Focused Review

**User says:**
- "检查是否有重复代码"
- "Is there redundant code?"
- "查找可以重构的地方"

**Action:**
1. Run `/design-review` with focus on:
   - Duplicate logic across files
   - Similar functions with slight variations
   - Copy-pasted code blocks
   - Overlapping responsibilities

2. Search codebase for patterns:
   ```bash
   # Similar function names
   grep -r "function_name_pattern" .
   
   # Repeated imports
   grep -r "^import " packages/ | sort | uniq -c | sort -rn
   ```

3. Report:
   - Specific redundant sections (file:line)
   - Suggested refactoring approach
   - DRY violations with severity

**Skill used:** `/design-review`

---

## Scenario 4: Security Review

**User says:**
- "这段代码安全吗？"
- "Is this secure?"
- "审查安全性"

**Action:**
1. Read `rules/security.md`
2. Run `/cso` (gstack security audit)
3. Check for:
   - Input validation
   - SQL injection vectors
   - Prompt injection risks
   - Secrets exposure
   - Audit logging
4. Report findings with severity levels

**Skill used:** `/cso`

---

## Scenario 5: Pre-Merge Comprehensive Check

**User says:**
- "准备合并到 main，请全面检查"
- "Before I merge, review this"
- "Ready for merge, comprehensive check"

**Action:**
1. Run `/design-review` (architecture)
2. Run `/qa` (quality assurance)
3. Run `/cso` (security audit)
4. Run `requesting-code-review` (independent reviewer subagent)
   ```
   Get git SHAs:
   BASE_SHA=$(git merge-base HEAD origin/main)
   HEAD_SHA=$(git rev-parse HEAD)
   
   Dispatch reviewer with:
   - DESCRIPTION: What was built
   - PLAN_OR_REQUIREMENTS: What it should do
   - BASE_SHA: Starting commit
   - HEAD_SHA: Ending commit
   ```
5. Synthesize all findings
6. Provide:
   - Overall risk level
   - Must-fix issues (Critical/Important)
   - Optional improvements (Minor)
   - Merge recommendation

**Skills used:** `/design-review` + `/qa` + `/cso` + `requesting-code-review`

---

## Scenario 6: Handling Review Feedback

**User says:**
- "修复你发现的问题"
- "Fix the issues you found"
- "Implement the suggestions"

**Action:**
1. Apply `receiving-code-review` principles (superpowers)
2. For each issue:
   - **Verify** it's a real problem (not a misunderstanding)
   - **Ask** for clarification if unclear
   - **Push back** with technical reasoning if incorrect
3. Implement fixes one at a time
4. Test each fix individually
5. Report what changed

**NO performative agreement:**
- ❌ "You're absolutely right!"
- ❌ "Great point!"
- ✅ "Fixed. [Brief description]"
- ✅ "Good catch - [issue]. Fixed in [location]."

**Skill used:** `receiving-code-review` principles

---

## Scenario 7: Architecture Impact Assessment

**User says:**
- "这个改动对架构有什么影响？"
- "Will this break the architecture?"
- "设计审查"

**Action:**
1. Read `ARCHITECTURE.md`
2. Run `/design-review` (gstack)
3. Check:
   - Layer boundaries preserved
   - Circular dependencies introduced
   - Governance flows intact
   - Evolution paths auditable
4. Report architectural impact

**Skill used:** `/design-review`

---

## Scenario 8: Single File Deep Dive

**User says:**
- "对 `file.py` 进行全面质量审查"
- "Deep review of `file.py`"

**Action:**
1. Run `/design-review` (focus on this file)
2. Run `/qa` (focus on this file)
3. Check against `rules/quality-checklist.md`
4. Report:
   - Code quality issues
   - Design problems
   - Test coverage
   - Security concerns (if applicable)

**Skills used:** `/design-review` + `/qa`

---

## User Ask Templates

以下是用户可以直接复制使用的询问模板：

### 🔍 Quick Review
```
请 review 这个 PR
```

### 🏗️ Quality + Design
```
请检查代码质量和设计：
1. 是否有冗余代码
2. 架构是否合理
3. 是否有 code smells

运行：/design-review + /qa
```

### 🔒 Security
```
请审查安全性，运行 /cso
重点检查：
- SQL/prompt 注入
- 认证授权
- 敏感数据泄露
- 审计日志
```

### ✅ Pre-Merge
```
准备合并到 main，请全面审查：
1. /design-review — 架构
2. /qa — 质量
3. /cso — 安全
4. requesting-code-review — 独立验证

给出风险等级和必须修复的问题。
```

### 🎯 Redundancy Check
```
请重点检查代码冗余：
运行 /design-review，关注：
- 重复代码（DRY 违规）
- 相似函数
- 可抽象的公共逻辑

给出具体位置和重构建议。
```

### 📊 Quality Deep Dive
```
请深度分析代码质量：
运行 /qa，检查：
- 函数复杂度
- 嵌套深度
- 未使用的代码
- 测试覆盖率

输出质量评分和改进建议。
```

---

## Skill Combination Matrix

| 用户需求 | 技能组合 | 原因 |
|---------|---------|------|
| 快速 review | `/review` | 单个技能足够 |
| 质量 + 设计 | `/design-review` + `/qa` | 需要架构和质量双重视角 |
| 只查冗余 | `/design-review` | 专注 DRY 和架构 |
| 安全审查 | `/cso` | 专项安全检查 |
| 合并前检查 | 四件套 | 全方位验证 |
| 单文件深度 | `/design-review` + `/qa` | 聚焦单文件的质量和设计 |

---

## When NOT to Use Skills

**Do direct manual review when:**
- User explicitly says "don't use skills"
- Quick conversational question about code
- Explaining how something works (教学场景)

**Always use skills for:**
- PR reviews
- Pre-merge checks
- Quality assessments
- Security audits
