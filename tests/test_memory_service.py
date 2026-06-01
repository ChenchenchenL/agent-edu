from datetime import date, datetime, timezone
from pathlib import Path

from agent_core.application.services.audit import AuditService
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import (
    BehaviorMemoryEmbeddingRecord,
    ConflictStatusImpact,
    KnowledgeMemoryEmbeddingRecord,
    MemoryAnnotation,
    MemoryConflictMember,
    MemoryConflictSet,
    MemoryEmbeddingRecord,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
)
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.errors import ValidationError


class StubMemoryRepository:
    def __init__(self):
        self.events = []

    async def create(self, entity):
        self.events.append(entity)

    async def list_by_profile_since(self, *, learner_profile_id, since):
        return [
            item
            for item in self.events
            if getattr(item, "learner_profile_id", None) == learner_profile_id and getattr(item, "created_at", since) >= since
        ]


class StubMemoryEmbeddingRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity: MemoryEmbeddingRecord):
        self.records.append(entity)

    async def list_recent_by_session(self, *, session_id, limit):
        return [item for item in self.records if item.session_id == session_id][-limit:]

    async def list_recent_by_profile(self, *, learner_profile_id, limit):
        return [item for item in self.records if item.learner_profile_id == learner_profile_id][-limit:]


class StubEmbeddingProvider:
    provider_name = "stub"
    model_name = "stub-embedding-v1"

    async def embed_texts(self, texts):
        mapping = {
            "matrix multiplication basics": [1.0, 0.0],
            "learner struggled with determinants": [0.8, 0.2],
            "triangle proof strategy": [0.0, 1.0],
            "how do I multiply two matrices?": [1.0, 0.1],
            "Topic: Matrices | Concept focus: I am confused about | Struggle: I am confused about matrix multiplication. | Progress: Session advanced with a structured reply: Definition: Matrix multiplication combines rows and columns. | Mode: chat": [1.0, 0.0],
            "Learner profile update for Matrices. Current concept trend: I am confused about. Recurring struggle: I am confused about matrix multiplication.. Progress signal: Session advanced with a structured reply: Definition: Matrix multiplication combines rows and columns..": [0.8, 0.2],
        }
        vectors = []
        for text in texts:
            if text in mapping:
                vectors.append(mapping[text])
            elif text.casefold().startswith("knowledge:"):
                vectors.append([1.0, 0.0])
            elif text.casefold().startswith("behavior:"):
                vectors.append([0.8, 0.2])
            elif text.casefold().startswith("knowledge cluster"):
                vectors.append([1.0, 0.0])
            elif text.casefold().startswith("behavior cluster"):
                vectors.append([0.8, 0.2])
            else:
                vectors.append([0.5, 0.5])
        return vectors


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class FailingMemoryRepository(StubMemoryRepository):
    async def create(self, entity):
        raise RuntimeError("memory write failed")


class FailingEmbeddingProvider(StubEmbeddingProvider):
    async def embed_texts(self, texts):
        raise RuntimeError("embedding generation failed")


class FailingEmbeddingRepository(StubMemoryEmbeddingRepository):
    async def create(self, entity: MemoryEmbeddingRecord):
        raise RuntimeError("embedding persist failed")


class StubKnowledgeMemoryRepository:
    def __init__(self):
        self.memories = []
        self.created_statuses = []
        self.updated_memories = []

    async def create(self, entity):
        self.created_statuses.append(entity.status)
        self.memories.append(entity)
        return None

    async def update(self, entity):
        self.updated_memories.append(entity)
        for index, item in enumerate(self.memories):
            if item.id == entity.id:
                self.memories[index] = entity
                break

    async def get_by_id(self, memory_id: str):
        for item in self.memories:
            if item.id == memory_id:
                return item
        return None

    async def list_by_ids(self, memory_ids: list[str]):
        return [item for item in self.memories if item.id in memory_ids]

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        knowledge_key: str,
        semantic_category: str,
        statuses: set[str] | None = None,
    ):
        for item in reversed(self.memories):
            if (
                item.learner_profile_id == learner_profile_id
                and item.learner_goal_id == learner_goal_id
                and item.knowledge_key == knowledge_key
                and item.semantic_category == semantic_category
                and (statuses is None or item.status in statuses)
            ):
                return item
        return None

    async def list_by_profile(
        self,
        learner_profile_id: str,
        *,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ):
        allowed = statuses or {"active", "stable"}
        items = [
            item
            for item in self.memories
            if item.learner_profile_id == learner_profile_id
            and item.status in allowed
            and (learner_goal_id is None or item.learner_goal_id == learner_goal_id)
        ]
        sliced = items[offset:]
        return sliced if limit is None else sliced[:limit]

    async def list_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        statuses: set[str],
        after_id: str | None,
        limit: int,
    ):
        return [
            item
            for item in sorted(self.memories, key=lambda memory: memory.id)
            if item.learner_profile_id == learner_profile_id
            and item.status in statuses
            and (after_id is None or item.id > after_id)
        ][:limit]

    async def list_profile_ids_with_statuses(self, statuses: set[str]):
        return sorted({item.learner_profile_id for item in self.memories if item.status in statuses})

    async def list_profile_ids_with_active_memories(self):
        return await self.list_profile_ids_with_statuses({"active", "stable"})


class StubBehaviorMemoryRepository:
    def __init__(self):
        self.memories = []
        self.created_statuses = []
        self.updated_memories = []

    async def create(self, entity):
        self.created_statuses.append(entity.status)
        self.memories.append(entity)
        return None

    async def update(self, entity):
        self.updated_memories.append(entity)
        for index, item in enumerate(self.memories):
            if item.id == entity.id:
                self.memories[index] = entity
                break

    async def get_by_id(self, memory_id: str):
        for item in self.memories:
            if item.id == memory_id:
                return item
        return None

    async def list_by_ids(self, memory_ids: list[str]):
        return [item for item in self.memories if item.id in memory_ids]

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        statuses: set[str] | None = None,
    ):
        for item in reversed(self.memories):
            if (
                item.learner_profile_id == learner_profile_id
                and item.learner_goal_id == learner_goal_id
                and item.behavior_key == behavior_key
                and item.behavior_category == behavior_category
                and (statuses is None or item.status in statuses)
            ):
                return item
        return None

    async def list_by_profile(
        self,
        learner_profile_id: str,
        *,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ):
        allowed = statuses or {"active", "stable"}
        items = [
            item
            for item in self.memories
            if item.learner_profile_id == learner_profile_id
            and item.status in allowed
            and (learner_goal_id is None or item.learner_goal_id == learner_goal_id)
        ]
        sliced = items[offset:]
        return sliced if limit is None else sliced[:limit]

    async def list_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        statuses: set[str],
        after_id: str | None,
        limit: int,
    ):
        return [
            item
            for item in sorted(self.memories, key=lambda memory: memory.id)
            if item.learner_profile_id == learner_profile_id
            and item.status in statuses
            and (after_id is None or item.id > after_id)
        ][:limit]

    async def list_profile_ids_with_statuses(self, statuses: set[str]):
        return sorted({item.learner_profile_id for item in self.memories if item.status in statuses})

    async def list_profile_ids_with_active_memories(self):
        return await self.list_profile_ids_with_statuses({"active", "stable"})


class RacingKnowledgeMemoryRepository(StubKnowledgeMemoryRepository):
    def __init__(self, existing):
        super().__init__()
        self.memories = [existing]
        self.create_calls = 0

    async def create(self, entity):
        self.created_statuses.append(entity.status)
        self.create_calls += 1
        return self.memories[0]

    async def get_by_identity(self, **kwargs):
        if self.create_calls == 0:
            return None
        return await super().get_by_identity(**kwargs)


class RacingBehaviorMemoryRepository(StubBehaviorMemoryRepository):
    def __init__(self, existing):
        super().__init__()
        self.memories = [existing]
        self.create_calls = 0

    async def create(self, entity):
        self.created_statuses.append(entity.status)
        self.create_calls += 1
        return self.memories[0]

    async def get_by_identity(self, **kwargs):
        if self.create_calls == 0:
            return None
        return await super().get_by_identity(**kwargs)


class StubKnowledgeMemoryEmbeddingRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity: KnowledgeMemoryEmbeddingRecord):
        self.records.append(entity)

    async def update(self, entity: KnowledgeMemoryEmbeddingRecord):
        for index, item in enumerate(self.records):
            if item.id == entity.id:
                self.records[index] = entity
                break

    async def get_by_memory_id(self, memory_id: str):
        for item in self.records:
            if item.memory_id == memory_id:
                return item
        return None

    async def list_recent_by_profile(self, *, learner_profile_id, limit, statuses: set[str] | None = None):
        allowed = statuses or {"active", "stable"}
        return [item for item in self.records if item.learner_profile_id == learner_profile_id and item.status in allowed][-limit:]

    async def list_by_profile(self, *, learner_profile_id):
        return [item for item in self.records if item.learner_profile_id == learner_profile_id]


class StubBehaviorMemoryEmbeddingRepository:
    def __init__(self):
        self.records = []

    async def create(self, entity: BehaviorMemoryEmbeddingRecord):
        self.records.append(entity)

    async def update(self, entity: BehaviorMemoryEmbeddingRecord):
        for index, item in enumerate(self.records):
            if item.id == entity.id:
                self.records[index] = entity
                break

    async def get_by_memory_id(self, memory_id: str):
        for item in self.records:
            if item.memory_id == memory_id:
                return item
        return None

    async def list_recent_by_profile(self, *, learner_profile_id, limit, statuses: set[str] | None = None):
        allowed = statuses or {"active", "stable"}
        return [item for item in self.records if item.learner_profile_id == learner_profile_id and item.status in allowed][-limit:]

    async def list_by_profile(self, *, learner_profile_id):
        return [item for item in self.records if item.learner_profile_id == learner_profile_id]


class StubMemoryEvidenceLinkRepository:
    def __init__(self):
        self.records: dict[tuple[str, str, str, str, str], MemoryEvidenceLink] = {}

    async def upsert(self, entity: MemoryEvidenceLink):
        key = (
            entity.memory_type,
            entity.memory_id,
            entity.evidence_source_type,
            entity.evidence_source_id,
            entity.evidence_role,
        )
        self.records[key] = entity

    async def list_by_memory(self, *, memory_type: str, memory_id: str):
        return [
            item
            for item in self.records.values()
            if item.memory_type == memory_type and item.memory_id == memory_id
        ]

    async def list_by_profile(self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit: int = 100):
        items = [
            item
            for item in self.records.values()
            if item.learner_profile_id == learner_profile_id
            and (learner_goal_id is None or item.learner_goal_id == learner_goal_id)
        ]
        return items[:limit]


class StubMemoryGovernanceDecisionRepository:
    def __init__(self):
        self.records: list[MemoryGovernanceDecision] = []

    async def create(self, entity: MemoryGovernanceDecision):
        self.records.append(entity)

    async def list_by_memory(self, *, memory_type: str, memory_id: str):
        return [
            item
            for item in self.records
            if item.memory_type == memory_type and item.memory_id == memory_id
        ]

    async def list_by_profile(self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit: int = 100):
        return self.records[-limit:]


class StubMemoryAnnotationRepository:
    def __init__(self):
        self.records: list[MemoryAnnotation] = []

    async def create(self, entity: MemoryAnnotation):
        self.records.append(entity)

    async def list_by_memory(self, *, memory_type: str, memory_id: str):
        return [
            item
            for item in self.records
            if item.memory_type == memory_type and item.memory_id == memory_id
        ]


class StubMemoryConflictRepository:
    def __init__(self):
        self.sets: list[MemoryConflictSet] = []
        self.members: list[MemoryConflictMember] = []

    async def upsert_set(self, *, conflict_set: MemoryConflictSet, members: list[MemoryConflictMember]):
        existing = next(
            (
                item
                for item in self.sets
                if item.learner_profile_id == conflict_set.learner_profile_id
                and item.learner_goal_id == conflict_set.learner_goal_id
                and item.topic_key == conflict_set.topic_key
                and item.conflict_type == conflict_set.conflict_type
                and item.status == "open"
            ),
            None,
        )
        conflict_set_id = conflict_set.id
        if existing is None:
            self.sets.append(conflict_set)
            created = True
        else:
            conflict_set_id = existing.id
            self.sets[self.sets.index(existing)] = MemoryConflictSet(
                id=existing.id,
                learner_profile_id=existing.learner_profile_id,
                learner_goal_id=existing.learner_goal_id,
                topic_key=existing.topic_key,
                conflict_type=existing.conflict_type,
                severity_score=conflict_set.severity_score,
                status=existing.status,
                summary=conflict_set.summary,
                created_at=existing.created_at,
                updated_at=conflict_set.updated_at,
                reason_code=conflict_set.reason_code,
                reason_note=conflict_set.reason_note,
                handling_result=conflict_set.handling_result,
                status_impact=conflict_set.status_impact,
            )
            self.members = [
                MemoryConflictMember(
                    id=item.id,
                    conflict_set_id=item.conflict_set_id,
                    memory_type=item.memory_type,
                    memory_id=item.memory_id,
                    memory_key=item.memory_key,
                    stance="superseded" if item.conflict_set_id == existing.id else item.stance,
                    support_score=item.support_score,
                    contradiction_score=item.contradiction_score,
                    created_at=item.created_at,
                )
                for item in self.members
            ]
            created = False
        self.members.extend(
            MemoryConflictMember(
                id=item.id,
                conflict_set_id=conflict_set_id,
                memory_type=item.memory_type,
                memory_id=item.memory_id,
                memory_key=item.memory_key,
                stance=item.stance,
                support_score=item.support_score,
                contradiction_score=item.contradiction_score,
                created_at=item.created_at,
            )
            for item in members
        )
        stored = next(item for item in self.sets if item.id == conflict_set_id)
        return stored, created

    async def list_sets_by_profile(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ):
        items = [
            item
            for item in self.sets
            if item.learner_profile_id == learner_profile_id
            and (learner_goal_id is None or item.learner_goal_id == learner_goal_id)
            and (status is None or item.status == status)
        ]
        return sorted(items, key=lambda item: item.severity_score, reverse=True)[:limit]

    async def list_open_sets(self):
        return [item for item in self.sets if item.status == "open"]

    async def list_profile_ids_with_open_sets(self):
        return sorted({item.learner_profile_id for item in self.sets if item.status == "open"})

    async def count_open_by_type(self):
        counts: dict[str, int] = {}
        for item in self.sets:
            if item.status != "open":
                continue
            counts[item.conflict_type] = counts.get(item.conflict_type, 0) + 1
        return counts

    async def list_open_sets_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        after_id: str | None,
        limit: int,
    ):
        return [
            item
            for item in sorted(self.sets, key=lambda conflict_set: conflict_set.id)
            if item.learner_profile_id == learner_profile_id
            and item.status == "open"
            and (after_id is None or item.id > after_id)
        ][:limit]

    async def close_open_set(
        self,
        *,
        conflict_set_id: str,
        status: str,
        summary: str | None = None,
        reason_code: str | None = None,
        reason_note: str | None = None,
        handling_result: str | None = None,
        status_impact: ConflictStatusImpact | None = None,
    ):
        for index, item in enumerate(self.sets):
            if item.id != conflict_set_id or item.status != "open":
                continue
            self.sets[index] = MemoryConflictSet(
                id=item.id,
                learner_profile_id=item.learner_profile_id,
                learner_goal_id=item.learner_goal_id,
                topic_key=item.topic_key,
                conflict_type=item.conflict_type,
                severity_score=item.severity_score,
                status=status,
                summary=summary if summary is not None else item.summary,
                created_at=item.created_at,
                updated_at=datetime.now(timezone.utc),
                reason_code=reason_code or item.reason_code,
                reason_note=reason_note if reason_note is not None else item.reason_note,
                handling_result=handling_result or item.handling_result,
                status_impact=status_impact if status_impact is not None else item.status_impact,
            )
            break

    async def list_members(self, *, conflict_set_id: str):
        return [item for item in self.members if item.conflict_set_id == conflict_set_id]


class StubTaskAttemptRepository:
    def __init__(self):
        self.records: list[TaskAttempt] = []

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int):
        return [item for item in self.records if item.learner_goal_id == learner_goal_id][-limit:]


class StubLearnerTopicMasteryRepository:
    def __init__(self):
        self.records: list[LearnerTopicMastery] = []

    async def get_by_goal_and_topic(self, learner_goal_id: str, topic_key: str):
        for item in self.records:
            if item.learner_goal_id == learner_goal_id and item.topic_key == topic_key:
                return item
        return None


def _with_id(entity, entity_id: str):
    return type(entity)(**{**entity.__dict__, "id": entity_id})


async def test_record_session_event_writes_embedding_and_audit_when_provider_is_configured():
    memory_repository = StubMemoryRepository()
    embedding_repository = StubMemoryEmbeddingRepository()
    audit_repository = StubAuditRepository()
    service = MemoryService(
        memory_repository,
        embedding_repository=embedding_repository,
        embedding_provider=StubEmbeddingProvider(),
        audit_service=AuditService(audit_repository),
    )

    event = await service.record_session_event(
        session_id="session-1",
        learner_profile_id="profile-1",
        memory_scope="session",
        memory_level="episodic",
        summary="matrix multiplication basics",
        progress_note="Learner received a structured explanation.",
        struggle_note="Learner asked for help with multiplication.",
        concept_focus="matrix multiplication",
        source_message_id="message-1",
        tags=["session", "chat"],
    )

    assert event.summary == "matrix multiplication basics"
    assert event.learner_profile_id == "profile-1"
    assert event.memory_scope == "session"
    assert len(memory_repository.events) == 1
    assert len(embedding_repository.records) == 1
    assert embedding_repository.records[0].memory_event_id == event.id
    assert embedding_repository.records[0].dimensions == 2
    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_type == "memory.event.recorded"
    assert audit_repository.events[0].event_data["embedding_dimensions"] == 2


async def test_retrieve_relevant_session_memories_returns_top_matches():
    embedding_repository = StubMemoryEmbeddingRepository()
    embedding_repository.records = [
        MemoryEmbeddingRecord(
            id="e1",
            memory_event_id="m1",
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[1.0, 0.0],
            summary="matrix multiplication basics",
            created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
        ),
        MemoryEmbeddingRecord(
            id="e2",
            memory_event_id="m2",
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="profile",
            memory_level="semantic",
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[0.8, 0.2],
            summary="learner struggled with determinants",
            created_at=datetime(2026, 5, 19, 8, 1, tzinfo=timezone.utc),
        ),
        MemoryEmbeddingRecord(
            id="e3",
            memory_event_id="m3",
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[0.0, 1.0],
            summary="triangle proof strategy",
            created_at=datetime(2026, 5, 19, 8, 2, tzinfo=timezone.utc),
        ),
    ]
    service = MemoryService(
        StubMemoryRepository(),
        embedding_repository=embedding_repository,
        embedding_provider=StubEmbeddingProvider(),
    )

    result = await service.retrieve_relevant_session_memories(
        session_id="session-1",
        query_text="how do I multiply two matrices?",
        limit=2,
        candidate_limit=10,
        min_score=0.2,
    )

    assert result.provider == "stub"
    assert result.model == "stub-embedding-v1"
    assert len(result.memories) == 2
    assert result.memories[0].summary == "matrix multiplication basics"
    assert result.memories[1].summary == "learner struggled with determinants"


async def test_record_learning_memories_creates_session_and_profile_layers():
    memory_repository = StubMemoryRepository()
    embedding_repository = StubMemoryEmbeddingRepository()
    audit_repository = StubAuditRepository()
    service = MemoryService(
        memory_repository,
        embedding_repository=embedding_repository,
        embedding_provider=StubEmbeddingProvider(),
        audit_service=AuditService(audit_repository),
    )

    events = await service.record_learning_memories(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )

    assert len(events) == 2
    assert {item.memory_scope for item in events} == {"session", "profile"}
    assert any(item.struggle_note is not None for item in events)
    assert len(embedding_repository.records) == 2
    assert len(audit_repository.events) == 2
    assert {item.event_type for item in audit_repository.events} == {"memory.event.recorded"}


async def test_retrieve_relevant_profile_memories_returns_profile_scope_only():
    embedding_repository = StubMemoryEmbeddingRepository()
    embedding_repository.records = [
        MemoryEmbeddingRecord(
            id="e1",
            memory_event_id="m1",
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[1.0, 0.0],
            summary="matrix multiplication basics",
            created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
        ),
        MemoryEmbeddingRecord(
            id="e2",
            memory_event_id="m2",
            session_id="session-2",
            learner_profile_id="profile-1",
            memory_scope="profile",
            memory_level="semantic",
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[0.8, 0.2],
            summary="learner struggled with determinants",
            created_at=datetime(2026, 5, 19, 8, 1, tzinfo=timezone.utc),
        ),
    ]
    service = MemoryService(
        StubMemoryRepository(),
        embedding_repository=embedding_repository,
        embedding_provider=StubEmbeddingProvider(),
    )

    result = await service.retrieve_relevant_profile_memories(
        learner_profile_id="profile-1",
        query_text="how do I multiply two matrices?",
        limit=2,
        candidate_limit=10,
        min_score=0.2,
    )

    assert len(result.memories) == 1
    assert result.memories[0].memory_scope == "profile"


async def test_record_session_event_failure_writes_durable_audit():
    audit_repository = StubAuditRepository()
    service = MemoryService(
        FailingMemoryRepository(),
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.record_session_event(
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            summary="matrix multiplication basics",
            progress_note="Learner received a structured explanation.",
            struggle_note="Learner asked for help with multiplication.",
            concept_focus="matrix multiplication",
            source_message_id="message-1",
            tags=["session", "chat"],
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "memory write failed" in str(exc)

    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_type == "memory.event.record.failed"
    assert audit_repository.events[0].event_data["failure_stage"] == "memory_event.persist"


async def test_record_session_event_embedding_failure_writes_durable_audit():
    memory_repository = StubMemoryRepository()
    audit_repository = StubAuditRepository()
    service = MemoryService(
        memory_repository,
        embedding_repository=StubMemoryEmbeddingRepository(),
        embedding_provider=FailingEmbeddingProvider(),
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.record_session_event(
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            summary="matrix multiplication basics",
            progress_note="Learner received a structured explanation.",
            struggle_note="Learner asked for help with multiplication.",
            concept_focus="matrix multiplication",
            source_message_id="message-1",
            tags=["session", "chat"],
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "embedding generation failed" in str(exc)

    assert len(memory_repository.events) == 1
    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_data["failure_stage"] == "embedding.generate"


async def test_record_session_event_embedding_persist_failure_writes_durable_audit():
    audit_repository = StubAuditRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_repository=FailingEmbeddingRepository(),
        embedding_provider=StubEmbeddingProvider(),
        audit_service=AuditService(audit_repository),
    )

    try:
        await service.record_session_event(
            session_id="session-1",
            learner_profile_id="profile-1",
            memory_scope="session",
            memory_level="episodic",
            summary="matrix multiplication basics",
            progress_note="Learner received a structured explanation.",
            struggle_note="Learner asked for help with multiplication.",
            concept_focus="matrix multiplication",
            source_message_id="message-1",
            tags=["session", "chat"],
        )
        assert False, "Expected RuntimeError"
    except RuntimeError as exc:
        assert "embedding persist failed" in str(exc)

    assert len(audit_repository.events) == 1
    assert audit_repository.events[0].event_data["failure_stage"] == "embedding.persist"


async def test_record_long_term_memories_is_deprecated():
    service = MemoryService(StubMemoryRepository())

    try:
        await service.record_long_term_memories(
            session_id="session-1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            learner_message="I am confused about matrix multiplication.",
            assistant_message="Definition: Matrix multiplication combines rows and columns.",
            source_message_id="message-1",
            mode="chat",
            subject="Matrices",
            session_title="Linear Algebra",
            persist_embeddings=True,
        )
        assert False, "Expected ValidationError"
    except ValidationError as exc:
        assert "LongTermMemoryMaterializationService" in str(exc)


async def test_upsert_long_term_memory_refreshes_existing_identity_without_duplicate():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
    )

    first_knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-1"],
        provenance_type="session_event",
        provenance_source_id="event-1",
    )
    second_knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication again.",
        assistant_message="Matrix multiplication still combines rows and columns.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-2"],
        provenance_type="session_event",
        provenance_source_id="event-2",
    )
    assert first_knowledge is not None
    assert second_knowledge is not None

    created = await service.upsert_knowledge_memory(first_knowledge)
    refreshed = await service.upsert_knowledge_memory(second_knowledge)

    assert created.action == "created"
    assert refreshed.action == "refreshed"
    assert len(knowledge_repository.memories) == 1
    assert refreshed.memory.id == created.memory.id
    assert refreshed.memory.source_event_ids == ["event-1", "event-2"]
    assert refreshed.memory.provenance_source_id == "event-1"

    first_behavior = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need help with matrix multiplication.",
        assistant_message="Try a guided row-column example.",
        source_message_id="message-1",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-1"],
        provenance_type="session_event",
        provenance_source_id="event-1",
    )
    second_behavior = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need help with matrix multiplication again.",
        assistant_message="Try another guided row-column example.",
        source_message_id="message-2",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-2"],
        provenance_type="session_event",
        provenance_source_id="event-2",
    )
    assert first_behavior is not None
    assert second_behavior is not None

    created_behavior = await service.upsert_behavior_memory(first_behavior)
    refreshed_behavior = await service.upsert_behavior_memory(second_behavior)

    assert created_behavior.action == "created"
    assert refreshed_behavior.action == "refreshed"
    assert len(behavior_repository.memories) == 1
    assert refreshed_behavior.memory.id == created_behavior.memory.id
    assert refreshed_behavior.memory.source_event_ids == ["event-1", "event-2"]


async def test_upsert_long_term_memory_handles_identity_race_without_duplicate_or_active_mutation():
    base_service = MemoryService(StubMemoryRepository())
    existing_knowledge = base_service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id=None,
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-1"],
        provenance_type="session_event",
        provenance_source_id="event-1",
    )
    incoming_knowledge = base_service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id=None,
        learner_message="I am confused about matrix multiplication again.",
        assistant_message="Matrix multiplication combines rows and columns again.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-2"],
        provenance_type="session_event",
        provenance_source_id="event-2",
    )
    assert existing_knowledge is not None
    assert incoming_knowledge is not None
    knowledge_repository = RacingKnowledgeMemoryRepository(existing_knowledge)
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
    )

    refreshed = await service.upsert_knowledge_memory(incoming_knowledge, persist_embedding=True)

    assert refreshed.action == "refreshed"
    assert refreshed.memory.id == existing_knowledge.id
    assert len(knowledge_repository.memories) == 1
    assert knowledge_repository.create_calls == 1
    assert knowledge_repository.memories[0].source_event_ids == ["event-1", "event-2"]
    assert knowledge_embedding_repository.records == []

    active_knowledge = existing_knowledge.with_status("active")
    active_repository = RacingKnowledgeMemoryRepository(active_knowledge)
    active_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=active_repository,
        knowledge_memory_embedding_repository=active_embedding_repository,
    )

    evidence_only = await service.upsert_knowledge_memory(incoming_knowledge, persist_embedding=True)

    assert evidence_only.action == "evidence_only"
    assert evidence_only.memory.id == active_knowledge.id
    assert evidence_only.memory.summary == active_knowledge.summary
    assert active_repository.updated_memories == []
    assert active_embedding_repository.records == []

    existing_behavior = base_service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id=None,
        learner_message="I need help with matrix multiplication.",
        assistant_message="Try a guided row-column example.",
        source_message_id="message-1",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-1"],
        provenance_type="session_event",
        provenance_source_id="event-1",
    )
    incoming_behavior = base_service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id=None,
        learner_message="I need help with matrix multiplication again.",
        assistant_message="Try another guided row-column example.",
        source_message_id="message-2",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-2"],
        provenance_type="session_event",
        provenance_source_id="event-2",
    )
    assert existing_behavior is not None
    assert incoming_behavior is not None
    behavior_repository = RacingBehaviorMemoryRepository(existing_behavior)
    behavior_embedding_repository = StubBehaviorMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        behavior_memory_repository=behavior_repository,
        behavior_memory_embedding_repository=behavior_embedding_repository,
    )

    behavior_refreshed = await service.upsert_behavior_memory(incoming_behavior, persist_embedding=True)

    assert behavior_refreshed.action == "refreshed"
    assert behavior_refreshed.memory.id == existing_behavior.id
    assert len(behavior_repository.memories) == 1
    assert behavior_repository.memories[0].source_event_ids == ["event-1", "event-2"]
    assert behavior_embedding_repository.records == []

    stable_behavior = existing_behavior.with_status("stable")
    stable_repository = RacingBehaviorMemoryRepository(stable_behavior)
    stable_embedding_repository = StubBehaviorMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        behavior_memory_repository=stable_repository,
        behavior_memory_embedding_repository=stable_embedding_repository,
    )

    behavior_evidence_only = await service.upsert_behavior_memory(incoming_behavior, persist_embedding=True)

    assert behavior_evidence_only.action == "evidence_only"
    assert behavior_evidence_only.memory.id == stable_behavior.id
    assert behavior_evidence_only.memory.summary == stable_behavior.summary
    assert stable_repository.updated_memories == []
    assert stable_embedding_repository.records == []


async def test_upsert_long_term_memory_does_not_restore_suppressed_memory():
    knowledge_repository = StubKnowledgeMemoryRepository()
    service = MemoryService(StubMemoryRepository(), knowledge_memory_repository=knowledge_repository)
    memory = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrices.",
        assistant_message="Matrix basics.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert memory is not None
    suppressed = memory.with_status("suppressed", suppressed_reason_code="manual_block")
    await knowledge_repository.create(suppressed)

    result = await service.upsert_knowledge_memory(memory)

    assert result.action == "skipped_suppressed"
    assert len(knowledge_repository.memories) == 1
    assert knowledge_repository.memories[0].status == "suppressed"


async def test_restore_memory_clears_suppression_metadata():
    knowledge_repository = StubKnowledgeMemoryRepository()
    service = MemoryService(StubMemoryRepository(), knowledge_memory_repository=knowledge_repository)
    memory = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrices.",
        assistant_message="Matrix basics.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert memory is not None
    await knowledge_repository.create(memory.with_status("suppressed", suppressed_reason_code="manual_block"))

    restored = await service.restore_memory(
        memory_type="knowledge",
        memory_id=knowledge_repository.memories[0].id,
        restore_to_status="candidate",
        reason="reviewed",
        actor_id="operator-1",
    )

    assert restored.status == "candidate"
    assert restored.suppressed_reason_code is None
    assert restored.suppressed_reason_note is None
    assert restored.suppressed_by is None
    assert restored.suppressed_at is None


async def test_materialize_chat_turn_uses_profile_memory_event_as_provenance_and_dedupes():
    memory_repository = StubMemoryRepository()
    knowledge_repository = StubKnowledgeMemoryRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    memory_service = MemoryService(
        memory_repository,
        knowledge_memory_repository=knowledge_repository,
        evidence_link_repository=evidence_repository,
    )
    materialization_service = LongTermMemoryMaterializationService(memory_service)
    memory_events = await memory_service.record_learning_memories(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    profile_event = next(item for item in memory_events if item.memory_scope == "profile")

    first = await materialization_service.materialize_from_chat_turn(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=memory_events,
        persist_embeddings=False,
    )
    second = await materialization_service.materialize_from_chat_turn(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=memory_events,
        persist_embeddings=False,
    )

    assert first.knowledge[0].action == "created"
    assert second.knowledge[0].action == "refreshed"
    assert len(knowledge_repository.memories) == 1
    knowledge = knowledge_repository.memories[0]
    assert knowledge.provenance_type == "session_event"
    assert knowledge.provenance_source_id == profile_event.id
    assert knowledge.source_event_ids == [profile_event.id]
    assert "message-1" not in knowledge.source_event_ids
    links = await evidence_repository.list_by_memory(memory_type="knowledge", memory_id=knowledge.id)
    assert len(links) == 1
    assert links[0].evidence_source_type == "session_memory_event"
    assert links[0].evidence_source_id == profile_event.id
    assert links[0].payload["source_message_id"] == "message-1"


def test_memory_normalizer_centralizes_topic_category_and_roles():
    assert MemoryNormalizer.normalize_topic_key("The Matrix Multiplication!") == "matrix-multiplication"
    assert MemoryNormalizer.classify_behavior_category(
        mode="hint",
        struggle_note=None,
        progress_note=None,
    ) == "support_request"
    assert MemoryNormalizer.classify_semantic_category(
        memory_type="knowledge",
        knowledge_level="foundation",
    ) == "prerequisite"
    assert MemoryNormalizer.classify_evidence_role(
        memory_type="behavior",
        evidence_source_type="task_attempt",
        outcome_status="failed",
    ) == "supporting"


async def test_structured_extraction_validates_model_output_and_only_writes_candidates():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    audit_repository = StubAuditRepository()
    materialization_service = LongTermMemoryMaterializationService(
        MemoryService(
            StubMemoryRepository(),
            knowledge_memory_repository=knowledge_repository,
            behavior_memory_repository=behavior_repository,
        ),
        audit_service=AuditService(audit_repository),
    )

    result = await materialization_service.materialize_from_structured_extraction(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        provenance_source_id="model-run-1",
        raw_candidates=[
            {
                "memory_type": "knowledge",
                "topic": "Matrix multiplication",
                "summary": "Learner may confuse row-column order.",
                "semantic_category": "misconception",
                "evidence_role": "supporting",
                "confidence_score": 0.7,
            },
            {
                "memory_type": "behavior",
                "topic": "Matrix multiplication",
                "summary": "Learner asks for scaffolded hints before retrying.",
                "behavior_category": "support_request",
                "evidence_role": "refreshing",
            },
            {
                "memory_type": "knowledge",
                "topic": "Matrices",
                "summary": "Model tried to force an active memory.",
                "status": "active",
            },
        ],
        persist_embeddings=False,
    )

    assert result.rejected_count == 1
    assert knowledge_repository.created_statuses == ["candidate"]
    assert behavior_repository.created_statuses == ["candidate"]
    assert knowledge_repository.memories[0].semantic_category == "misconception"
    assert knowledge_repository.memories[0].provenance_type == "system_inference"
    assert behavior_repository.memories[0].behavior_category == "support_request"
    assert all(item.status == "candidate" for item in knowledge_repository.memories + behavior_repository.memories)
    assert any(
        event.event_type == "long_term_memory.extraction.validation_failed"
        for event in audit_repository.events
    )


async def test_materialize_chat_turn_active_memory_is_evidence_only_without_mutating_embedding():
    memory_repository = StubMemoryRepository()
    knowledge_repository = StubKnowledgeMemoryRepository()
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    memory_service = MemoryService(
        memory_repository,
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
        evidence_link_repository=evidence_repository,
    )
    active = memory_service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        source_event_ids=["event-old"],
        provenance_type="session_event",
        provenance_source_id="event-old",
    )
    assert active is not None
    active = active.with_status(
        "active",
        support_score=0.7,
        evidence_count=3,
        stability_score=0.6,
        validation_status="locally_valid",
    )
    await knowledge_repository.create(active)
    await knowledge_embedding_repository.create(
        KnowledgeMemoryEmbeddingRecord.build(
            memory_id=active.id,
            learner_profile_id=active.learner_profile_id,
            learner_goal_id=active.learner_goal_id,
            knowledge_key=active.knowledge_key,
            title=active.title,
            summary=active.summary,
            knowledge_level=active.knowledge_level,
            time_horizon=active.time_horizon,
            importance_score=active.importance_score,
            confidence_score=active.confidence_score,
            freshness_score=active.freshness_score,
            stability_score=active.stability_score,
            goal_relevance_score=active.goal_relevance_score,
            scope_type=active.scope_type,
            provider="stub",
            model="stub-embedding-v1",
            vector=[0.25, 0.75],
            status=active.status,
        )
    )
    original_memory = knowledge_repository.memories[0]
    original_embedding = knowledge_embedding_repository.records[0]
    materialization_service = LongTermMemoryMaterializationService(memory_service)
    memory_events = await memory_service.record_learning_memories(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrix multiplication again.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    profile_event = next(item for item in memory_events if item.memory_scope == "profile")

    result = await materialization_service.materialize_from_chat_turn(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication again.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=memory_events,
        persist_embeddings=True,
    )

    assert result.knowledge[0].action == "evidence_only"
    assert knowledge_repository.memories == [original_memory]
    assert knowledge_embedding_repository.records == [original_embedding]
    links = await evidence_repository.list_by_memory(memory_type="knowledge", memory_id=active.id)
    assert len(links) == 1
    assert links[0].evidence_source_type == "session_memory_event"
    assert links[0].evidence_source_id == profile_event.id


async def test_materialize_task_outcome_creates_terminal_memories_and_task_attempt_evidence():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    memory_service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
        evidence_link_repository=evidence_repository,
    )
    materialization_service = LongTermMemoryMaterializationService(memory_service)
    task = DailyTask.build(
        learner_goal_id="goal-1",
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="practice",
        execution_mode="chat",
        title="Matrix multiplication practice",
        instructions="Work through a row-column multiplication example.",
        topic_focus="Matrix Multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=20,
        scheduled_for=date(2026, 5, 29),
        due_on=date(2026, 5, 29),
    )
    completed_task = task.with_status("completed", result_note="Finished the row-column practice.")
    completed_attempt = TaskAttempt.build(
        learner_goal_id="goal-1",
        daily_task_id=task.id,
        workflow_run_id="workflow-1",
        execution_session_id="session-1",
        task_type="practice",
        topic_focus=task.topic_focus,
        outcome_status="completed",
        score=0.86,
        result_note=completed_task.result_note,
    )

    first = await materialization_service.materialize_from_task_outcome(
        learner_profile_id="profile-1",
        task=completed_task,
        attempt=completed_attempt,
        persist_embeddings=False,
    )
    retry = await materialization_service.materialize_from_task_outcome(
        learner_profile_id="profile-1",
        task=completed_task,
        attempt=completed_attempt,
        persist_embeddings=False,
    )

    assert first.knowledge[0].action == "created"
    assert retry.knowledge[0].action == "refreshed"
    assert len(knowledge_repository.memories) == 1
    knowledge = knowledge_repository.memories[0]
    assert knowledge.provenance_type == "task_attempt"
    assert knowledge.provenance_source_id == completed_attempt.id
    assert knowledge.source_event_ids == []
    links = await evidence_repository.list_by_memory(memory_type="knowledge", memory_id=knowledge.id)
    assert len(links) == 1
    assert links[0].evidence_source_type == "task_attempt"
    assert links[0].evidence_source_id == completed_attempt.id
    assert links[0].evidence_role == "supporting"
    assert links[0].payload["daily_task_id"] == task.id

    failed_task = task.with_status("failed", result_note="Got the multiplication order wrong.")
    failed_attempt = TaskAttempt.build(
        learner_goal_id="goal-1",
        daily_task_id=task.id,
        workflow_run_id="workflow-2",
        execution_session_id="session-2",
        task_type="practice",
        topic_focus=task.topic_focus,
        outcome_status="failed",
        score=0.24,
        result_note=failed_task.result_note,
    )

    failed = await materialization_service.materialize_from_task_outcome(
        learner_profile_id="profile-1",
        task=failed_task,
        attempt=failed_attempt,
        persist_embeddings=False,
    )

    assert failed.knowledge[0].action == "refreshed"
    assert failed.behavior[0].action == "created"
    assert len(knowledge_repository.memories) == 1
    assert len(behavior_repository.memories) == 1
    behavior = behavior_repository.memories[0]
    assert behavior.provenance_type == "task_attempt"
    assert behavior.provenance_source_id == failed_attempt.id
    behavior_links = await evidence_repository.list_by_memory(memory_type="behavior", memory_id=behavior.id)
    assert len(behavior_links) == 1
    assert behavior_links[0].evidence_source_type == "task_attempt"
    assert behavior_links[0].evidence_source_id == failed_attempt.id
    assert behavior_links[0].evidence_role == "supporting"


async def test_materialize_task_outcome_skips_non_terminal_status():
    materialization_service = LongTermMemoryMaterializationService(MemoryService(StubMemoryRepository()))
    task = DailyTask.build(
        learner_goal_id="goal-1",
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="practice",
        execution_mode="chat",
        title="Matrix multiplication practice",
        instructions="Work through a row-column multiplication example.",
        topic_focus="Matrix Multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=20,
        scheduled_for=date(2026, 5, 29),
        due_on=date(2026, 5, 29),
    )
    attempt = TaskAttempt.build(
        learner_goal_id="goal-1",
        daily_task_id=task.id,
        workflow_run_id=None,
        execution_session_id=None,
        task_type="practice",
        topic_focus=task.topic_focus,
        outcome_status="in_progress",
        score=0.5,
        result_note=None,
    )

    result = await materialization_service.materialize_from_task_outcome(
        learner_profile_id="profile-1",
        task=task,
        attempt=attempt,
        persist_embeddings=False,
    )

    assert result.skipped_reason == "non_terminal_task_status"
    assert result.knowledge == []
    assert result.behavior == []


async def test_materialize_reflection_outcome_creates_candidate_and_reflection_evidence():
    knowledge_repository = StubKnowledgeMemoryRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    memory_service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=StubBehaviorMemoryRepository(),
        evidence_link_repository=evidence_repository,
    )
    materialization_service = LongTermMemoryMaterializationService(memory_service)
    reflection = ReflectionRecord.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id="task-1",
        workflow_run_id=None,
        study_plan_id=None,
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        duplicate_count=0,
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        priority_score=0.7,
        last_duplicate_at=None,
        cooldown_until=None,
        summary="Learner struggled with matrix multiplication.",
        evidence_summary="Repeated failure on matrix multiplication.",
        recommended_next_step="review prerequisite and retry",
        evidence_payload={"task": {"topic_focus": "Matrix Multiplication"}},
        aggregation_key="agg-1",
        dedupe_key="dedupe-1",
    )
    evaluation = ReflectionOutcomeEvaluation.build(
        reflection_record_id=reflection.id,
        learner_goal_id="goal-1",
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    ).with_result(
        evaluation_status="effective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 2},
        improvement_score=0.7,
        evaluation_note="improved",
        evaluated=True,
    )

    first = await materialization_service.materialize_from_reflection_outcome(
        reflection=reflection,
        evaluation=evaluation,
        persist_embeddings=False,
    )
    retry = await materialization_service.materialize_from_reflection_outcome(
        reflection=reflection,
        evaluation=evaluation,
        persist_embeddings=False,
    )

    assert first.knowledge[0].action == "created"
    assert retry.knowledge[0].action == "refreshed"
    assert len(knowledge_repository.memories) == 1
    knowledge = knowledge_repository.memories[0]
    assert knowledge.status == "candidate"
    assert knowledge.provenance_type == "reflection"
    assert knowledge.provenance_source_id == evaluation.id
    assert knowledge.source_event_ids == []
    links = await evidence_repository.list_by_memory(memory_type="knowledge", memory_id=knowledge.id)
    assert len(links) == 1
    assert links[0].evidence_source_type == "reflection_outcome"
    assert links[0].evidence_source_id == evaluation.id
    assert links[0].evidence_role == "supporting"
    assert links[0].payload["reflection_record_id"] == reflection.id


async def test_materialize_reflection_outcome_skips_missing_topic_and_pending_evaluation():
    materialization_service = LongTermMemoryMaterializationService(MemoryService(StubMemoryRepository()))
    reflection = ReflectionRecord.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id="task-1",
        workflow_run_id=None,
        study_plan_id=None,
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        duplicate_count=0,
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        priority_score=0.7,
        last_duplicate_at=None,
        cooldown_until=None,
        summary="Learner struggled with a task.",
        evidence_summary="Failure without a clear topic.",
        recommended_next_step="review prerequisite and retry",
        evidence_payload={},
        aggregation_key="agg-1",
        dedupe_key="dedupe-1",
    )
    pending = ReflectionOutcomeEvaluation.build(
        reflection_record_id=reflection.id,
        learner_goal_id="goal-1",
        topic_key=None,
        window_size=3,
        baseline_snapshot={},
    )

    unsupported = await materialization_service.materialize_from_reflection_outcome(
        reflection=reflection,
        evaluation=pending,
        persist_embeddings=False,
    )
    ineffective = pending.with_result(
        evaluation_status="ineffective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 0},
        improvement_score=0.1,
        evaluation_note="not improved",
        evaluated=True,
    )
    missing_topic = await materialization_service.materialize_from_reflection_outcome(
        reflection=reflection,
        evaluation=ineffective,
        persist_embeddings=False,
    )

    assert unsupported.skipped_reason == "unsupported_evaluation_status"
    assert missing_topic.skipped_reason == "missing_reflection_topic"


async def test_materialization_does_not_add_evidence_to_suppressed_memory():
    knowledge_repository = StubKnowledgeMemoryRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    memory_service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        evidence_link_repository=evidence_repository,
    )
    existing = memory_service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrices.",
        assistant_message="Matrix basics.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert existing is not None
    await knowledge_repository.create(existing.with_status("suppressed", suppressed_reason_code="operator_block"))
    materialization_service = LongTermMemoryMaterializationService(memory_service)
    memory_events = await memory_service.record_learning_memories(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrices.",
        assistant_message="Matrix basics.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )

    result = await materialization_service.materialize_from_chat_turn(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrices.",
        assistant_message="Matrix basics.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=memory_events,
        persist_embeddings=False,
    )

    assert result.knowledge[0].action == "skipped_suppressed"
    assert len(knowledge_repository.memories) == 1
    assert knowledge_repository.memories[0].status == "suppressed"
    assert evidence_repository.records == {}


async def test_retrieve_long_term_memories_uses_weighted_ranking():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    behavior_embedding_repository = StubBehaviorMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
        behavior_memory_repository=behavior_repository,
        behavior_memory_embedding_repository=behavior_embedding_repository,
    )

    knowledge_embedding_repository.records = [
        KnowledgeMemoryEmbeddingRecord(
            id="k1",
            memory_id="km1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            knowledge_key="matrices",
            title="Matrices",
            summary="matrix multiplication basics",
            knowledge_level="core",
            time_horizon="mid",
            importance_score=0.9,
            confidence_score=0.8,
            freshness_score=1.0,
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[1.0, 0.0],
            status="active",
            created_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
        )
    ]
    behavior_embedding_repository.records = [
        BehaviorMemoryEmbeddingRecord(
            id="b1",
            memory_id="bm1",
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            behavior_key="support-request-matrices",
            behavior_category="support_request",
            title="Support request",
            summary="learner struggled with determinants",
            behavior_level="recurrent",
            time_horizon="mid",
            importance_score=0.7,
            confidence_score=0.9,
            freshness_score=1.0,
            provider="stub",
            model="stub-embedding-v1",
            dimensions=2,
            vector=[0.8, 0.2],
            status="active",
            created_at=datetime(2026, 5, 19, 8, 1, tzinfo=timezone.utc),
        )
    ]

    knowledge_result = await service.retrieve_relevant_knowledge_memories(
        learner_profile_id="profile-1",
        query_text="how do I multiply two matrices?",
        limit=2,
        candidate_limit=10,
        min_score=0.1,
    )
    behavior_result = await service.retrieve_relevant_behavior_memories(
        learner_profile_id="profile-1",
        query_text="how do I multiply two matrices?",
        limit=2,
        candidate_limit=10,
        min_score=0.1,
    )

    assert len(knowledge_result.memories) == 1
    assert knowledge_result.memories[0].memory_id == "km1"
    assert len(behavior_result.memories) == 1
    assert behavior_result.memories[0].memory_id == "bm1"


async def test_run_memory_maintenance_runs_governance_cycles_without_crashing():
    audit_repository = StubAuditRepository()
    knowledge_repository = StubKnowledgeMemoryRepository()
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    behavior_embedding_repository = StubBehaviorMemoryEmbeddingRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    task_attempt_repository = StubTaskAttemptRepository()
    learner_topic_mastery_repository = StubLearnerTopicMasteryRepository()
    task_attempt_repository.records = [
        TaskAttempt.build(
            learner_goal_id="goal-1",
            daily_task_id="task-1",
            workflow_run_id="run-1",
            execution_session_id="session-1",
            task_type="assessment",
            topic_focus="matrices",
            outcome_status="completed",
            score=0.92,
            result_note="Correctly explained matrix multiplication.",
        ),
        TaskAttempt.build(
            learner_goal_id="goal-1",
            daily_task_id="task-2",
            workflow_run_id="run-2",
            execution_session_id="session-2",
            task_type="practice",
            topic_focus="matrices",
            outcome_status="failed",
            score=0.32,
            result_note="Still struggled with matrix multiplication.",
        ),
    ]
    learner_topic_mastery_repository.records = [
        LearnerTopicMastery(
            id="mastery-1",
            learner_goal_id="goal-1",
            topic_key="matrices",
            mastery_score=0.76,
            confidence=0.74,
            evidence_count=3,
            last_attempt_status="completed",
            last_assessed_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
            created_at=datetime(2026, 5, 18, 8, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 19, 8, 0, tzinfo=timezone.utc),
        )
    ]
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        audit_service=AuditService(audit_repository),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
        behavior_memory_repository=behavior_repository,
        behavior_memory_embedding_repository=behavior_embedding_repository,
        evidence_link_repository=evidence_repository,
        task_attempt_repository=task_attempt_repository,
        learner_topic_mastery_repository=learner_topic_mastery_repository,
    )

    materialization_service = LongTermMemoryMaterializationService(service)
    first_events = await service.record_learning_memories(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    await materialization_service.materialize_from_chat_turn(
        session_id="session-1",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=first_events,
        persist_embeddings=True,
    )
    second_events = await service.record_learning_memories(
        session_id="session-2",
        learner_profile_id="profile-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    await materialization_service.materialize_from_chat_turn(
        session_id="session-2",
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-2",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
        memory_events=second_events,
        persist_embeddings=True,
    )

    result = await service.run_memory_maintenance(batch_size=5)

    assert result.compressed_knowledge_groups >= 0
    assert result.compressed_behavior_groups >= 0
    assert result.promoted_knowledge >= 0
    assert result.promoted_behavior >= 0
    assert len(evidence_repository.records) >= 2
    assert any(item.evidence_source_type == "task_attempt" for item in evidence_repository.records.values())
    assert any(item.evidence_source_type == "topic_mastery" for item in evidence_repository.records.values())


async def test_compression_moves_sources_out_of_current_identity_before_activating_aggregate():
    knowledge_repository = StubKnowledgeMemoryRepository()
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    behavior_embedding_repository = StubBehaviorMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
        behavior_memory_repository=behavior_repository,
        behavior_memory_embedding_repository=behavior_embedding_repository,
    )
    base_knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert base_knowledge is not None
    knowledge_one = base_knowledge.with_status("active", evidence_count=2, support_score=0.5)
    knowledge_two = base_knowledge.with_status("stable", evidence_count=3, support_score=0.6)
    knowledge_two = type(knowledge_two)(
        **{
            **knowledge_two.__dict__,
            "id": "knowledge-alt",
            "semantic_category": "misconception",
            "summary": "Learner may confuse matrix multiplication order.",
        }
    )
    knowledge_repository.memories = [knowledge_one, knowledge_two]
    for memory in knowledge_repository.memories:
        knowledge_embedding_repository.records.append(
            KnowledgeMemoryEmbeddingRecord.build(
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                knowledge_key=memory.knowledge_key,
                title=memory.title,
                summary=memory.summary,
                knowledge_level=memory.knowledge_level,
                time_horizon=memory.time_horizon,
                importance_score=memory.importance_score,
                confidence_score=memory.confidence_score,
                freshness_score=memory.freshness_score,
                stability_score=memory.stability_score,
                goal_relevance_score=memory.goal_relevance_score,
                scope_type=memory.scope_type,
                provider="stub",
                model="stub-embedding-v1",
                vector=[1.0, 0.0],
                status=memory.status,
            )
        )

    compressed_knowledge = await service.compress_knowledge_memories(batch_size=5)

    assert compressed_knowledge == 1
    assert "compressed" in knowledge_repository.created_statuses
    assert sum(item.status in {"active", "stable"} for item in knowledge_repository.memories) == 1
    assert sum(item.status == "compressed" for item in knowledge_repository.memories) == 2

    base_behavior = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need help with matrix multiplication.",
        assistant_message="Try a guided row-column example.",
        source_message_id="message-1",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert base_behavior is not None
    behavior_one = base_behavior.with_status("active", evidence_count=2, support_score=0.5)
    behavior_two = base_behavior.with_status("stable", evidence_count=3, support_score=0.6)
    behavior_two = type(behavior_two)(
        **{
            **behavior_two.__dict__,
            "id": "behavior-alt",
            "behavior_category": "guided_progress",
            "summary": "Learner responds to guided row-column examples.",
        }
    )
    behavior_repository.memories = [behavior_one, behavior_two]
    for memory in behavior_repository.memories:
        behavior_embedding_repository.records.append(
            BehaviorMemoryEmbeddingRecord.build(
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                behavior_key=memory.behavior_key,
                behavior_category=memory.behavior_category,
                title=memory.title,
                summary=memory.summary,
                behavior_level=memory.behavior_level,
                time_horizon=memory.time_horizon,
                importance_score=memory.importance_score,
                confidence_score=memory.confidence_score,
                freshness_score=memory.freshness_score,
                stability_score=memory.stability_score,
                goal_relevance_score=memory.goal_relevance_score,
                scope_type=memory.scope_type,
                provider="stub",
                model="stub-embedding-v1",
                vector=[0.8, 0.2],
                status=memory.status,
            )
        )

    compressed_behavior = await service.compress_behavior_memories(batch_size=5)

    assert compressed_behavior == 1
    assert "compressed" in behavior_repository.created_statuses
    assert sum(item.status in {"active", "stable"} for item in behavior_repository.memories) == 1
    assert sum(item.status == "compressed" for item in behavior_repository.memories) == 2


async def test_governance_batches_use_profile_id_cursor_without_offset_skip():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
    )
    knowledge_base = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    behavior_base = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need hints before solving matrix questions.",
        assistant_message="Use row-column matching.",
        source_message_id="message-2",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert knowledge_base is not None and behavior_base is not None
    knowledge_repository.memories = [
        _with_id(knowledge_base.with_status("candidate"), "k-001"),
        _with_id(knowledge_base.with_status("candidate"), "k-002"),
        _with_id(knowledge_base.with_status("candidate"), "k-003"),
    ]
    behavior_repository.memories = [
        _with_id(behavior_base.with_status("candidate"), "b-001"),
        _with_id(behavior_base.with_status("candidate"), "b-002"),
        _with_id(behavior_base.with_status("candidate"), "b-003"),
    ]

    first_knowledge = await service.run_knowledge_governance_batch(
        learner_profile_id="profile-1",
        cursor=None,
        batch_size=2,
    )
    second_knowledge = await service.run_knowledge_governance_batch(
        learner_profile_id="profile-1",
        cursor=first_knowledge.next_cursor,
        batch_size=2,
    )
    first_behavior = await service.run_behavior_governance_batch(
        learner_profile_id="profile-1",
        cursor=None,
        batch_size=2,
    )
    second_behavior = await service.run_behavior_governance_batch(
        learner_profile_id="profile-1",
        cursor=first_behavior.next_cursor,
        batch_size=2,
    )

    assert first_knowledge.processed_count == 2
    assert first_knowledge.next_cursor == "k-002"
    assert first_knowledge.completed is False
    assert second_knowledge.processed_count == 1
    assert second_knowledge.next_cursor == "k-003"
    assert second_knowledge.completed is True
    assert first_behavior.processed_count == 2
    assert first_behavior.next_cursor == "b-002"
    assert first_behavior.completed is False
    assert second_behavior.processed_count == 1
    assert second_behavior.next_cursor == "b-003"
    assert second_behavior.completed is True


async def test_profile_compression_batch_advances_cursor_by_processed_group_id():
    knowledge_repository = StubKnowledgeMemoryRepository()
    knowledge_embedding_repository = StubKnowledgeMemoryEmbeddingRepository()
    service = MemoryService(
        StubMemoryRepository(),
        embedding_provider=StubEmbeddingProvider(),
        knowledge_memory_repository=knowledge_repository,
        knowledge_memory_embedding_repository=knowledge_embedding_repository,
    )
    base = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert base is not None
    memories = [
        _with_id(base.with_status("active", importance_score=0.2), "k-001"),
        _with_id(base.with_status("active", importance_score=0.95), "k-002"),
        _with_id(base.with_status("active", importance_score=0.85), "k-003"),
    ]
    knowledge_repository.memories = memories
    for memory in memories:
        knowledge_embedding_repository.records.append(
            KnowledgeMemoryEmbeddingRecord.build(
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                knowledge_key=memory.knowledge_key,
                title=memory.title,
                summary=memory.summary,
                knowledge_level=memory.knowledge_level,
                time_horizon=memory.time_horizon,
                importance_score=memory.importance_score,
                confidence_score=memory.confidence_score,
                freshness_score=memory.freshness_score,
                stability_score=memory.stability_score,
                goal_relevance_score=memory.goal_relevance_score,
                scope_type=memory.scope_type,
                provider="stub",
                model="stub-embedding-v1",
                vector=[1.0, 0.0],
                status=memory.status,
            )
        )

    result = await service.compress_knowledge_memories_for_profile(
        learner_profile_id="profile-1",
        cursor=None,
        batch_size=1,
    )

    assert result.processed_count == 1
    assert result.changed_count == 1
    assert result.next_cursor == "k-001"
    assert result.completed is True
    assert {item.id for item in knowledge_repository.memories if item.status == "compressed"} == {"k-001", "k-002"}
    assert any(item.id == "k-003" and item.status == "active" for item in knowledge_repository.memories)


async def test_build_reflection_corpus_orders_items_by_governance_priority():
    audit_repository = StubAuditRepository()
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    service = MemoryService(
        StubMemoryRepository(),
        audit_service=AuditService(audit_repository),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
    )

    knowledge_repository.memories = [
        service._build_knowledge_memory(  # noqa: SLF001
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            learner_message="I am confused about matrix multiplication.",
            assistant_message="Matrix multiplication combines rows and columns.",
            source_message_id="message-1",
            mode="chat",
            subject="Matrices",
            session_title="Linear Algebra",
        )
    ]
    behavior_repository.memories = [
        service._build_behavior_memory(  # noqa: SLF001
            learner_profile_id="profile-1",
            learner_goal_id="goal-1",
            learner_message="I need a hint for matrix multiplication.",
            assistant_message="Try the row-column rule first.",
            source_message_id="message-2",
            mode="hint",
            subject="Matrices",
            session_title="Linear Algebra",
        )
    ]

    corpus = await service.build_reflection_corpus(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        limit_per_type=8,
    )

    assert corpus.learner_profile_id == "profile-1"
    assert corpus.summary.total_items == 2
    assert corpus.summary.reinforce_items >= 1
    assert corpus.items[0].reflection_priority_score >= corpus.items[1].reflection_priority_score
    assert corpus.items[0].recommended_action in {"reinforce", "validate", "refresh", "observe", "review"}
    assert 0.0 <= corpus.items[0].quality_score <= 1.0
    assert corpus.items[0].quality_tier in {"low", "medium", "high"}
    assert corpus.items[0].promotion_readiness in {"not_ready", "monitor", "ready"}
    assert isinstance(corpus.items[0].quality_reasons, list)
    assert isinstance(corpus.items[0].evidence_mix, dict)
    assert corpus.items[0].recommended_action_reason in {
        "promotion_candidate",
        "contradiction_pressure",
        "staleness_pressure",
        "archived_high_value",
        "balanced",
    }
    assert corpus.items[0].topic_alignment_score >= 0.0
    assert corpus.items[0].governance_pressure >= 0.0
    assert audit_repository.events[-1].event_type == "memory.reflection_corpus.generated"


async def test_topic_matching_handles_separator_and_token_variants():
    assert MemoryService._topic_matches("matrix multiplication", "matrix-multiplication")
    assert MemoryService._topic_matches("matrix_multiplication", "matrix multiplication")
    assert MemoryService._topic_alignment_score(
        "matrix multiplication",
        "algebra",
        title="Matrix Multiplication Basics",
        tags=["matrices", "linear algebra"],
        extras=None,
    ) >= 0.4


async def test_memory_governance_uses_configured_thresholds():
    service = MemoryService(
        StubMemoryRepository(),
        governance_config={
            **MemoryService._default_governance_config(),
            "candidate_to_active_evidence_min": 3,
        },
    )
    memory = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert memory is not None
    governed = memory.with_status(
        "candidate",
        evidence_count=2,
        support_score=0.5,
        confidence_score=0.8,
        contradiction_score=0.0,
    )
    assert service._govern_knowledge_status(governed) == "candidate"  # noqa: SLF001


async def test_bridge_reflection_outcome_writes_memory_evidence_links():
    knowledge_repository = StubKnowledgeMemoryRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=StubBehaviorMemoryRepository(),
        evidence_link_repository=evidence_repository,
    )
    memory = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrix Multiplication",
        session_title="Linear Algebra",
    )
    assert memory is not None
    await knowledge_repository.create(memory)

    from agent_core.domain.entities.reflection import ReflectionRecord
    from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation

    reflection = ReflectionRecord.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        daily_task_id="task-1",
        workflow_run_id=None,
        study_plan_id=None,
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        duplicate_count=0,
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        priority_score=0.7,
        last_duplicate_at=None,
        cooldown_until=None,
        summary="Learner is confused about matrix multiplication.",
        evidence_summary="Repeated failure on matrix multiplication.",
        recommended_next_step="review prerequisite and retry",
        evidence_payload={"task": {"topic_focus": "matrix-multiplication"}},
        aggregation_key="agg-1",
        dedupe_key="dedupe-1",
    )
    evaluation = ReflectionOutcomeEvaluation.build(
        reflection_record_id=reflection.id,
        learner_goal_id="goal-1",
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    ).with_result(
        evaluation_status="effective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 2},
        improvement_score=0.7,
        evaluation_note="improved",
        evaluated=True,
    )
    updates = await service.bridge_reflection_outcome(reflection=reflection, evaluation=evaluation)
    assert updates == 1
    links = await evidence_repository.list_by_memory(memory_type="knowledge", memory_id=memory.id)
    assert any(item.evidence_source_type == "reflection_outcome" for item in links)


async def test_build_governance_summary_aggregates_memory_statuses():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    decision_repository = StubMemoryGovernanceDecisionRepository()
    evidence_repository = StubMemoryEvidenceLinkRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
        governance_decision_repository=decision_repository,
        evidence_link_repository=evidence_repository,
    )
    knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    behavior = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need a hint for matrix multiplication.",
        assistant_message="Try the row-column rule first.",
        source_message_id="message-2",
        mode="hint",
        subject="Matrices",
        session_title="Linear Algebra",
    )
    assert knowledge is not None and behavior is not None
    await knowledge_repository.create(knowledge.with_status("active", contradiction_score=0.4))
    await behavior_repository.create(
        behavior.with_status("candidate", freshness_score=0.05, goal_relevance_score=0.2, contradiction_score=0.2)
    )

    summary = await service.build_governance_summary(learner_profile_id="profile-1", learner_goal_id="goal-1")

    assert summary.knowledge_total == 1
    assert summary.behavior_total == 1
    assert summary.active_total == 1
    assert summary.candidate_total == 1
    assert summary.contradiction_focus_total == 1
    assert summary.stale_candidate_total == 1
    assert summary.demotion_risk_total >= 1
    assert summary.operator_review_recommended_total >= 1
    assert summary.high_quality_total >= 0
    assert summary.medium_quality_total >= 0
    assert summary.ready_promotion_total >= 0
    assert summary.weak_candidate_total >= 0
    assert set(summary.quality_tier_totals).issuperset({"low", "medium", "high"})
    assert isinstance(summary.topic_bucket_summary, list)


async def test_memory_interpretation_separates_contested_memories_and_constraints():
    knowledge_repository = StubKnowledgeMemoryRepository()
    behavior_repository = StubBehaviorMemoryRepository()
    conflict_repository = StubMemoryConflictRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=behavior_repository,
        conflict_repository=conflict_repository,
    )
    knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrix Multiplication",
        session_title="Linear Algebra",
    )
    behavior = service._build_behavior_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I need hints before solving matrix questions.",
        assistant_message="Use row-column matching.",
        source_message_id="message-2",
        mode="hint",
        subject="Matrix Multiplication",
        session_title="Linear Algebra",
    )
    assert knowledge is not None and behavior is not None
    await knowledge_repository.create(
        knowledge.with_status(
            "active",
            support_score=0.6,
            evidence_count=3,
            validation_status="locally_valid",
        )
    )
    await behavior_repository.create(
        behavior.with_status(
            "candidate",
            contradiction_score=0.5,
            contradiction_count=1,
            validation_status="contested",
        )
    )
    await service.refresh_conflict_sets()

    interpretation = await service.build_interpretation(learner_profile_id="profile-1", learner_goal_id="goal-1")

    assert len(interpretation.facts) == 1
    assert interpretation.facts[0].validation_status == "locally_valid"
    assert len(interpretation.contested_items) == 1
    assert interpretation.contested_items[0].recommended_use == "verify_before_use"
    assert interpretation.conflict_count == 1
    assert any("contested" in item for item in interpretation.recommended_constraints)


async def test_refresh_conflict_sets_closes_resolved_conflict_when_contradiction_drops():
    knowledge_repository = StubKnowledgeMemoryRepository()
    conflict_repository = StubMemoryConflictRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        conflict_repository=conflict_repository,
    )
    knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrix Multiplication",
        session_title="Linear Algebra",
    )
    assert knowledge is not None
    await knowledge_repository.create(knowledge.with_status("active", contradiction_score=0.6, contradiction_count=2))
    await service.refresh_conflict_sets()
    assert len(conflict_repository.sets) == 1
    assert conflict_repository.sets[0].status == "open"
    assert conflict_repository.sets[0].reason_code == "contradiction_score_threshold"
    assert conflict_repository.sets[0].handling_result == "open_review_required"
    assert conflict_repository.sets[0].status_impact.recommended_use == "verify_before_use"
    details = await service.list_conflict_member_details(conflict_set_id=conflict_repository.sets[0].id)
    assert details[0].member_title == knowledge.title
    assert details[0].member_status == "active"

    lowered = knowledge_repository.memories[0].with_status("active", contradiction_score=0.1, contradiction_count=0)
    await knowledge_repository.update(lowered)
    await service.refresh_conflict_sets()

    assert conflict_repository.sets[0].status == "resolved"
    assert "resolved" in conflict_repository.sets[0].summary
    assert conflict_repository.sets[0].handling_result == "resolved_by_evidence_refresh"
    assert conflict_repository.sets[0].status_impact.direct_status_change is False


async def test_refresh_conflict_sets_closes_stale_conflict_when_member_is_no_longer_visible():
    knowledge_repository = StubKnowledgeMemoryRepository()
    conflict_repository = StubMemoryConflictRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        conflict_repository=conflict_repository,
    )
    knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I am confused about matrix multiplication.",
        assistant_message="Definition: Matrix multiplication combines rows and columns.",
        source_message_id="message-1",
        mode="chat",
        subject="Matrix Multiplication",
        session_title="Linear Algebra",
    )
    assert knowledge is not None
    await knowledge_repository.create(knowledge.with_status("active", contradiction_score=0.6, contradiction_count=2))
    await service.refresh_conflict_sets()
    assert len(conflict_repository.sets) == 1
    assert conflict_repository.sets[0].status == "open"
    details = await service.list_conflict_member_details(conflict_set_id=conflict_repository.sets[0].id)
    assert details[0].member_validation_status == "unverified"

    archived = knowledge_repository.memories[0].with_status("archived", contradiction_score=0.6, contradiction_count=2)
    await knowledge_repository.update(archived)
    await service.refresh_conflict_sets()

    assert conflict_repository.sets[0].status == "stale"
    assert "no longer visible" in conflict_repository.sets[0].summary
    assert conflict_repository.sets[0].handling_result == "stale_member_not_visible"


async def test_profile_conflict_refresh_closes_only_requested_profile_sets():
    conflict_repository = StubMemoryConflictRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=StubKnowledgeMemoryRepository(),
        conflict_repository=conflict_repository,
    )
    first_set = MemoryConflictSet.build(
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        topic_key="matrices",
        conflict_type="contradictory_evidence",
        severity_score=0.8,
        summary="Profile 1 conflict.",
        reason_code="test_open_conflict",
        reason_note=None,
        handling_result="open_review_required",
        status_impact=ConflictStatusImpact.build(
            validation_status="contested",
            recommended_use="verify_before_use",
            governance_effect="test",
            direct_status_change=False,
            severity_score=0.8,
        ),
    )
    second_set = MemoryConflictSet.build(
        learner_profile_id="profile-2",
        learner_goal_id="goal-2",
        topic_key="vectors",
        conflict_type="contradictory_evidence",
        severity_score=0.8,
        summary="Profile 2 conflict.",
        reason_code="test_open_conflict",
        reason_note=None,
        handling_result="open_review_required",
        status_impact=ConflictStatusImpact.build(
            validation_status="contested",
            recommended_use="verify_before_use",
            governance_effect="test",
            direct_status_change=False,
            severity_score=0.8,
        ),
    )
    conflict_repository.sets = [
        _with_id(first_set, "conflict-001"),
        _with_id(second_set, "conflict-002"),
    ]
    conflict_repository.members = [
        MemoryConflictMember.build(
            conflict_set_id="conflict-001",
            memory_type="knowledge",
            memory_id="missing-memory-1",
            memory_key="matrices",
            stance="contested",
            support_score=0.0,
            contradiction_score=0.8,
        ),
        MemoryConflictMember.build(
            conflict_set_id="conflict-002",
            memory_type="knowledge",
            memory_id="missing-memory-2",
            memory_key="vectors",
            stance="contested",
            support_score=0.0,
            contradiction_score=0.8,
        ),
    ]

    result = await service.refresh_conflict_sets_for_profile(
        learner_profile_id="profile-1",
        cursor=None,
        batch_size=10,
    )

    statuses_by_id = {item.id: item.status for item in conflict_repository.sets}
    assert result.processed_count == 1
    assert result.changed_count == 1
    assert result.metadata["closed"] == 1
    assert statuses_by_id["conflict-001"] == "stale"
    assert statuses_by_id["conflict-002"] == "open"


def test_long_term_memory_boundary_migration_matches_models():
    repo_root = Path(__file__).resolve().parents[1]
    models = (repo_root / "packages/agent_core/src/agent_core/infrastructure/db/models.py").read_text()
    migration = (repo_root / "alembic/versions/0013_long_term_memory_materialization_boundaries.py").read_text()
    consistency_migration = (
        repo_root / "alembic/versions/0014_long_term_memory_consistency_constraints.py"
    ).read_text()
    conflict_explainability_migration = (
        repo_root / "alembic/versions/0016_memory_conflict_explainability.py"
    ).read_text()

    assert 'down_revision = "0012_learner_profile_access_key"' in migration
    assert 'down_revision = "0013_long_term_memory_materialization_boundaries"' in consistency_migration
    assert 'down_revision = "0015_memory_maintenance_jobs"' in conflict_explainability_migration
    for table_name in ("knowledge_memories", "behavior_memories"):
        assert f'"{table_name}"' in migration
    for field_name in (
        "semantic_category",
        "validation_status",
        "provenance_type",
        "provenance_source_id",
        "scope_ref",
        "promotion_rationale",
    ):
        assert field_name in models
        assert field_name in migration
    for status in ("candidate", "active", "stable", "suppressed"):
        assert status in models
        assert status in consistency_migration
    for table_name in ("memory_conflict_sets", "memory_conflict_members"):
        assert table_name in models
        assert table_name in migration
    for index_name in (
        "ix_memory_conflict_sets_profile_status_topic",
        "ix_memory_conflict_sets_profile_goal_status",
        "ix_memory_conflict_members_set",
        "ix_memory_conflict_members_memory",
    ):
        assert index_name in migration
    for index_name in (
        "uq_knowledge_memories_current_identity",
        "uq_behavior_memories_current_identity",
        "uq_memory_evidence_links_identity",
        "uq_memory_conflict_sets_open_identity",
    ):
        assert index_name in models
        assert index_name in consistency_migration
    for duplicate_label in (
        "knowledge memory current identity",
        "behavior memory current identity",
        "memory evidence link identity",
        "open memory conflict set identity",
    ):
        assert duplicate_label in consistency_migration
    assert "COALESCE(learner_goal_id, '')" in consistency_migration
    assert "HAVING COUNT(*) > 1" in consistency_migration
    assert "RuntimeError" in consistency_migration
    for field_name in (
        "reason_code",
        "reason_note",
        "handling_result",
        "status_impact",
    ):
        assert field_name in models
        assert field_name in conflict_explainability_migration
    for removed_snapshot_field in (
        "member_title",
        "member_summary",
        "member_status",
        "member_validation_status",
    ):
        assert removed_snapshot_field not in models
        assert removed_snapshot_field not in conflict_explainability_migration


def test_memory_observability_assets_reference_expected_metrics():
    repo_root = Path(__file__).resolve().parents[1]
    dashboard = (repo_root / "ops/grafana/dashboards/agent-edu-overview.json").read_text()
    alerts = (repo_root / "ops/prometheus/alerts.yml").read_text()
    prometheus = (repo_root / "ops/prometheus/prometheus.yml").read_text()
    compose = (repo_root / "compose.yaml").read_text()

    for metric_name in (
        "agent_edu_memory_candidate_backlog",
        "agent_edu_memory_governance_decisions_total",
        "agent_edu_memory_conflict_events_total",
        "agent_edu_long_term_memory_materialization_total",
        "agent_edu_memory_maintenance_job_duration_seconds",
    ):
        assert metric_name in dashboard
    for metric_name in (
        "agent_edu_memory_candidate_backlog",
        "agent_edu_memory_conflict_events_total",
        "agent_edu_long_term_memory_materialization_total",
        "agent_edu_memory_maintenance_job_duration_seconds",
    ):
        assert metric_name in alerts
    assert "alerts.yml" in prometheus
    assert "ops/prometheus/alerts.yml" in compose


async def test_reflection_corpus_exposes_semantics_and_contested_state():
    knowledge_repository = StubKnowledgeMemoryRepository()
    service = MemoryService(
        StubMemoryRepository(),
        knowledge_memory_repository=knowledge_repository,
        behavior_memory_repository=StubBehaviorMemoryRepository(),
    )
    knowledge = service._build_knowledge_memory(  # noqa: SLF001
        learner_profile_id="profile-1",
        learner_goal_id="goal-1",
        learner_message="I keep mixing determinant and inverse.",
        assistant_message="Check determinant meaning before inverse procedures.",
        source_message_id="message-1",
        mode="chat",
        subject="Determinants",
        session_title="Linear Algebra",
    )
    assert knowledge is not None
    await knowledge_repository.create(
        knowledge.with_status(
            "candidate",
            contradiction_score=0.6,
            contradiction_count=2,
            validation_status="contested",
        )
    )

    corpus = await service.build_reflection_corpus(learner_profile_id="profile-1", learner_goal_id="goal-1")

    assert corpus.items
    assert corpus.items[0].semantic_category in {"concept", "prerequisite"}
    assert corpus.items[0].validation_status == "contested"
    assert corpus.items[0].contested is True
