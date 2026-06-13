# ARCHITECTURE.md

## Summary

`agent-edu` is a long-horizon educational agent system, not a one-shot question answering bot.
The system is designed to evolve from a stable teaching agent into a governed multi-agent learning companion with memory, reflection, and controlled capability growth.

This document defines the architectural blueprint across all planned phases and provides the canonical vocabulary for future code, APIs, schemas, and docs.

## System Goals

- Provide long-term educational companionship instead of isolated chat responses.
- Maintain durable learner context through layered memory.
- Plan and execute teaching workflows against explicit learner goals.
- Improve teaching quality through bounded reflection.
- Evolve skills through controlled proposal, evaluation, and approval paths.
- Preserve safety, auditability, and human oversight as non-optional system properties.

## Non-Goals

- A generic AI assistant with no educational specialization
- An unconstrained self-modifying autonomous system
- A single "super agent" that hides planning, execution, memory, safety, and evolution behind one opaque loop

## Reference Inspirations

The system borrows Hermes-style platform patterns, but not its product scope.

Reused ideas:

- unified agent core
- skills as reusable procedural memory
- bounded memory with compression
- session store, lineage, and full-text retrieval
- curated evolution through proposal, sandbox, evaluation, and approval
- batch / trajectory evaluation for regression and replay

Self-built layers:

- learner model
- mastery estimation
- curriculum planner
- reflection / evaluation loop
- pedagogical safety

Reference mapping: [docs/hermes-to-edu-mapping.md](docs/hermes-to-edu-mapping.md)

## Core Principles

- Long-term memory is required for continuity.
- Planning and execution must be explicit and traceable.
- Reflection is bounded and governed.
- Evolution is proposal-driven, never direct self-modification.
- Safety rules are upstream of optimization.
- System behavior must remain explainable through logs, state, and approvals.

## Canonical Concepts

Use these names consistently in code and documentation:

- `LearningSession`: one bounded teaching or practice interaction
- `SessionMessage`: a user or assistant message within a session
- `LearnerGoal`: a durable user learning objective
- `LearnerProfile`: a durable learner state and preference record
- `StudyPlan`: a generated learning path for one learner goal
- `PlanStage`: a milestone or stage within a study plan
- `DailyTask`: a bounded learning task scheduled from a study plan
- `WorkflowRun`: a tracked execution instance for a workflow or task
- `GoalAutonomyState`: the current autonomy phase and control snapshot for one goal
- `ScheduledAutonomyJob`: a persisted due job for the autonomy worker
- `LearnerAvailability`: the learner's available time and scheduling preferences
- `LearnerTopicMastery`: per-topic mastery, confidence, and evidence
- `TaskAttempt`: a persisted attempt/result record for a task execution
- `WorkspaceSummary`: a learner-facing terminal workspace snapshot for one profile and optional goal
- `KnowledgeMemory`: a durable knowledge-point memory record
- `BehaviorMemory`: a durable learner-behavior memory record
- `Skill`: a composable teaching, analysis, or automation capability
- `Workflow`: an executable task graph that coordinates skills
- `MemoryRecord`: a persisted memory unit
- `MemoryEmbeddingRecord`: a persisted embedding or retrieval index entry
- `SessionQuiz`: a generated practice set for a learning session
- `SessionQuizQuestion`: one generated quiz question
- `ReflectionRecord`: a persisted analysis of an outcome and an improvement proposal
- `EvolutionProposal`: a candidate change to skill or strategy behavior
- `AuditEvent`: an immutable operational or safety-relevant event
- `AgentRole`: a declared agent responsibility such as tutor, planner, memory, or safety
- `ApprovalDecision`: a human or system gate result on high-risk changes

## Logical Layers

### 1. Constitutional Layer

- Holds immutable root policy and hard safety constraints.
- Defines non-bypassable limits for approval, reflection depth, privilege, and behavioral transparency.
- Must remain outside agent-controlled mutation paths.

### 2. Executive Planner

- Converts a `LearnerGoal` into actionable plans, tasks, and workflows.
- Selects skills, decomposes work, and adjusts plans based on learner progress.
- Coordinates, but does not replace, execution agents.

### 3. Skill System

- Encapsulates reusable capabilities with explicit inputs, outputs, and evaluation criteria.
- Supports teaching, diagnosis, review scheduling, summarization, and metacognitive operations.
- Serves as the unit of controlled evolution.

### 4. Workflow Engine

- Runs multi-step execution graphs such as diagnosis -> exercise generation -> review scheduling.
- Handles async work, retries, and multi-step state progression.
- Provides the runtime path between planning and execution.

### 5. Memory System

- Stores and retrieves layered memory for learner continuity and agent adaptation.
- Includes episodic, semantic, procedural, and reflective memory classes.
- Requires compression, decay, and abstraction to control growth.

### 6. Reflection System

- Analyzes successes and failures after execution.
- Produces bounded improvement hypotheses for prompts, workflows, sequencing, or teaching strategy.
- Writes `ReflectionRecord` outputs for later evaluation and reuse.

### 7. Evolution Engine

- Converts evidence from reflection into `EvolutionProposal` candidates.
- Runs sandboxed evaluation before any promoted change becomes active.
- Cannot directly modify production behavior without approval.

### 8. Multi-Agent Coordination

- Manages role separation across planner, tutor, reflection, memory, curriculum, motivation, and safety agents.
- Keeps responsibilities explicit rather than collapsing them into a single loop.
- Enables later-phase agent society patterns under governance.

### 9. Environment Adapter

- Bridges the agent system with APIs, storage, queues, external tools, and user-facing surfaces.
- Isolates infrastructure and transport concerns from domain logic.
- Current user-facing surface direction is CLI-first:
  - installable terminal CLI for scriptable operations
  - learner-first TUI workspace for long-running study sessions
  - future QQ / 微信 / other connectors should reuse the same application boundary

## Pedagogical Safety

Educational autonomy has additional constraints beyond generic agent safety:

- do not fabricate mastery or progress
- do not hide uncertainty in teaching output
- do not optimize engagement at the cost of learning quality
- do not create manipulative dependency loops
- do not promote unsafe or unreviewed teaching changes
- require explicit governance for any strategy that materially changes learner experience

## Primary Data And Decision Flow

The canonical runtime path is:

`LearnerGoal` -> Planner -> `Workflow` -> execution via `Skill` units -> `MemoryRecord` persistence -> `ReflectionRecord` generation -> `EvolutionProposal` evaluation -> `ApprovalDecision` -> optional rollout -> `AuditEvent` trail

This flow is intentionally governed:

- planning does not bypass workflow execution
- execution does not bypass memory and audit
- reflection does not bypass limits
- evolution does not bypass sandbox and approval

## Memory Model

The system uses four memory classes:

- Episodic memory: concrete learner interactions and recent struggle context
- Semantic memory: stable learner traits, patterns, and inferred preferences
- Procedural memory: reusable teaching heuristics and operational know-how
- Reflective memory: prior failures, lessons, and improvement outcomes

Required control mechanisms:

- summarization
- clustering
- decay
- abstraction

Current long-term memory v1 implementation splits persistent memory into:

- knowledge memory: concepts, prerequisite structure, and topic mastery evidence
- behavior memory: learner habits, support patterns, and intervention effects
- session memory remains the episodic source layer

Long-term memory materialization is governed and provenance-preserving:

- chat turns first write profile-scoped `MemoryEvent` records, then materialize or refresh long-term memory candidates from those events
- terminal task outcomes (`completed`, `failed`, `skipped`) can contribute `TaskAttempt` evidence and create candidates when no matching memory exists
- evaluated reflection outcomes (`effective`, `ineffective`) can contribute `reflection_outcome` evidence and create candidates when topic and evaluation are explicit
- structured extraction output is normalized through application-layer policy and validated schemas before it can become a `candidate`
- memory conflict sets keep policy-derived reason / handling / impact fields, while member titles and status are resolved by memory-id lookup instead of stored snapshots
- long-term maintenance uses a dedicated `memory_maintenance_jobs` queue with lease, retry/backoff, and bounded batch processing
- observability for long-term memory includes candidate backlog, promotion/conflict rates, materialization failure rate, and maintenance duration
- automatic materialization only creates or refreshes `candidate` memories; promotion to `active` or `stable`, suppression restore, compression, and archival remain governance operations
- provenance must not mix identifiers: `session_event` provenance points to `MemoryEvent.id`, while raw `SessionMessage.id` stays on the memory event or evidence payload

## Safety And Governance

The following architectural constraints are mandatory:

- Constitutional rules are immutable at runtime.
- Reflection depth is limited and must not recurse indefinitely.
- Evolution follows `proposal -> sandbox -> evaluation -> approval`.
- High-risk changes require explicit approval.
- Audit logging is append-oriented and cannot be silently skipped.
- Skill execution is allowlisted or otherwise policy-controlled.
- Agents must not self-expand permissions or hide actions from operators.

## Phase Blueprint

### Phase 1: Stable Teaching Agent

- Deliver conversational teaching, quizzes, explanation, and basic memory.
- Establish the first stable `Skill` and `Workflow` abstractions.
- Keep the system reliable before adding deeper autonomy.

### Phase 2: Autonomous Task System

- Add explicit planning, workflow execution, and tool use.
- Generate learning plans and scheduled actions from `LearnerGoal` objects.
- Current implemented baseline:
  - `LearnerProfile -> LearnerGoal -> StudyPlan -> DailyTask -> WorkflowRun`
  - `GoalAutonomyState`, `LearnerAvailability`, `LearnerTopicMastery`, `TaskAttempt`
  - DB-backed autonomy jobs plus worker poll loop
  - learner timezone-aware daily task materialization
  - autonomy control API: state / availability / mastery / pause / resume / manual replan
  - dynamic spaced review interval policy driven by mastery, recent attempts, and strategy bias
  - milestone stage gate with blocked downstream materialization until release
  - governed tool use:
    - internal tool execution
    - allowlisted external HTTP tool execution v1
  - immutable replan versions and audit trail for plan/task/workflow changes
  - CLI/TUI-ready API surface:
    - workspace summary endpoint
    - filtered task listing
    - read-only long-term memory browse endpoints
    - dual-mode backend client contract for remote API and embedded ASGI runtime
  - long-term memory production maintenance:
    - `memory_maintenance_jobs` queue
    - profile + job type bounded batching
    - lease recovery / retry / backoff / durable audit
    - conflict refresh and compression runner
    - observability hooks for backlog / promotion / conflict / materialization / maintenance duration
  - **Service Architecture Refactoring (Phase 3 partial, 2026-06)**:
    - Protocol-based service interfaces (13 interfaces)
    - Dependency injection container (dual-layer: Application + RequestScope)
    - Service decomposition from monolithic `AutonomousTaskService`:
      - `TaskPlanLifecycleService`: plan/task CRUD, status updates (60% complete)
      - `TaskExecutionService`: task execution logic (100% complete)
      - `TaskAutonomySchedulingService`: autonomy state queries (25% complete)
      - `TaskRuntimeSkillService`: skill resolution (facade, pending refactor)
    - Callback pattern for complex coordination without circular dependencies
    - Backward compatibility maintained via dual-track operation
    - Documentation: `docs/PHASE3_MIGRATION_REPORT.md`
  - explicit non-goals for this phase:
    - non-HTTP external connectors
    - plugin marketplace/runtime
    - heavy external workflow scheduler

### Phase 3: Long-Term Memory

- Expand from session memory to layered persistent memory.
- Current implemented baseline:
  - knowledge memory / behavior memory dual entities
  - independent retrieval APIs
  - importance / confidence / freshness / stability / goal relevance metadata
  - `candidate -> active -> stable -> compressed / archived / suppressed` governed status model
  - governed auto-materialization from chat profile memory events, terminal task attempts, and evaluated reflection outcomes
  - upsert / dedupe for knowledge and behavior candidates using stable semantic identity keys
  - dynamic reinforcement / decay refresh during maintenance
  - stronger topic-key alignment and evidence extraction from task outcomes / reflection outcomes
  - governance summary aggregation for promotion candidates / demotion risk / topic buckets
  - evidence links / governance decisions / operator annotations
  - structured extraction validation and centralized `MemoryNormalizer`
  - explainable conflict sets with policy-derived status impact and live member memory details
  - dedicated `memory_maintenance_jobs` queue with bounded governance / compression / conflict refresh jobs
  - Prometheus / Grafana / alert baseline for candidate backlog, promotion rate, conflict rate, materialization failures, and maintenance duration
  - reflection corpus export for downstream reflection agents
  - operator API for suppress / annotate / restore
  - session memory remains the episodic source layer
- Still pending:
  - more adaptive decay / promotion thresholds
  - richer operator review surfaces
  - larger long-lived regression datasets covering multi-round learning, multiple goals, multiple topics, and migration upgrades

### Phase 4: Reflection System

- Analyze outcomes after execution.
- Current implemented baseline:
  - `ReflectionRecord / ReflectionAction` persistence
  - task / assessment / workflow / replan event-driven reflection triggers
  - rule-first root cause classification with bounded LLM summarization
  - low-risk autonomy follow-up execution through governed autonomy jobs
  - high-risk reflection actions blocked into `needs_review`
  - read APIs for goal/task/detail reflection inspection
  - reflection-v2 partial enhancements:
    - evidence signal persistence
    - outcome evaluation tracking
    - operator review / resolve / override
    - goal strategy card
    - reflective memory candidate layer
    - aggregate review queue on primary reflection records
    - automatic feedback write-back from outcome evaluation into strategy and reflective memory
    - long-term memory bridge from reflection outcomes
    - planner blueprint + LLM planning context informed by active strategy card
    - conservative autonomy-job scheduling for periodic goal reflection
    - worker-driven outcome evaluation sweep
    - proposal queue for prompt / workflow optimization
    - rule-based replay/evaluation for proposal validation
    - proposal sandbox / approval v1:
      - `ReflectionProposalSandboxRun`
      - archived replay live-LLM sandbox worker path
      - operator approval / rejection decisions
      - proposal evaluation read API
      - low / medium risk proposal auto-admission to sandbox
    - proposal rollout / rollback v1:
      - `ReflectionProposalRollout`
      - `ReflectionProposalRolloutObservation`
      - `ReflectionProposalRolloutDecision`
      - goal-scoped staged activation
      - chat / hint / quiz / plan_generation / review_scheduling / assessment_generation / replan rollout surfaces
      - rollout overlay consumption in chat / planner / task runtime
      - manual promote / rollback
      - rollout auto-governance V1 via a separate autonomy decision job; observation remains signal-only and does not inline rollout state transitions
      - current auto-governance allowlist is `review_scheduling / assessment_generation / replan`; `chat / hint / quiz / plan_generation` remain manual-only for rollout promote / rollback
      - planner rollback baseline replan
    - skill evolution MVP:
      - `skill_package` and `skill_patch_request` proposal types
      - `SkillArtifact` versioned lifecycle asset
      - `SkillUsageEvent` usage attribution
      - `SkillCuratorRecommendation` review carrier and `SkillCuratorJob` MVP
      - `patch_needed -> skill_patch_request -> replacement skill_package proposal -> staged replacement` governed path
      - `merge_candidate -> merge-sourced replacement skill_package proposal -> staged replacement` governed path
      - artifact overlap / duplicate detection input that emits `merge_candidate / none` recommendations without mutating artifacts
      - curator governance evidence input from memory conflict summaries, reflection outcome evaluations, and resolver health trends that emits or enriches `flag_for_review / none` recommendations without mutating artifacts
      - surface / topic coverage regression input that emits `patch_needed / none` recommendations from declared-topic drift and governed binding gaps without mutating artifacts
      - Prometheus / Grafana / alert baseline for skill usage, resolver failures, artifact status, curator backlog, recommendation rates, and curator job latency
      - rollout auto-governance observability for auto decision queued / executed / skipped and alerting on elevated auto rollback / skip rates
      - operator-protected replacement staging that preserves lineage / parent / supersedes provenance without automatic activate / replace
      - shared staged-replacement readiness evaluation, strict source-anchor gate, and curator ready recommendation before manual activate / replace
      - readiness read API returns `recommended_action` plus the unified replacement-readiness evidence summary used by operator review and curator recommendation
- Still pending:
  - deeper prompt / workflow optimization outputs
  - bundle / global rollout governance
  - broader rollout auto-governance beyond allowlisted workflow surfaces
  - staged replacement auto-activate / auto-replace
  - deeper session-signal evidence extraction
  - dynamic runtime skill registry V2, including richer multi-step tool-plan orchestration and fuller active-artifact runtime sourcing

### Phase 5: Skill Evolution

- Generate controlled proposals for new or improved skills.
- Evaluate proposals in sandboxed conditions before promotion.
- Current MVP can carry `patch_needed` and `merge_candidate` recommendations through governed replacement `skill_package` proposals and operator-staged replacement artifacts.
- Curator evidence v1 can incorporate memory conflict summaries, reflection outcome evaluations, and resolver health trends into review recommendations.
- Replacement staging stops at `staged`; activation or replacement remains governed by later evidence gates.
- Dynamic runtime registry V1 remains governed configuration sourcing, not dynamic code loading: handler registration and internal tool registration stay code-controlled, while artifacts and bindings provide directives, tool-plan, and rollout metadata.
- Chat, planner, and task/autonomy paths now share the same runtime-plan contract and usage attribution shape; chat / hint / quiz / plan_generation can emit rollout observation signals on success, while allowlisted task/autonomy workflow surfaces can emit observation on success and on runtime failure when a real workflow-run anchor exists, without inlining rollout state transitions.
- Rollout auto-governance V1 is intentionally narrower than replacement governance: it can auto-promote or auto-rollback allowlisted rollouts, but it does not auto-activate or auto-replace staged replacement artifacts.
- Replacement governance remains manual execution after evidence gates, and both direct `activate_staged` and `replace_selectable` now re-check readiness under locked artifact/selectable reads before state transition; recommendation accept failure emits durable `accept_failed` audit and leaves the recommendation pending.

### Phase 6: Multi-Agent Society

- Introduce richer inter-agent specialization and governance.
- Preserve role clarity, safety oversight, and auditability as the system becomes more autonomous.

## Recommended Technology Direction

The repository remains implementation-neutral at the architecture layer.
Current recommended reference stack from `README.md` is:

- API/service layer: FastAPI
- agent orchestration: LangGraph
- primary database: PostgreSQL
- vector retrieval: pgvector
- async and queueing: Redis, Celery, or equivalent
- long-running workflow runtime: Temporal or equivalent DAG/workflow engine

These are reference choices, not exclusive requirements.
Concrete implementation documents and code may refine them later.

## Repository Shape

The intended repository shape is a single repository with multiple logical modules.
The top-level organization should converge toward:

- `apps/`: runnable services, APIs, workers, or entrypoints
- `packages/`: shared domain logic, schemas, memory, workflow, and safety modules
- `infra/`: deployment, environment, operations, and infrastructure definitions
- `docs/`: extended design, ADRs, and implementation notes

Exact paths can evolve, but responsibilities should remain separated along these lines.

## Implementation Constraints

- Domain logic should not depend directly on infrastructure implementations.
- Safety and approval flows should be modeled explicitly rather than implied.
- Memory, reflection, and evolution writes should go through governed interfaces.
- New modules should map back to the canonical concepts in this document.
