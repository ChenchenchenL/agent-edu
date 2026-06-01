# frontend.md

# Frontend Rules

## Scope

These rules apply to learner-facing, admin-facing, or internal UI code.
If the project uses React, Next.js, TailwindCSS, or shadcn/ui, the framework-specific rules below apply.
If those tools are not present, follow the general UI and component rules without introducing a second styling or rendering model by default.

---

## React / Next.js

- Prefer Server Components when the framework supports them
- Avoid unnecessary `useEffect`
- Keep components focused and reasonably small
- Prefer composition over inheritance
- Keep state local unless it is truly shared
- Move data fetching to route-level or application-level boundaries when possible

---

## UI / UX

- Mobile-first by default
- Accessibility is required
- Use semantic HTML
- Avoid layout shift
- Always show loading, empty, and error states
- Render model-generated or user-generated rich content safely

---

## Styling

- If TailwindCSS is already used, reuse existing utility patterns
- If shadcn/ui is already used, prefer extending existing primitives
- Avoid inline styles unless they are truly dynamic and localized
- Do not introduce a second styling system for a narrow change

---

## Component Design

- One component should have one clear responsibility
- Avoid prop drilling when composition or scoped context is clearer
- Extract reusable UI patterns that appear more than once
- Keep page components from becoming orchestration layers for unrelated concerns

---

## Data And State

- Do not fetch inside deeply nested presentational components
- Keep permission checks server-side or in application boundaries, not UI-only
- Keep transient UI state local
- Treat API and model responses as untrusted data until validated or normalized

---

## Forbidden

- No direct database access from UI code
- No giant page components that mix layout, data loading, and business logic
- No frontend-only authorization for sensitive actions
- No unsafe HTML rendering without sanitization or escape handling
