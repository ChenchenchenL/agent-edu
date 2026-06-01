from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectiveMemory
from agent_core.infrastructure.db.repositories import ReflectiveMemoryRepository


class ReflectiveMemoryService:
    def __init__(
        self,
        *,
        repository: ReflectiveMemoryRepository,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._audit_service = audit_service

    async def list_by_goal(self, learner_goal_id: str) -> list[ReflectiveMemory]:
        return await self._repository.list_by_goal(learner_goal_id)

    async def create_candidate(
        self,
        *,
        reflection: ReflectionRecord,
        actions: list[ReflectionAction],
    ) -> ReflectiveMemory:
        topic_key = str((reflection.evidence_payload.get("task") or {}).get("topic_focus") or "general")
        memory = ReflectiveMemory.build(
            learner_profile_id=reflection.learner_profile_id,
            learner_goal_id=reflection.learner_goal_id,
            reflection_record_id=reflection.id,
            memory_key=f"goal:{reflection.learner_goal_id}:strategy:{reflection.primary_root_cause}:{topic_key}",
            title=f"Reflective insight for {topic_key}",
            summary=reflection.summary,
            details=reflection.evidence_summary,
            memory_level="pattern",
            importance_score=max(0.4, reflection.priority_score),
            confidence_score=reflection.confidence_score,
            freshness_score=1.0,
            evidence_count=max(1, reflection.duplicate_count + 1),
            source_reflection_ids=[reflection.id],
            source_action_ids=[item.id for item in actions],
            tags=[reflection.primary_root_cause, topic_key],
        )
        await self._repository.create(memory)
        await self._audit_service.record(
            event_type="reflective_memory.candidate.created",
            resource_type="reflective_memory",
            resource_id=memory.id,
            actor="system",
            event_data={"reflection_record_id": reflection.id, "learner_goal_id": reflection.learner_goal_id},
        )
        return memory

    async def promote_or_refresh_candidate(
        self,
        *,
        reflection: ReflectionRecord,
        actions: list[ReflectionAction],
        effective: bool,
    ) -> ReflectiveMemory:
        topic_key = str((reflection.evidence_payload.get("task") or {}).get("topic_focus") or "general")
        memory_key = f"goal:{reflection.learner_goal_id}:strategy:{reflection.primary_root_cause}:{topic_key}"
        existing = next(
            (item for item in await self._repository.list_by_goal(reflection.learner_goal_id) if item.memory_key == memory_key),
            None,
        )
        if existing is None:
            return await self.create_candidate(reflection=reflection, actions=actions)
        next_status = existing.status
        next_evidence_count = existing.evidence_count + 1
        next_importance = min(1.0, existing.importance_score + (0.12 if effective else -0.05))
        next_confidence = min(1.0, max(0.0, existing.confidence_score + (0.08 if effective else -0.04)))
        if effective and next_evidence_count >= 2:
            next_status = "active"
        elif not effective and existing.status == "active":
            next_status = "archived"
        updated = existing.with_status(
            next_status,
            importance_score=next_importance,
            confidence_score=next_confidence,
            freshness_score=1.0 if effective else max(0.2, existing.freshness_score - 0.15),
            evidence_count=next_evidence_count,
        )
        await self._repository.update(updated)
        await self._audit_service.record(
            event_type="reflective_memory.updated",
            resource_type="reflective_memory",
            resource_id=updated.id,
            actor="system",
            event_data={
                "reflection_record_id": reflection.id,
                "effective": effective,
                "status": updated.status,
                "evidence_count": updated.evidence_count,
            },
        )
        return updated
