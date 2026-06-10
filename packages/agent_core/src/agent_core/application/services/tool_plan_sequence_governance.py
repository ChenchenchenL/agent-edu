from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.domain.entities.skill import SkillUsageEvent


@dataclass(frozen=True)
class ToolPlanSequenceContract:
    surface: str
    expected_sequence: list[str]
    expected_step_count: int
    is_multi_step: bool
    requires_repair_task_id: bool
    requires_created_review_task_ids: bool


@dataclass(frozen=True)
class ToolPlanSequenceUsageSummary:
    matched_usage_count: int
    sequence_match_count: int
    sequence_mismatch_count: int
    step_count_mismatch_count: int
    missing_sequence_metadata_count: int
    missing_repair_task_id_count: int
    missing_created_review_task_ids_count: int
    matched_usage_event_ids: list[str]
    mismatch_usage_event_ids: list[str]
    latest_observed_sequences: list[list[str]]

    def to_payload(self, contract: ToolPlanSequenceContract) -> dict[str, Any]:
        return {
            "expected_sequence": list(contract.expected_sequence),
            "expected_step_count": contract.expected_step_count,
            "matched_usage_count": self.matched_usage_count,
            "sequence_match_count": self.sequence_match_count,
            "sequence_mismatch_count": self.sequence_mismatch_count,
            "step_count_mismatch_count": self.step_count_mismatch_count,
            "missing_sequence_metadata_count": self.missing_sequence_metadata_count,
            "missing_repair_task_id_count": self.missing_repair_task_id_count,
            "missing_created_review_task_ids_count": self.missing_created_review_task_ids_count,
            "matched_usage_event_ids": list(self.matched_usage_event_ids),
            "mismatch_usage_event_ids": list(self.mismatch_usage_event_ids),
            "latest_observed_sequences": [list(item) for item in self.latest_observed_sequences],
        }


def build_tool_plan_sequence_contract(
    *,
    surface: str,
    tool_plan: list[dict[str, Any]] | None,
) -> ToolPlanSequenceContract | None:
    normalized_tool_plan = [dict(item) for item in (tool_plan or []) if isinstance(item, dict)]
    if not normalized_tool_plan:
        return None
    expected_sequence = [str(item.get("tool_name") or "").strip() for item in normalized_tool_plan]
    return ToolPlanSequenceContract(
        surface=surface,
        expected_sequence=expected_sequence,
        expected_step_count=len(expected_sequence),
        is_multi_step=len(expected_sequence) > 1,
        requires_repair_task_id="partial_replan" in expected_sequence,
        requires_created_review_task_ids="review_scheduling" in expected_sequence,
    )


def summarize_tool_plan_preview(
    *,
    contract: ToolPlanSequenceContract,
    tool_previews: list[dict[str, Any]],
) -> dict[str, Any]:
    preview_sequence = [str(item.get("tool_name") or "").strip() for item in tool_previews if isinstance(item, dict)]
    preview_step_ids = [str(item.get("step_id") or "").strip() for item in tool_previews if isinstance(item, dict)]
    missing_required_outputs: list[str] = []
    if contract.requires_repair_task_id and not _preview_has_created_task_ids(tool_previews, "partial_replan"):
        missing_required_outputs.append("repair_task_id")
    if contract.requires_created_review_task_ids and not _preview_has_created_task_ids(tool_previews, "review_scheduling"):
        missing_required_outputs.append("created_review_task_ids")
    preview_matches_contract = (
        preview_sequence == contract.expected_sequence
        and len(preview_sequence) == contract.expected_step_count
        and not missing_required_outputs
    )
    reason_codes: list[str] = []
    if preview_sequence != contract.expected_sequence:
        reason_codes.append("tool_plan_sequence_mismatch")
    if len(preview_sequence) != contract.expected_step_count:
        reason_codes.append("tool_plan_step_count_mismatch")
    if "repair_task_id" in missing_required_outputs:
        reason_codes.append("tool_plan_missing_repair_output")
    if "created_review_task_ids" in missing_required_outputs:
        reason_codes.append("tool_plan_missing_review_output")
    if preview_matches_contract:
        reason_codes.append("tool_plan_sequence_verified")
    return {
        "preview_available": bool(tool_previews),
        "expected_sequence": list(contract.expected_sequence),
        "expected_step_count": contract.expected_step_count,
        "preview_sequence": preview_sequence,
        "preview_step_count": len(preview_sequence),
        "preview_step_ids": preview_step_ids,
        "preview_matches_contract": preview_matches_contract,
        "missing_required_outputs": missing_required_outputs,
        "reason_codes": reason_codes,
    }


def summarize_tool_plan_usage(
    *,
    contract: ToolPlanSequenceContract,
    usage_events: list[SkillUsageEvent],
) -> ToolPlanSequenceUsageSummary:
    sequence_match_count = 0
    sequence_mismatch_count = 0
    step_count_mismatch_count = 0
    missing_sequence_metadata_count = 0
    missing_repair_task_id_count = 0
    missing_created_review_task_ids_count = 0
    matched_usage_event_ids: list[str] = []
    mismatch_usage_event_ids: list[str] = []
    latest_observed_sequences: list[list[str]] = []

    for event in usage_events:
        metadata = dict(event.metadata or {})
        observed_sequence = _observed_sequence(metadata)
        if observed_sequence:
            latest_observed_sequences.append(list(observed_sequence))
        matched_usage_event_ids.append(event.id)

        has_hard_mismatch = False
        if not observed_sequence:
            missing_sequence_metadata_count += 1
            has_hard_mismatch = True
        elif observed_sequence != contract.expected_sequence:
            sequence_mismatch_count += 1
            has_hard_mismatch = True
        else:
            sequence_match_count += 1

        observed_step_count = metadata.get("tool_plan_step_count")
        if not isinstance(observed_step_count, int) or observed_step_count != contract.expected_step_count:
            step_count_mismatch_count += 1
            has_hard_mismatch = True

        if contract.requires_repair_task_id and not _has_non_empty_string(metadata.get("repair_task_id")):
            missing_repair_task_id_count += 1
            has_hard_mismatch = True
        if contract.requires_created_review_task_ids and not _has_string_list(metadata.get("created_review_task_ids")):
            missing_created_review_task_ids_count += 1
            has_hard_mismatch = True

        if has_hard_mismatch and event.id not in mismatch_usage_event_ids:
            mismatch_usage_event_ids.append(event.id)

    return ToolPlanSequenceUsageSummary(
        matched_usage_count=len(matched_usage_event_ids),
        sequence_match_count=sequence_match_count,
        sequence_mismatch_count=sequence_mismatch_count,
        step_count_mismatch_count=step_count_mismatch_count,
        missing_sequence_metadata_count=missing_sequence_metadata_count,
        missing_repair_task_id_count=missing_repair_task_id_count,
        missing_created_review_task_ids_count=missing_created_review_task_ids_count,
        matched_usage_event_ids=matched_usage_event_ids,
        mismatch_usage_event_ids=mismatch_usage_event_ids,
        latest_observed_sequences=latest_observed_sequences[:5],
    )


def has_tool_plan_sequence_regression(
    *,
    summary: ToolPlanSequenceUsageSummary,
    mismatch_min: int,
    missing_metadata_min: int,
    required_output_missing_min: int,
) -> bool:
    if summary.sequence_mismatch_count >= max(mismatch_min, 1):
        return True
    if summary.step_count_mismatch_count >= max(mismatch_min, 1):
        return True
    if summary.missing_sequence_metadata_count >= max(missing_metadata_min, 1):
        return True
    if summary.missing_repair_task_id_count >= max(required_output_missing_min, 1):
        return True
    if summary.missing_created_review_task_ids_count >= max(required_output_missing_min, 1):
        return True
    return False


def tool_plan_sequence_reason_codes(summary: ToolPlanSequenceUsageSummary) -> list[str]:
    reason_codes: list[str] = []
    if summary.sequence_mismatch_count > 0:
        reason_codes.append("tool_plan_sequence_mismatch")
    if summary.step_count_mismatch_count > 0:
        reason_codes.append("tool_plan_step_count_mismatch")
    if summary.missing_sequence_metadata_count > 0:
        reason_codes.append("tool_plan_missing_sequence_metadata")
    if summary.missing_repair_task_id_count > 0:
        reason_codes.append("tool_plan_missing_repair_output")
    if summary.missing_created_review_task_ids_count > 0:
        reason_codes.append("tool_plan_missing_review_output")
    if not reason_codes and summary.sequence_match_count > 0:
        reason_codes.append("tool_plan_sequence_verified")
    return reason_codes


def _preview_has_created_task_ids(tool_previews: list[dict[str, Any]], tool_name: str) -> bool:
    for item in tool_previews:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != tool_name:
            continue
        preview_payload = dict(item.get("preview") or {})
        if _has_string_list(preview_payload.get("created_task_ids")):
            return True
    return False


def _observed_sequence(metadata: dict[str, Any]) -> list[str]:
    value = metadata.get("tool_plan_sequence")
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            normalized.append(item.strip())
    return normalized


def _has_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _has_string_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value)
