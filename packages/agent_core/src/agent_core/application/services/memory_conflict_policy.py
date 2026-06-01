from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.entities.memory import ConflictStatusImpact

CONFLICT_CONTRADICTION_THRESHOLD = 0.35


@dataclass(frozen=True)
class MemoryConflictDecision:
    reason_code: str
    reason_note: str
    handling_result: str
    status_impact: ConflictStatusImpact


class MemoryConflictPolicy:
    @staticmethod
    def open_contradictory_evidence(
        *,
        topic_key: str,
        current_memory_count: int,
        severity_score: float,
    ) -> MemoryConflictDecision:
        return MemoryConflictDecision(
            reason_code="contradiction_score_threshold",
            reason_note=(
                f"{current_memory_count} current memories for topic '{topic_key}' have contradiction score "
                f"at or above {CONFLICT_CONTRADICTION_THRESHOLD:.2f}."
            ),
            handling_result="open_review_required",
            status_impact=ConflictStatusImpact.build(
                validation_status="contested",
                recommended_use="verify_before_use",
                governance_effect="blocks_promotion_and_adds_demotion_pressure",
                direct_status_change=False,
                severity_score=severity_score,
            ),
        )

    @staticmethod
    def close_no_current_members() -> MemoryConflictDecision:
        handling_result = "stale_no_current_members"
        return MemoryConflictDecision(
            reason_code="stale_no_current_members",
            reason_note="No current conflict members remained after refresh.",
            handling_result=handling_result,
            status_impact=MemoryConflictPolicy._closed_status_impact(handling_result=handling_result),
        )

    @staticmethod
    def close_member_not_visible() -> MemoryConflictDecision:
        handling_result = "stale_member_not_visible"
        return MemoryConflictDecision(
            reason_code="stale_member_not_visible",
            reason_note="One or more member memories are no longer visible to conflict refresh.",
            handling_result=handling_result,
            status_impact=MemoryConflictPolicy._closed_status_impact(handling_result=handling_result),
        )

    @staticmethod
    def close_resolved_by_refresh() -> MemoryConflictDecision:
        handling_result = "resolved_by_evidence_refresh"
        return MemoryConflictDecision(
            reason_code="resolved_contradiction_below_threshold",
            reason_note="All visible member memories are now below the contradiction threshold.",
            handling_result=handling_result,
            status_impact=MemoryConflictPolicy._closed_status_impact(handling_result=handling_result),
        )

    @staticmethod
    def close_inactive_refresh() -> MemoryConflictDecision:
        handling_result = "stale_inactive_refresh"
        return MemoryConflictDecision(
            reason_code="stale_inactive_refresh",
            reason_note="The previous conflict identity was no longer active after refresh.",
            handling_result=handling_result,
            status_impact=MemoryConflictPolicy._closed_status_impact(handling_result=handling_result),
        )

    @staticmethod
    def _closed_status_impact(*, handling_result: str) -> ConflictStatusImpact:
        return ConflictStatusImpact.build(
            validation_status="unchanged",
            recommended_use="normal_governance",
            governance_effect="conflict_pressure_removed",
            direct_status_change=False,
            handling_result=handling_result,
        )
