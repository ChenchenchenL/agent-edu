# Memory System Defects & Gaps Analysis

## Overview

The memory system has a well-built **write path** (materialization from chat turns, task outcomes, reflection outcomes, and structured extraction), but the **read path** is severely disconnected — accumulated knowledge and behavior memories are not fed back into actual teaching conversations and task decisions.

---

## P0 — Critical

### 1. Knowledge/Behavior Memories Not Injected into Chat Context

**File:** `packages/agent_core/src/agent_core/application/services/chat.py`

`ChatService` builds conversation context by calling:
- `retrieve_relevant_session_memories` ✅
- `retrieve_relevant_profile_memories` ✅
- `retrieve_relevant_knowledge_memories` ❌ **NOT called**
- `retrieve_relevant_behavior_memories` ❌ **NOT called**

The `long_term_context` only contains `cross_session_context + profile_memory_summaries`. Long-term knowledge and behavior memories accumulated through materialization are **never used** during chat, making the entire long-term memory accumulation effectively invisible to the learner-facing agent.

**Impact:** The agent cannot leverage what it has "learned" about the learner's knowledge gaps, misconceptions, or behavioral patterns during conversations.

### 2. No Automatic Periodic Memory Maintenance Scheduling

**File:** `packages/agent_core/src/agent_core/application/services/memory.py`

`run_memory_maintenance()` is implemented (promotion evaluation, decay, compression, conflict refresh), but there is **no automatic periodic scheduling mechanism**. It depends on external invocation. Without an autonomy job trigger, memory quality degrades continuously without governance.

**Impact:** Memories stay in `candidate` state indefinitely, stale memories are never compressed, and conflict sets are never refreshed automatically.

---

## P1 — High

### 3. Conflict Detection Without Automatic Resolution

**File:** `packages/agent_core/src/agent_core/application/services/memory.py` (ConflictService)

`refresh_conflict_sets()` detects contradictory memories (e.g., misconception vs correct concept), but:
- Conflict resolution requires manual operator intervention
- No automatic suppression of low-quality conflicting memories
- Conflict status does not affect retrieval ranking — conflicting memories can still be retrieved and influence the learner

**Impact:** Contradictory memories may confuse the learner or produce inconsistent teaching behavior.

### 4. Behavior Memory Only Created on Task Failure/Skip

**File:** `packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py` (line ~140)

```python
if attempt.outcome_status in {"failed", "skipped"}:
    behavior = ...  # only creates behavior memory
```

Successfully completed tasks **do not produce behavior memories**, missing the opportunity to record effective learning strategies, preferred approaches, and positive patterns.

**Impact:** The system only remembers what went wrong, never what went right. This creates a negativity bias in behavior memory.

### 5. Interpretation & Reflection Corpus Not Consumed by Any Flow

**File:** `packages/agent_core/src/agent_core/application/services/memory.py`

- `build_interpretation()` produces learner profile interpretations (knowledge mastery, behavior patterns) but is never called by Chat, Planner, Task, or Reflection systems.
- `build_reflection_corpus()` produces prioritized action recommendations (reinforce/validate/refresh/observe/review) but these are not automatically consumed by the reflection trigger system.

**Impact:** Built-in intelligent analysis capabilities are wasted dead code.

---

## P2 — Medium

### 6. Retrieval Scoring Weights Are Hardcoded

**File:** `packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py` (line ~240)

```python
0.40 * similarity + 0.20 * importance + 0.15 * confidence
+ 0.10 * freshness + 0.10 * stability + 0.05 * goal_relevance
```

Different learning scenarios (exam review vs concept exploration vs hint generation) need different weight profiles, but the current system cannot adapt weights based on context.

**Impact:** Suboptimal memory retrieval for specific learning scenarios.

### 7. Embedding Dimension Incompatibility Without Degradation Strategy

**File:** `packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py` (line ~224)

```python
def cosine_similarity(left, right):
    if len(left) != len(right):
        return 0.0
```

If the embedding model is switched (different dimensions), all historical embeddings become invalid and return 0 similarity score. There is no migration, backfill, or fallback mechanism.

**Impact:** Switching embedding providers/models causes complete memory retrieval failure until all embeddings are regenerated.

### 8. Memory Replay Has No Maximum Retry Limit

**File:** `packages/agent_core/src/agent_core/application/services/chat.py` (line ~869)

Chat and Task materialization failures schedule replay jobs, but there is no visible maximum retry count limit. Theoretically, this could retry indefinitely.

**Impact:** In persistent failure scenarios (e.g., embedding provider down), replay jobs accumulate without bound.

### 9. Structured Extraction Hardcodes Freshness to 1.0

**File:** `packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py` (line ~358)

```python
freshness_score=1.0  # hardcoded maximum
```

LLM-extracted memories start at maximum freshness without evidence accumulation. This gives unverified LLM inferences the same weight as well-established memories.

**Impact:** Potentially incorrect LLM-extracted memories may dominate retrieval results initially.

---

## P3 — Low

### 10. No Cross-Goal Memory Aggregation

All retrieval methods require `learner_profile_id` or `session_id` with goal scoping. There is no support for cross-goal memory aggregation queries. When a learner has multiple learning goals, knowledge associations across goals cannot be retrieved.

**Impact:** Learners with multiple goals cannot benefit from cross-domain knowledge connections.

### 11. Freshness Decay Function Exists but Is Not Applied to Entities

**File:** `packages/agent_core/src/agent_core/application/services/learner_memory/retrieval.py` (line ~254)

`decay_freshness()` computes updated freshness based on time, but it is **never called during maintenance cycles** to update the actual memory entity's `freshness_score`. Freshness only decays at retrieval time as a scoring factor, not as a persisted state change.

**Impact:** Memory freshness scores in the database remain static, making governance decisions (compression, archival) based on stale data.

### 12. Reflection Corpus Does Not Drive Automatic Reflection Triggering

`build_reflection_corpus()` outputs prioritized recommendations, but the reflection trigger system still uses simple rules (e.g., task failure count). The corpus intelligence is not consumed.

**Impact:** Reflection triggering remains reactive rather than proactive, missing opportunities to reinforce weak knowledge before it causes failures.
