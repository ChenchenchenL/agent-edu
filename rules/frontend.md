# frontend.md

# Frontend Rules

These rules apply to Web frontend code only.

The default frontend stack is:

- `React + TypeScript`
- `shadcn/ui + TailwindCSS`
- `TanStack Query`

The frontend is an API consumer. It must not become the source of truth for
backend lifecycle, governance, approval, or permission decisions.

---

## Scope And Stack

- Build Web frontend code with TypeScript.
- Treat React as the default component model.
- Treat `shadcn/ui + TailwindCSS` as the primary component and styling system.
- Treat `TanStack Query` as the default server-state and request lifecycle
  foundation.
- Do not introduce a second frontend stack, a second component system, or a
  second styling system without an explicit architectural decision.
- Design for desktop workbench usage first: prioritize information density,
  scanability, and stable layouts, while keeping mobile views usable.

---

## Language And Type Safety

- Browser frontend code must use TypeScript.
- Do not use `any`.
- Type component props, hook return values, form payloads, and API mapping
  objects explicitly.
- Treat API responses, model-generated content, and unknown inputs as untrusted
  data until validated or normalized.
- Do not push unvalidated backend payloads directly into component state.
- Prefer type-only imports where applicable.
- Do not hide real structures behind broad object types such as generic record
  bags when a stable shape exists.

---

## UI Library And Dependency Policy

- Use `shadcn/ui` primitives as the default component foundation.
- Use Tailwind utility patterns consistently instead of mixing in another
  styling model for narrow changes.
- Full-featured supporting libraries are allowed for icons, tables, charts,
  forms, and similar infrastructure when they have clear reuse value.
- Do not introduce a new UI framework or full styling system for a single page
  or a small feature.
- Do not mix two primary component libraries in the same frontend surface.
- New frontend dependencies should earn their place through reuse, consistency,
  or meaningful complexity reduction, not because they save a few lines once.

---

## Component Boundaries And Composition

- Page or route components assemble screens; they should not accumulate
  unrelated business logic.
- Presentational components should not fetch their own data.
- Data loading, mutations, permission checks, and other side effects belong in
  page boundaries or dedicated hooks.
- Prefer composition over inheritance.
- Extract repeated UI patterns into reusable components once the same pattern
  appears three or more times.
- Do not let giant pages or giant components mix layout, data loading, state
  machines, permissions, and rendering in one place.

---

## State And Data Flow

- Use `TanStack Query` for server state, caching, and request lifecycle
  management by default.
- Keep transient UI state local unless it is truly shared.
- Keep server state separate from local interaction state.
- Normalize or map API responses before storing them in UI state when the raw
  payload shape is not the desired view model.
- Do not maintain the same derived business state independently in multiple
  components.
- Frontend code must not reimplement backend governance or lifecycle state
  machines for memory, reflection, approval, rollout, or skill transitions.

---

## Styling And Design System

- Use TailwindCSS as the styling system.
- Prefer extending existing `shadcn/ui` primitives over inventing parallel
  visual patterns.
- Avoid inline styles unless the value is truly dynamic and localized.
- Keep spacing, typography, radius, border, and color usage consistent.
- Extract repeated visual patterns into shared primitives rather than copying
  page-level markup.
- Favor stable workbench layouts over marketing-style composition.

---

## UX States And Interaction Completeness

- Every async view must handle loading, empty, and error states.
- Every mutation flow must surface pending, success, and failure feedback.
- Dangerous actions must have clear confirmation, disable states, or explicit
  consequence messaging.
- Dense data views such as tables, queues, and review surfaces must optimize
  for scanning and repeated use.
- Do not ship happy-path-only UI flows.

---

## Security And Permission Boundaries

- Do not treat frontend visibility as authorization.
- Hide or disable controls for usability when appropriate, but treat backend
  permission responses as the real authority.
- Do not render unsafe HTML or rich content without sanitization or safe
  escaping.
- Do not expose internal prompts, secrets, tokens, or unnecessary internal
  identifiers in the UI.
- Treat model-generated content as untrusted until rendered through safe UI
  paths.

---

## File, Component, And Hook Size Limits

- Treat these thresholds as effective logic and responsibility limits, not as
  raw physical line counts inflated by JSX formatting or Tailwind class lists.
- Do not mechanically split one-use UI fragments only to satisfy physical line
  counts when responsibility boundaries are still clear.
- Keep presentational component files under 350 effective lines by default.
- Keep page or container component files under 600 effective lines by default.
- Keep custom hooks under 200 effective lines by default.
- Files over 500 lines enter refactor watch status.
- Files over 800 lines are split candidates.
- Components with more than 12 props should be reviewed for interface redesign.
- Keep complex render branches and handlers under 80 effective lines by
  default.
- Threshold crossings do not require immediate large rewrites, but new changes
  should not keep making oversized components worse without a clear reason.

---

## Testing Expectations

- Add tests for complex interactions and stateful UI flows.
- Cover loading, empty, error, and permission-denied states when UI behavior
  changes.
- Test forms, filters, pagination, confirmation flows, and mutation feedback
  when those behaviors are added or changed.
- Prefer tests that exercise user-visible behavior over implementation details.
- Avoid snapshot-heavy testing as a substitute for real behavior coverage.

---

## Forbidden

- No direct database access from frontend code.
- No frontend-only authorization for sensitive actions.
- No giant pages that mix layout, data loading, business logic, and mutation
  coordination without boundaries.
- No untyped API consumption in core frontend flows.
- No reimplementation of backend governance logic in the browser.
- No mixing multiple primary UI or styling systems in the same Web frontend
  surface.
- No deeply nested presentational components that fetch their own data.
- No async UI paths without loading, empty, and error handling.
