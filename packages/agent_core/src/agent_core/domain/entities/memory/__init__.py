"""Memory entities."""

from agent_core.domain.entities.memory.event import (
    MemoryEvent,
    MemoryEmbeddingRecord,
    RetrievedMemory,
    MemoryRetrievalResult,
)
from agent_core.domain.entities.memory.knowledge import (
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
    KnowledgeMemoryRetrievalResult,
    KnowledgeMemoryStatusUpdate,
)
from agent_core.domain.entities.memory.behavior import (
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    BehaviorMemoryRetrievalResult,
    BehaviorMemoryStatusUpdate,
)
from agent_core.domain.entities.memory.conflict import (
    MemoryConflictSet,
    MemoryConflictMember,
)
from agent_core.domain.entities.memory.governance import (
    ConflictStatusImpact,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
    MemoryAnnotation,
    RetrievedKnowledgeMemory,
    RetrievedBehaviorMemory,
)
from agent_core.domain.entities.memory.maintenance import (
    MemoryMaintenanceJob,
    MEMORY_MAINTENANCE_JOB_TYPES,
)

# Export all constants from event (since we copied the header to all, they are in event.py)
from agent_core.domain.entities.memory.event import (
    MEMORY_HORIZONS,
    KNOWLEDGE_LEVELS,
    BEHAVIOR_LEVELS,
    MEMORY_STATUSES,
    MEMORY_SCOPE_TYPES,
    MEMORY_TYPES,
    MEMORY_BEHAVIOR_CATEGORIES,
    MEMORY_SEMANTIC_CATEGORIES,
    MEMORY_VALIDATION_STATUSES,
    MEMORY_PROVENANCE_TYPES,
    MEMORY_EVIDENCE_SOURCE_TYPES,
    MEMORY_EVIDENCE_ROLES,
    MEMORY_DECISION_TYPES,
    MEMORY_DECISION_TRIGGER_SOURCES,
    MEMORY_ACTOR_TYPES,
    MEMORY_RETRIEVAL_STATUSES,
    MemoryFieldUnset,
)

__all__ = [
    # Event
    "MemoryEvent",
    "MemoryEmbeddingRecord",
    "RetrievedMemory",
    "MemoryRetrievalResult",
    # Knowledge
    "KnowledgeMemory",
    "KnowledgeMemoryEmbeddingRecord",
    "KnowledgeMemoryRetrievalResult",
    "KnowledgeMemoryStatusUpdate",
    # Behavior
    "BehaviorMemory",
    "BehaviorMemoryEmbeddingRecord",
    "BehaviorMemoryRetrievalResult",
    "BehaviorMemoryStatusUpdate",
    # Conflict
    "MemoryConflictSet",
    "MemoryConflictMember",
    # Governance
    "ConflictStatusImpact",
    "MemoryEvidenceLink",
    "MemoryGovernanceDecision",
    "MemoryAnnotation",
    "RetrievedKnowledgeMemory",
    "RetrievedBehaviorMemory",
    # Maintenance
    "MemoryMaintenanceJob",
    "MEMORY_MAINTENANCE_JOB_TYPES",
    # Constants
    "MEMORY_HORIZONS",
    "KNOWLEDGE_LEVELS",
    "BEHAVIOR_LEVELS",
    "MEMORY_STATUSES",
    "MEMORY_SCOPE_TYPES",
    "MEMORY_TYPES",
    "MEMORY_BEHAVIOR_CATEGORIES",
    "MEMORY_SEMANTIC_CATEGORIES",
    "MEMORY_VALIDATION_STATUSES",
    "MEMORY_PROVENANCE_TYPES",
    "MEMORY_EVIDENCE_SOURCE_TYPES",
    "MEMORY_EVIDENCE_ROLES",
    "MEMORY_DECISION_TYPES",
    "MEMORY_DECISION_TRIGGER_SOURCES",
    "MEMORY_ACTOR_TYPES",
    "MEMORY_RETRIEVAL_STATUSES",
    "MemoryFieldUnset",
]
