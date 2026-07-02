"""Governance lifecycle transitions, operator actions, and audit recording."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.domain.entities.memory import (
    BehaviorMemoryStatusUpdate,
    KnowledgeMemoryStatusUpdate,
)
from agent_core.application.services.audit import AuditService
from agent_core.application.services.learner_memory.constants import (
    default_governance_config,
)
from agent_core.application.services.memory_conflict_policy import CONFLICT_CONTRADICTION_THRESHOLD
from agent_core.application.services.learner_memory.quality import (
    behavior_promotion_readiness,
    behavior_quality_score,
    clamp_score,
    memory_quality_snapshot_sync,
)
from agent_core.application.services.learner_memory.upsert import UpsertService
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryAnnotation,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
    MemoryPromotionEligibilityRecord,
)
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    BehaviorMemoryRepository,
    KnowledgeMemoryRepository,
    MemoryAnnotationRepository,
    MemoryEvidenceLinkRepository,
    MemoryGovernanceDecisionRepository,
    MemoryPromotionEligibilityRepository,
)


class GovernanceService:
    """Handles governed lifecycle transitions, operator actions, and audit."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        governance_decision_repository: MemoryGovernanceDecisionRepository | None = None,
        promotion_eligibility_repository: MemoryPromotionEligibilityRepository | None = None,
        annotation_repository: MemoryAnnotationRepository | None = None,
        evidence_link_repository: MemoryEvidenceLinkRepository | None = None,
        audit_service: AuditService | None = None,
        upsert_service: UpsertService | None = None,
        governance_config: dict[str, float | int] | None = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._governance_decision_repository = governance_decision_repository
        self._promotion_eligibility_repository = promotion_eligibility_repository
        self._annotation_repository = annotation_repository
        self._evidence_link_repository = evidence_link_repository
        self._audit_service = audit_service
        self._upsert_service = upsert_service
        self._governance_config = governance_config or {}

    async def get_memory(self, memory_type: str, memory_id: str) -> KnowledgeMemory | BehaviorMemory:
        if memory_type == "knowledge":
            if self._knowledge_memory_repository is None:
                raise NotFoundError(f"knowledge memory {memory_id} not found")
            memory = await self._knowledge_memory_repository.get_by_id(memory_id)
            if memory is None:
                raise NotFoundError(f"knowledge memory {memory_id} not found")
            return memory
        if memory_type == "behavior":
            if self._behavior_memory_repository is None:
                raise NotFoundError(f"behavior memory {memory_id} not found")
            memory = await self._behavior_memory_repository.get_by_id(memory_id)
            if memory is None:
                raise NotFoundError(f"behavior memory {memory_id} not found")
            return memory
        raise ValidationError("memory_type must be knowledge or behavior.")

    async def suppress_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        reason_code: str,
        note: str | None,
        actor_id: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        return await self.apply_operator_status_change(
            memory_type=memory_type,
            memory_id=memory_id,
            new_status="suppressed",
            reason_code=reason_code,
            reason_note=note,
            actor_id=actor_id,
            decision_type="suppress",
        )

    async def restore_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        restore_to_status: str,
        reason: str | None,
        actor_id: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        if restore_to_status not in {"candidate", "active"}:
            raise ValidationError("restore_to_status must be candidate or active.")
        return await self.apply_operator_status_change(
            memory_type=memory_type,
            memory_id=memory_id,
            new_status=restore_to_status,
            reason_code="operator_restore",
            reason_note=reason,
            actor_id=actor_id,
            decision_type="restore",
        )

    async def annotate_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        annotation_code: str,
        note: str,
        actor_id: str,
    ) -> MemoryAnnotation:
        if self._annotation_repository is None:
            raise ValidationError("annotation repository is not configured")
        annotation = MemoryAnnotation.build(
            memory_type=memory_type,
            memory_id=memory_id,
            annotation_code=annotation_code,
            note=note,
            created_by=actor_id,
        )
        await self._annotation_repository.create(annotation)
        if self._evidence_link_repository is not None:
            memory = await self.get_memory(memory_type, memory_id)
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type=memory_type,
                    memory_id=memory_id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="operator_annotation",
                    evidence_source_id=annotation.id,
                    evidence_role=MemoryNormalizer.classify_evidence_role(
                        memory_type=memory_type,
                        evidence_source_type="operator_annotation",
                    ),
                    signal_type=annotation_code,
                    weight=0.1,
                    payload={"annotation_code": annotation_code},
                    observed_at=annotation.created_at,
                )
            )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type=f"{memory_type}_memory.annotated",
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor=actor_id,
                event_data={
                    "memory_id": memory_id,
                    "annotation_id": annotation.id,
                    "annotation_code": annotation.annotation_code,
                    "created_by": actor_id,
                },
            )
        return annotation

    async def apply_operator_status_change(
        self,
        *,
        memory_type: str,
        memory_id: str,
        new_status: str,
        reason_code: str,
        reason_note: str | None,
        actor_id: str,
        decision_type: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        memory = await self.get_memory(memory_type, memory_id)
        previous_status = memory.status
        if memory_type == "knowledge":
            updated = memory.with_status(
                new_status,
                update=KnowledgeMemoryStatusUpdate(
                    suppressed_reason_code=reason_code if new_status == "suppressed" else None,
                    suppressed_reason_note=reason_note if new_status == "suppressed" else None,
                    suppressed_by=actor_id if new_status == "suppressed" else None,
                    suppressed_at=datetime.now(timezone.utc) if new_status == "suppressed" else None,
                    promotion_state_changed_at=datetime.now(timezone.utc),
                ),
            )
            if self._knowledge_memory_repository is not None:
                await self._knowledge_memory_repository.update(updated)
            if self._upsert_service is not None:
                await self._upsert_service.sync_knowledge_embedding(updated)
        else:
            updated = memory.with_status(
                new_status,
                update=BehaviorMemoryStatusUpdate(
                    suppressed_reason_code=reason_code if new_status == "suppressed" else None,
                    suppressed_reason_note=reason_note if new_status == "suppressed" else None,
                    suppressed_by=actor_id if new_status == "suppressed" else None,
                    suppressed_at=datetime.now(timezone.utc) if new_status == "suppressed" else None,
                    promotion_state_changed_at=datetime.now(timezone.utc),
                ),
            )
            if self._behavior_memory_repository is not None:
                await self._behavior_memory_repository.update(updated)
            if self._upsert_service is not None:
                await self._upsert_service.sync_behavior_embedding(updated)
        await self.record_governance_decision(
            memory_type=memory_type,
            memory_id=memory_id,
            previous_status=previous_status,
            new_status=new_status,
            decision_type=decision_type,
            trigger_source="operator_api",
            actor_type="operator",
            actor_id=actor_id,
            reason_code=reason_code,
            reason_note=reason_note,
            metrics_snapshot=metrics_snapshot(memory=updated),
        )
        if self._audit_service is not None:
            suffix = "d" if decision_type in {"suppress", "restore"} else ""
            await self._audit_service.record(
                event_type=f"{memory_type}_memory.{decision_type}{suffix}",
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor=actor_id,
                event_data={
                    "memory_id": memory_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "reason_code": reason_code,
                    "reason_note": reason_note,
                    "actor_id": actor_id,
                },
            )
        return updated

    async def govern_knowledge_status(
        self,
        memory: KnowledgeMemory,
        *,
        eligibility: MemoryPromotionEligibilityRecord | None = None,
        eligibility_prefetched: bool = False,
    ) -> str:
        if memory.status == "suppressed":
            return "suppressed"
        if memory.status == "candidate":
            current_eligibility = eligibility
            if current_eligibility is None and not eligibility_prefetched:
                current_eligibility = await self.current_knowledge_eligibility(memory.id)
            if current_eligibility is None:
                return "candidate"
            if current_eligibility.status == "eligible":
                return "active"
            if current_eligibility.status == "conflict_blocked":
                return "suppressed"
            return "candidate"
        if memory.status == "active":
            if (
                memory.evidence_count >= int(self._governance_config.get("active_to_stable_evidence_min", 3))
                and memory.assessment_evidence_count >= int(self._governance_config.get("active_to_stable_assessment_min", 1))
                and memory.stability_score >= float(self._governance_config.get("active_to_stable_stability_min", 0.6))
                and memory.contradiction_score < float(self._governance_config.get("candidate_to_active_contradiction_max", 0.35))
            ):
                return "stable"
            if (
                memory.freshness_score < float(self._governance_config.get("archive_freshness_max", 0.2))
                and memory.goal_relevance_score < float(self._governance_config.get("archive_goal_relevance_max", 0.25))
            ):
                return "archived"
            return "active"
        if memory.status == "stable":
            if (
                memory.contradiction_score >= float(self._governance_config.get("stable_demote_contradiction_min", 0.45))
                or memory.freshness_score < float(self._governance_config.get("stable_demote_freshness_max", 0.2))
            ):
                return "active"
            if (
                memory.freshness_score < float(self._governance_config.get("archive_freshness_max", 0.2))
                and memory.goal_relevance_score < float(self._governance_config.get("archive_goal_relevance_max", 0.25))
            ):
                return "archived"
            return "stable"
        return memory.status

    def govern_behavior_status(self, memory: BehaviorMemory) -> str:
        if memory.status == "suppressed":
            return "suppressed"
        if memory.status == "candidate":
            readiness = behavior_promotion_readiness(memory, behavior_quality_score(memory), self._governance_config)
            if readiness == "ready":
                return "active"
            return "candidate"
        if memory.status == "active":
            if (
                memory.evidence_count >= int(self._governance_config.get("active_to_stable_evidence_min", 3))
                and memory.cross_session_recurrence_count >= int(self._governance_config.get("behavior_active_recurrence_min", 2))
                and memory.stability_score >= float(self._governance_config.get("behavior_active_to_stable_stability_min", 0.55))
            ):
                return "stable"
            if (
                memory.freshness_score < float(self._governance_config.get("archive_freshness_max", 0.2))
                and memory.goal_relevance_score < float(self._governance_config.get("archive_goal_relevance_max", 0.25))
            ):
                return "archived"
            return "active"
        if memory.status == "stable":
            if (
                memory.contradiction_score >= float(self._governance_config.get("stable_demote_contradiction_min", 0.45))
                or memory.freshness_score < float(self._governance_config.get("stable_demote_freshness_max", 0.2))
            ):
                return "active"
            if (
                memory.freshness_score < float(self._governance_config.get("archive_freshness_max", 0.2))
                and memory.goal_relevance_score < float(self._governance_config.get("archive_goal_relevance_max", 0.25))
            ):
                return "archived"
            return "stable"
        return memory.status

    async def apply_knowledge_status_transition(
        self,
        *,
        original: KnowledgeMemory,
        refreshed: KnowledgeMemory,
        next_status: str,
        eligibility: MemoryPromotionEligibilityRecord | None = None,
        eligibility_prefetched: bool = False,
    ) -> KnowledgeMemory:
        now = datetime.now(timezone.utc)
        current_eligibility = eligibility
        if current_eligibility is None and original.status == "candidate" and not eligibility_prefetched:
            current_eligibility = await self.current_knowledge_eligibility(refreshed.id)
        promotion_rationale = knowledge_transition_rationale(
            previous_status=original.status,
            next_status=next_status,
            eligibility=current_eligibility,
            memory=refreshed,
        )
        decision_type = knowledge_transition_decision_type(
            previous_status=original.status,
            next_status=next_status,
        )
        trigger_source = knowledge_transition_trigger_source(
            previous_status=original.status,
            next_status=next_status,
        )
        reason_code = knowledge_transition_reason_code(
            previous_status=original.status,
            next_status=next_status,
            eligibility=current_eligibility,
        )
        reason_note = knowledge_transition_reason_note(
            previous_status=original.status,
            next_status=next_status,
            eligibility=current_eligibility,
        )
        updated = refreshed.with_status(
            next_status,
            update=KnowledgeMemoryStatusUpdate(
                promotion_state_changed_at=now,
                promotion_rationale=promotion_rationale,
                suppressed_reason_code=None if next_status != "suppressed" else reason_code,
                suppressed_reason_note=None if next_status != "suppressed" else reason_note,
                suppressed_by=None if next_status != "suppressed" else "worker",
                suppressed_at=None if next_status != "suppressed" else now,
            ),
        )
        if self._knowledge_memory_repository is not None:
            await self._knowledge_memory_repository.update(updated)
        if self._upsert_service is not None:
            await self._upsert_service.sync_knowledge_embedding(
                updated,
                create_missing=original.status == "candidate" and updated.status == "active",
            )
        await self.record_governance_decision(
            memory_type="knowledge",
            memory_id=updated.id,
            previous_status=original.status,
            new_status=updated.status,
            decision_type=decision_type,
            trigger_source=trigger_source,
            actor_type="system",
            actor_id="worker",
            reason_code=reason_code,
            reason_note=reason_note,
            metrics_snapshot=knowledge_transition_metrics_snapshot(updated=updated, eligibility=current_eligibility),
        )
        return updated

    async def current_knowledge_eligibility(self, memory_id: str) -> MemoryPromotionEligibilityRecord | None:
        if self._promotion_eligibility_repository is None:
            return None
        return await self._promotion_eligibility_repository.get_current(memory_id=memory_id)

    async def record_governance_decision(
        self,
        *,
        memory_type: str,
        memory_id: str,
        previous_status: str | None,
        new_status: str,
        decision_type: str,
        trigger_source: str,
        actor_type: str,
        actor_id: str,
        reason_code: str,
        reason_note: str | None,
        metrics_snapshot: dict[str, float | int | str | None],
    ) -> None:
        if self._governance_decision_repository is not None:
            await self._governance_decision_repository.create(
                MemoryGovernanceDecision.build(
                    memory_type=memory_type,
                    memory_id=memory_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    decision_type=decision_type,
                    trigger_source=trigger_source,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=reason_code,
                    reason_note=reason_note,
                    metrics_snapshot=metrics_snapshot,
                )
            )
        if self._audit_service is not None:
            if decision_type == "suppress":
                event_type = f"{memory_type}_memory.suppressed"
            elif decision_type in {"promote", "demote", "archive", "restore"}:
                event_type = f"{memory_type}_memory.{decision_type}d"
            else:
                event_type = f"{memory_type}_memory.{decision_type}ed"
            await self._audit_service.record(
                event_type=event_type,
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor=actor_type,
                event_data={
                    "memory_id": memory_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "decision_type": decision_type,
                    "trigger_source": trigger_source,
                    "reason_code": reason_code,
                    "reason_note": reason_note,
                    "actor_id": actor_id,
                    "metrics_snapshot": metrics_snapshot,
                },
            )


def decision_type_for_transition(previous_status: str, new_status: str) -> str:
    if previous_status in {"candidate", "active"} and new_status in {"active", "stable"}:
        return "promote"
    if previous_status == "stable" and new_status == "active":
        return "demote"
    if new_status == "archived":
        return "archive"
    return "refresh"


def promotion_rationale(*, updated_status: str, memory: KnowledgeMemory | BehaviorMemory) -> str:
    return (
        f"status={updated_status}; evidence={memory.evidence_count}; "
        f"support={memory.support_score:.2f}; contradiction={memory.contradiction_score:.2f}; "
        f"confidence={memory.confidence_score:.2f}; stability={memory.stability_score:.2f}"
    )


def validation_status_for_memory(
    *,
    contradiction_score: float,
    freshness_score: float,
    evidence_count: int,
    support_score: float,
    scope_type: str,
) -> str:
    if contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        return "contested"
    if freshness_score < 0.3:
        return "stale"
    if evidence_count >= 3 and support_score >= 0.45:
        return "locally_valid" if scope_type == "goal_scoped" else "validated"
    return "unverified"


def knowledge_transition_rationale(
    *,
    previous_status: str,
    next_status: str,
    eligibility: MemoryPromotionEligibilityRecord | None,
    memory: KnowledgeMemory,
) -> str:
    if previous_status == "candidate" and next_status == "active":
        return "Promoted from candidate after governed eligibility evaluation."
    if previous_status == "candidate" and next_status == "suppressed":
        return "Suppressed from candidate because governed eligibility evaluation found an active/stable conflict."
    return promotion_rationale(updated_status=next_status, memory=memory)


def knowledge_transition_decision_type(*, previous_status: str, next_status: str) -> str:
    if next_status == "suppressed":
        return "suppress"
    return decision_type_for_transition(previous_status, next_status)


def knowledge_transition_trigger_source(*, previous_status: str, next_status: str) -> str:
    if previous_status == "candidate" and next_status in {"active", "suppressed"}:
        return "promotion_cycle"
    if next_status == "archived":
        return "decay_cycle"
    if previous_status == "stable" and next_status == "active":
        return "decay_cycle"
    return "promotion_cycle" if next_status == "stable" else "decay_cycle"


def knowledge_transition_reason_code(
    *,
    previous_status: str,
    next_status: str,
    eligibility: MemoryPromotionEligibilityRecord | None,
) -> str:
    if previous_status == "candidate" and next_status == "active":
        return "promotion_eligibility_approved"
    if previous_status == "candidate" and next_status == "suppressed":
        return "promotion_conflict_blocked"
    return "knowledge_governance_cycle"


def knowledge_transition_reason_note(
    *,
    previous_status: str,
    next_status: str,
    eligibility: MemoryPromotionEligibilityRecord | None,
) -> str | None:
    if previous_status != "candidate" or eligibility is None:
        return None
    parts = [f"eligibility_status={eligibility.status}"]
    if eligibility.blocked_memory_id is not None:
        parts.append(f"blocked_memory_id={eligibility.blocked_memory_id}")
    if eligibility.reason_codes:
        parts.append(f"reason_codes={','.join(eligibility.reason_codes)}")
    if next_status != "suppressed" and eligibility.score is not None:
        parts.append(f"eligibility_score={eligibility.score:.2f}")
    return "; ".join(parts)


def knowledge_transition_metrics_snapshot(
    *,
    updated: KnowledgeMemory,
    eligibility: MemoryPromotionEligibilityRecord | None,
) -> dict[str, float | int | str | None]:
    snapshot = metrics_snapshot(memory=updated)
    if eligibility is not None:
        snapshot.update(
            {
                "eligibility_status": eligibility.status,
                "eligibility_score": eligibility.score,
                "eligibility_independent_source_count": eligibility.independent_source_count,
                "eligibility_high_signal_source_count": eligibility.high_signal_source_count,
                "eligibility_evidence_span_hours": eligibility.evidence_span_hours,
                "eligibility_blocked_memory_id": eligibility.blocked_memory_id,
            }
        )
    return snapshot


def metrics_snapshot(
    memory: KnowledgeMemory | BehaviorMemory,
    *,
    governance_config: dict[str, float | int] | None = None,
) -> dict[str, float | int | str | None]:
    snapshot = memory_quality_snapshot_sync(
        memory,
        governance_config=governance_config or default_governance_config(),
    )
    return {
        "support_score": memory.support_score,
        "contradiction_score": memory.contradiction_score,
        "evidence_count": memory.evidence_count,
        "contradiction_count": memory.contradiction_count,
        "stability_score": memory.stability_score,
        "freshness_score": memory.freshness_score,
        "goal_relevance_score": memory.goal_relevance_score,
        "quality_score": snapshot["quality_score"],
        "quality_tier": snapshot["quality_tier"],
        "promotion_readiness": snapshot["promotion_readiness"],
    }
