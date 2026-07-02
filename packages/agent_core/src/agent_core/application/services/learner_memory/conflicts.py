"""Conflict set construction, refresh, and close logic."""

from __future__ import annotations

from agent_core.application.services.memory_conflict_policy import (
    CONFLICT_CONTRADICTION_THRESHOLD,
    MemoryConflictPolicy,
)
from agent_core.application.services.learner_memory.quality import clamp_score
from agent_core.application.services.learner_memory.result_types import (
    MemoryConflictMemberDetail,
    MemoryMaintenanceBatchResult,
)
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryConflictMember,
    MemoryConflictSet,
)
from agent_core.infrastructure.db.repositories import (
    BehaviorMemoryRepository,
    KnowledgeMemoryRepository,
    MemoryConflictRepository,
)
from agent_core.infrastructure.observability.metrics import (
    observe_memory_conflict_event,
)


class ConflictService:
    """Maintains open/closed conflict sets and builds operator-visible conflict detail."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        conflict_repository: MemoryConflictRepository | None = None,
        refresh_observability_metrics: object = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._conflict_repository = conflict_repository
        self._refresh_observability_metrics = refresh_observability_metrics

    async def refresh_conflict_sets_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if self._conflict_repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        memory_by_ref, active_conflict_keys, written = await self._upsert_profile_conflict_sets(
            learner_profile_id=learner_profile_id
        )
        if hasattr(self._conflict_repository, "list_open_sets_by_profile_after_id"):
            fetched_sets = await self._conflict_repository.list_open_sets_by_profile_after_id(
                learner_profile_id=learner_profile_id,
                after_id=cursor,
                limit=max(batch_size, 1) + 1,
            )
        else:
            open_sets = await self._conflict_repository.list_sets_by_profile(
                learner_profile_id=learner_profile_id,
                status="open",
                limit=10000,
            )
            fetched_sets = [
                item
                for item in sorted(open_sets, key=lambda item: item.id)
                if cursor is None or item.id > cursor
            ][: max(batch_size, 1) + 1]
        batch = fetched_sets[: max(batch_size, 1)]
        closed = await self._close_inactive_conflict_sets(
            active_conflict_keys=active_conflict_keys,
            visible_memories=memory_by_ref,
            conflict_sets=batch,
        )
        if self._refresh_observability_metrics is not None:
            await self._refresh_observability_metrics()
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=written + closed,
            next_cursor=next_cursor,
            completed=len(fetched_sets) <= max(batch_size, 1),
            metadata={"written": written, "closed": closed},
        )

    async def refresh_conflict_sets(self) -> int:
        if self._conflict_repository is None:
            return 0
        profile_ids: set[str] = set()
        if self._knowledge_memory_repository is not None:
            profile_ids.update(
                await self._knowledge_memory_repository.list_profile_ids_with_statuses(
                    {"candidate", "active", "stable"}
                )
            )
        if self._behavior_memory_repository is not None:
            profile_ids.update(
                await self._behavior_memory_repository.list_profile_ids_with_statuses(
                    {"candidate", "active", "stable"}
                )
            )
        if hasattr(self._conflict_repository, "list_profile_ids_with_open_sets"):
            profile_ids.update(await self._conflict_repository.list_profile_ids_with_open_sets())
        else:
            profile_ids.update(item.learner_profile_id for item in await self._conflict_repository.list_open_sets())
        written = 0
        for learner_profile_id in sorted(profile_ids):
            memory_by_ref, active_conflict_keys, profile_written = await self._upsert_profile_conflict_sets(
                learner_profile_id=learner_profile_id
            )
            if hasattr(self._conflict_repository, "list_sets_by_profile"):
                conflict_sets = await self._conflict_repository.list_sets_by_profile(
                    learner_profile_id=learner_profile_id,
                    status="open",
                    limit=10000,
                )
            else:
                conflict_sets = [
                    item
                    for item in await self._conflict_repository.list_open_sets()
                    if item.learner_profile_id == learner_profile_id
                ]
            await self._close_inactive_conflict_sets(
                active_conflict_keys=active_conflict_keys,
                visible_memories=memory_by_ref,
                conflict_sets=conflict_sets,
            )
            written += profile_written
        if self._refresh_observability_metrics is not None:
            await self._refresh_observability_metrics()
        return written

    async def _upsert_profile_conflict_sets(
        self,
        *,
        learner_profile_id: str,
    ) -> tuple[dict[tuple[str, str], KnowledgeMemory | BehaviorMemory], set[tuple[str, str | None, str, str]], int]:
        memories: list[KnowledgeMemory | BehaviorMemory] = []
        if self._knowledge_memory_repository is not None:
            memories.extend(
                await self._knowledge_memory_repository.list_by_profile(
                    learner_profile_id,
                    statuses={"candidate", "active", "stable"},
                )
            )
        if self._behavior_memory_repository is not None:
            memories.extend(
                await self._behavior_memory_repository.list_by_profile(
                    learner_profile_id,
                    statuses={"candidate", "active", "stable"},
                )
            )
        memory_by_ref: dict[tuple[str, str], KnowledgeMemory | BehaviorMemory] = {
            ("knowledge" if isinstance(memory, KnowledgeMemory) else "behavior", memory.id): memory
            for memory in memories
        }
        grouped: dict[tuple[str, str | None, str], list[KnowledgeMemory | BehaviorMemory]] = {}
        for memory in memories:
            if memory.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD:
                continue
            topic_key = getattr(memory, "knowledge_key", "") or getattr(memory, "behavior_key", "")
            grouped.setdefault((memory.learner_profile_id, memory.learner_goal_id, topic_key), []).append(memory)
        active_conflict_keys = {
            (learner_profile_id, learner_goal_id, topic_key, "contradictory_evidence")
            for learner_profile_id, learner_goal_id, topic_key in grouped
        }
        written = 0
        for (learner_profile_id, learner_goal_id, topic_key), items in grouped.items():
            severity = clamp_score(max(item.contradiction_score for item in items))
            decision = MemoryConflictPolicy.open_contradictory_evidence(
                topic_key=topic_key,
                current_memory_count=len(items),
                severity_score=severity,
            )
            conflict_set = MemoryConflictSet.build(
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                topic_key=topic_key,
                conflict_type="contradictory_evidence",
                severity_score=severity,
                summary=f"Contradictory memory evidence for topic '{topic_key}'.",
                reason_code=decision.reason_code,
                reason_note=decision.reason_note,
                handling_result=decision.handling_result,
                status_impact=decision.status_impact,
            )
            members = [
                MemoryConflictMember.build(
                    conflict_set_id=conflict_set.id,
                    memory_type="knowledge" if isinstance(item, KnowledgeMemory) else "behavior",
                    memory_id=item.id,
                    memory_key=getattr(item, "knowledge_key", "") or getattr(item, "behavior_key", ""),
                    stance="contested",
                    support_score=item.support_score,
                    contradiction_score=item.contradiction_score,
                )
                for item in items
            ]
            _, created = await self._conflict_repository.upsert_set(conflict_set=conflict_set, members=members)
            observe_memory_conflict_event(
                conflict_type=conflict_set.conflict_type,
                event="created" if created else "refreshed",
                status=conflict_set.status,
            )
            written += 1
        return memory_by_ref, active_conflict_keys, written

    async def _close_inactive_conflict_sets(
        self,
        *,
        active_conflict_keys: set[tuple[str, str | None, str, str]],
        visible_memories: dict[tuple[str, str], KnowledgeMemory | BehaviorMemory],
        conflict_sets: list[MemoryConflictSet] | None = None,
    ) -> int:
        if self._conflict_repository is None:
            return 0
        closed_count = 0
        open_sets = conflict_sets if conflict_sets is not None else await self._conflict_repository.list_open_sets()
        for conflict_set in open_sets:
            conflict_key = (
                conflict_set.learner_profile_id,
                conflict_set.learner_goal_id,
                conflict_set.topic_key,
                conflict_set.conflict_type,
            )
            if conflict_key in active_conflict_keys:
                continue
            members = [
                item
                for item in await self._conflict_repository.list_members(conflict_set_id=conflict_set.id)
                if item.stance != "superseded"
            ]
            if not members:
                decision = MemoryConflictPolicy.close_no_current_members()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' became stale because it has no current members.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
                continue
            member_memories = [
                visible_memories.get((member.memory_type, member.memory_id))
                for member in members
            ]
            if any(memory is None for memory in member_memories):
                decision = MemoryConflictPolicy.close_member_not_visible()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=(
                        f"Conflict for topic '{conflict_set.topic_key}' became stale because one or more "
                        "member memories are no longer visible."
                    ),
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
                continue
            if all(
                memory is not None and memory.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
                for memory in member_memories
            ):
                decision = MemoryConflictPolicy.close_resolved_by_refresh()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="resolved",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' resolved after contradiction fell below threshold.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="resolved",
                )
                closed_count += 1
            else:
                decision = MemoryConflictPolicy.close_inactive_refresh()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' became stale after refresh.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
        return closed_count

    @staticmethod
    def conflict_member_detail(
        *,
        member: MemoryConflictMember,
        memory: KnowledgeMemory | BehaviorMemory | None,
    ) -> MemoryConflictMemberDetail:
        return MemoryConflictMemberDetail(
            id=member.id,
            conflict_set_id=member.conflict_set_id,
            memory_type=member.memory_type,
            memory_id=member.memory_id,
            memory_key=member.memory_key,
            stance=member.stance,
            support_score=member.support_score,
            contradiction_score=member.contradiction_score,
            member_title=memory.title if memory is not None else None,
            member_summary=memory.summary if memory is not None else None,
            member_status=memory.status if memory is not None else None,
            member_validation_status=memory.validation_status if memory is not None else None,
            created_at=member.created_at,
        )
