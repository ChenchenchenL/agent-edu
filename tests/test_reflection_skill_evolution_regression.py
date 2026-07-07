"""Reflection outcome -> skill evolution closed loop regression tests.

Covers all phases from REFLECTION_SKILL_EVOLUTION_CLOSED_LOOP_PLAN.md:

- Phase 1: Reflection outcome evaluation contract (pure policy)
- Phase 2: apply_outcome_feedback() fan-out matrix
- Phase 3: Proposal source / provenance / evidence snapshot contract
- Phase 4: Curator auto-governance gate matrix
- Phase 5: Curator governance evidence contract
- Phase 6: End-to-end closed loop scenarios

All tests use stub repositories and do not depend on real providers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent_core.application.services.reflection_outcome_policy import (
    EFFECTIVE_NOTE,
    EFFECTIVE_SCORE,
    FEEDBACK_EFFECTIVE_PRIORITY_DELTA,
    FEEDBACK_INEFFECTIVE_PRIORITY_DELTA,
    INEFFECTIVE_NOTE,
    INCONCLUSIVE_SCORE,
    PENDING_NOTE,
    SKILL_PACKAGE_PRIORITY_THRESHOLD,
    evaluate_outcome,
    feedback_priority_delta,
    requires_feedback,
    skill_package_eligible,
)
from agent_core.application.services.reflection_provenance import (
    PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION,
    PROPOSAL_SOURCE_CURATOR_RECOMMENDATION,
    PROPOSAL_SOURCE_DIRECT_REFLECTION,
    PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION,
    TRUSTED_AUTO_STAGE_SOURCES,
    curator_merge_evidence,
    curator_recommendation_evidence,
    direct_reflection_evidence,
    is_trusted_auto_stage_source,
    minimum_provenance_keys,
    patch_request_realization_evidence,
)
from agent_core.application.services.reflection_skill_evolution_curator import (
    ReflectionSkillEvolutionCuratorConfig,
    ReflectionSkillEvolutionCuratorService,
    TRUSTED_AUTO_STAGE_SOURCES as CURATOR_TRUSTED_SOURCES,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reflection_skill_evolution"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text())


# ---------------------------------------------------------------------------
# Minimal stub types for policy tests
# ---------------------------------------------------------------------------


@dataclass
class _FakeAttempt:
    id: str
    outcome_status: str
    topic_focus: str | None = None


@dataclass
class _FakeEvaluation:
    id: str = "eval-001"
    evaluation_status: str = "effective"
    improvement_score: float = 0.7
    window_size: int = 3
    observed_attempt_count: int = 3
    outcome_snapshot: dict[str, Any] = field(default_factory=dict)
    score_delta: float = 0.2
    sandbox_run_id: str | None = None


@dataclass
class _FakeProposal:
    id: str = "proposal-001"
    reflection_record_id: str = "reflect-001"
    learner_goal_id: str = "goal-001"
    proposal_type: str = "skill_package"
    status: str = "approved"
    risk_level: str = "low"
    approved_by: str | None = "system"
    latest_sandbox_run_id: str | None = "sandbox-001"
    evidence_snapshot: dict[str, Any] = field(default_factory=lambda: {
        "source": "skill_patch_request_realization",
        "source_skill_patch_request_id": "patch-001",
    })
    structured_patch_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeSandboxRun:
    id: str = "sandbox-001"
    status: str = "completed"
    error_code: str | None = None


@dataclass
class _FakeArtifact:
    id: str = "artifact-001"
    status: str = "candidate"
    lineage_id: str | None = None
    parent_artifact_id: str | None = None
    supersedes_artifact_id: str | None = None


# ---------------------------------------------------------------------------
# Minimal stub repositories for curator tests
# ---------------------------------------------------------------------------


class _StubAuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def record(self, *, event_type: str, resource_type: str, resource_id: str, actor: str, event_data: dict[str, Any]) -> None:
        self.events.append({"event_type": event_type, "reason_code": event_data.get("reason_code")})

    async def record_durable(self, **kwargs: Any) -> None:
        await self.record(**kwargs)


class _StubProposalRepo:
    def __init__(self, patch_requests: list[Any] | None = None, sandbox_candidates: list[Any] | None = None, auto_stage_candidates: list[Any] | None = None) -> None:
        self._patch_requests = patch_requests or []
        self._sandbox = sandbox_candidates or []
        self._auto_stage = auto_stage_candidates or []
        self.updated: list[Any] = []

    async def list_pending_skill_patch_realizations(self, *, limit: int) -> list[Any]:
        return self._patch_requests

    async def list_pending_skill_package_sandbox(self, *, limit: int) -> list[Any]:
        return self._sandbox

    async def list_pending_skill_package_auto_stage(self, *, limit: int) -> list[Any]:
        return self._auto_stage

    async def get_by_id(self, proposal_id: str) -> _FakeProposal | None:
        return None

    async def update(self, entity: Any) -> None:
        self.updated.append(entity)

    async def list_queue(self, **kwargs: Any) -> tuple[list[Any], int]:
        return [], 0

    async def count_queue(self, **kwargs: Any) -> int:
        return 0

    async def find_equivalent_active(self, **kwargs: Any) -> Any:
        return None


class _StubEvaluationRepo:
    def __init__(self, evaluation: Any | None = None) -> None:
        self._evaluation = evaluation

    async def get_by_proposal(self, proposal_id: str) -> Any | None:
        return self._evaluation


class _StubSandboxRunRepo:
    def __init__(self, sandbox_run: Any | None = None) -> None:
        self._sandbox_run = sandbox_run

    async def get_by_id(self, run_id: str) -> Any | None:
        return self._sandbox_run


class _StubArtifactRepo:
    def __init__(self, artifact: Any | None = None, recent_staged_count: int = 0) -> None:
        self._artifact = artifact
        self._recent_staged_count = recent_staged_count

    async def get_by_source_proposal_id(self, proposal_id: str) -> Any | None:
        return self._artifact

    async def count_recent_system_staged_replacements_for_goal(self, *, learner_goal_id: str, created_at_from: datetime) -> int:
        return self._recent_staged_count


class _StubProposalService:
    def __init__(self, reject_raises: Exception | None = None) -> None:
        self._reject_raises = reject_raises
        self.rejected: list[str] = []
        self.sandboxed: list[str] = []
        self.approved: list[str] = []

    async def reject(self, *, proposal_id: str, operator_id: str, reason_code: str, reason_note: str | None) -> _FakeProposal:
        if self._reject_raises:
            raise self._reject_raises
        self.rejected.append(proposal_id)
        p = _FakeProposal(id=proposal_id, status="rejected")
        p.evidence_snapshot = {"source": "skill_patch_request_realization"}
        return p

    async def auto_enqueue_sandbox(self, *, proposal_id: str) -> _FakeProposal:
        self.sandboxed.append(proposal_id)
        return _FakeProposal(id=proposal_id, status="sandbox_queued")

    async def approve(self, *, proposal_id: str, operator_id: str, reason_code: str, reason_note: str) -> _FakeProposal:
        self.approved.append(proposal_id)
        p = _FakeProposal(id=proposal_id, status="approved", approved_by=operator_id)
        p.evidence_snapshot = {"source": "skill_patch_request_realization"}
        return p

    async def realize_skill_patch_request(self, *, proposal_id: str, operator_id: str, reason_code: str, reason_note: str) -> _FakeProposal:
        return _FakeProposal(id=f"derived-{proposal_id}")


class _StubStagingService:
    def __init__(self) -> None:
        self.staged: list[str] = []

    async def stage_replacement_from_proposal(self, *, proposal_id: str, operator_id: str, reason_code: str, reason_note: str) -> _FakeArtifact:
        self.staged.append(proposal_id)
        return _FakeArtifact(id=f"staged-artifact-{proposal_id}")


class _FakeBeginNested:
    """Context manager that simulates db_session.begin_nested()."""

    def __call__(self) -> _FakeBeginNested:
        return self

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: Any) -> None:
        return None


class _FakeDbSession:
    begin_nested = _FakeBeginNested()


def _make_curator(
    *,
    auto_stage_candidates: list[Any] | None = None,
    sandbox_candidates: list[Any] | None = None,
    patch_requests: list[Any] | None = None,
    evaluation: Any | None = None,
    sandbox_run: Any | None = None,
    artifact: Any | None = None,
    recent_staged_count: int = 0,
    auto_staging_enabled: bool = True,
    db_session: Any | None = None,
    score_delta_min: float = 0.10,
    limit_24h: int = 3,
    audit_service: _StubAuditService | None = None,
    proposal_service: _StubProposalService | None = None,
    staging_service: _StubStagingService | None = None,
    sandbox_service: Any | None = None,
) -> tuple[ReflectionSkillEvolutionCuratorService, _StubAuditService, _StubProposalService, _StubStagingService]:
    audit = audit_service or _StubAuditService()
    proposals = proposal_service or _StubProposalService()
    staging = staging_service or _StubStagingService()
    config = ReflectionSkillEvolutionCuratorConfig(
        enabled=True,
        auto_staging_enabled=auto_staging_enabled,
        auto_stage_score_delta_min=score_delta_min,
        auto_stage_24h_limit=limit_24h,
    )
    service = ReflectionSkillEvolutionCuratorService(
        proposal_repository=_StubProposalRepo(
            patch_requests=patch_requests,
            sandbox_candidates=sandbox_candidates,
            auto_stage_candidates=auto_stage_candidates,
        ),
        evaluation_repository=_StubEvaluationRepo(evaluation=evaluation),
        sandbox_run_repository=_StubSandboxRunRepo(sandbox_run=sandbox_run),
        artifact_repository=_StubArtifactRepo(artifact=artifact, recent_staged_count=recent_staged_count),
        proposal_service=proposals,
        staging_service=staging,
        audit_service=audit,
        db_session=db_session,
        config=config,
        sandbox_service=sandbox_service,
    )
    return service, audit, proposals, staging


# ===========================================================================
# Phase 1: Reflection outcome evaluation contract
# ===========================================================================


class TestOutcomeEvaluationPolicy:
    """Phase 1: Fixture-based regression tests for the pure outcome evaluation policy."""

    @pytest.mark.parametrize(
        "case",
        _load_fixture("outcome_evaluation_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_evaluation_status(self, case: dict[str, Any]) -> None:
        attempts = [_FakeAttempt(id=a["id"], outcome_status=a["outcome_status"]) for a in case["topic_attempts"]]
        result = evaluate_outcome(topic_attempts=attempts)
        expected = case["expected"]
        assert result.evaluation_status == expected["evaluation_status"], (
            f"[{case['name']}] expected status {expected['evaluation_status']!r}, got {result.evaluation_status!r}"
        )

    @pytest.mark.parametrize(
        "case",
        _load_fixture("outcome_evaluation_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_improvement_score(self, case: dict[str, Any]) -> None:
        attempts = [_FakeAttempt(id=a["id"], outcome_status=a["outcome_status"]) for a in case["topic_attempts"]]
        result = evaluate_outcome(topic_attempts=attempts)
        assert result.improvement_score == pytest.approx(case["expected"]["improvement_score"], abs=1e-9)

    @pytest.mark.parametrize(
        "case",
        _load_fixture("outcome_evaluation_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_evaluation_note(self, case: dict[str, Any]) -> None:
        attempts = [_FakeAttempt(id=a["id"], outcome_status=a["outcome_status"]) for a in case["topic_attempts"]]
        result = evaluate_outcome(topic_attempts=attempts)
        assert result.evaluation_note == case["expected"]["evaluation_note"]

    @pytest.mark.parametrize(
        "case",
        _load_fixture("outcome_evaluation_cases.json")["cases"],
        ids=lambda c: c["name"],
    )
    def test_evaluated_flag(self, case: dict[str, Any]) -> None:
        attempts = [_FakeAttempt(id=a["id"], outcome_status=a["outcome_status"]) for a in case["topic_attempts"]]
        result = evaluate_outcome(topic_attempts=attempts)
        assert result.evaluated == case["expected"]["evaluated"]

    @pytest.mark.parametrize(
        "case",
        [c for c in _load_fixture("outcome_evaluation_cases.json")["cases"] if "outcome_snapshot" in c["expected"]],
        ids=lambda c: c["name"],
    )
    def test_outcome_snapshot_counts(self, case: dict[str, Any]) -> None:
        attempts = [_FakeAttempt(id=a["id"], outcome_status=a["outcome_status"]) for a in case["topic_attempts"]]
        result = evaluate_outcome(topic_attempts=attempts)
        snap = case["expected"]["outcome_snapshot"]
        assert result.outcome_snapshot["success_count"] == snap["success_count"]
        assert result.outcome_snapshot["failure_count"] == snap["failure_count"]

    def test_attempt_ids_recorded_in_snapshot(self) -> None:
        attempts = [_FakeAttempt(id=f"a{i}", outcome_status="completed") for i in range(3)]
        result = evaluate_outcome(topic_attempts=attempts)
        assert sorted(result.outcome_snapshot["attempt_ids"]) == ["a0", "a1", "a2"]

    def test_requires_feedback_effective(self) -> None:
        assert requires_feedback("effective") is True

    def test_requires_feedback_ineffective(self) -> None:
        assert requires_feedback("ineffective") is True

    def test_requires_feedback_pending_false(self) -> None:
        assert requires_feedback("pending") is False

    def test_requires_feedback_inconclusive_false(self) -> None:
        assert requires_feedback("inconclusive") is False

    def test_priority_delta_effective(self) -> None:
        assert feedback_priority_delta("effective") == pytest.approx(FEEDBACK_EFFECTIVE_PRIORITY_DELTA)

    def test_priority_delta_ineffective_greater_than_effective(self) -> None:
        assert feedback_priority_delta("ineffective") > feedback_priority_delta("effective")

    def test_priority_delta_inconclusive_zero(self) -> None:
        assert feedback_priority_delta("inconclusive") == 0.0

    def test_skill_package_eligible_effective_above_threshold(self) -> None:
        assert skill_package_eligible(evaluation_status="effective", duplicate_count=2, priority_score=0.8)

    def test_skill_package_not_eligible_ineffective(self) -> None:
        assert not skill_package_eligible(evaluation_status="ineffective", duplicate_count=2, priority_score=0.9)

    def test_skill_package_not_eligible_no_duplicates(self) -> None:
        assert not skill_package_eligible(evaluation_status="effective", duplicate_count=0, priority_score=0.9)

    def test_skill_package_not_eligible_below_priority_threshold(self) -> None:
        assert not skill_package_eligible(evaluation_status="effective", duplicate_count=2, priority_score=0.3)

    def test_boundary_exactly_at_window_size_is_evaluated(self) -> None:
        attempts = [_FakeAttempt(id=f"a{i}", outcome_status="completed") for i in range(3)]
        result = evaluate_outcome(topic_attempts=attempts, window_size=3)
        assert result.evaluated is True

    def test_boundary_one_below_window_is_not_evaluated(self) -> None:
        attempts = [_FakeAttempt(id=f"a{i}", outcome_status="completed") for i in range(2)]
        result = evaluate_outcome(topic_attempts=attempts, window_size=3)
        assert result.evaluated is False


# ===========================================================================
# Phase 2: apply_outcome_feedback() fan-out matrix
# ===========================================================================


class TestApplyOutcomeFeedbackFanOut:
    """Phase 2: Verify downstream trigger matrix of apply_outcome_feedback().

    Uses lightweight stubs to avoid I/O.  Ensures the fan-out semantics
    cannot silently change without breaking these tests.
    """

    def _make_evaluation(self, status: str) -> _FakeEvaluation:
        return _FakeEvaluation(evaluation_status=status)

    def _make_reflection(self, *, duplicate_count: int = 0, priority_score: float = 0.5) -> MagicMock:
        r = MagicMock()
        r.id = "reflect-001"
        r.learner_goal_id = "goal-001"
        r.learner_profile_id = "profile-001"
        r.duplicate_count = duplicate_count
        r.priority_score = priority_score
        r.status = "open"
        r.last_duplicate_at = None
        r.cooldown_until = None
        updated = MagicMock()
        updated.id = "reflect-001"
        updated.learner_goal_id = "goal-001"
        updated.learner_profile_id = "profile-001"
        updated.duplicate_count = duplicate_count
        updated.priority_score = min(1.0, priority_score + FEEDBACK_EFFECTIVE_PRIORITY_DELTA)
        updated.status = "open"
        updated.with_aggregation_update = MagicMock(return_value=updated)
        updated.with_status = MagicMock(return_value=updated)
        r.with_aggregation_update = MagicMock(return_value=updated)
        r.with_status = MagicMock(return_value=r)
        r._updated = updated
        return r

    @pytest.mark.parametrize("status", ["pending", "inconclusive"])
    @pytest.mark.asyncio
    async def test_noop_for_pending_and_inconclusive(self, status: str) -> None:
        """pending and inconclusive evaluations should be a complete no-op."""
        from agent_core.application.services.reflection import ReflectionService

        reflection = self._make_reflection()
        evaluation = self._make_evaluation(status)

        # We can instantiate ReflectionService with None for most dependencies
        # since apply_outcome_feedback() returns early for these statuses.
        service = ReflectionService(
            reflection_record_repository=AsyncMock(),
            reflection_action_repository=AsyncMock(),
            goal_repository=AsyncMock(),
            daily_task_repository=AsyncMock(),
            workflow_run_repository=AsyncMock(),
            study_plan_repository=AsyncMock(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=AsyncMock(),
            autonomy_job_service=AsyncMock(),
            audit_service=AsyncMock(),
            llm_provider=MagicMock(),
        )
        result = await service.apply_outcome_feedback(reflection=reflection, evaluation=evaluation)
        assert result is reflection, "Should return unchanged reflection for no-op status"

    @pytest.mark.asyncio
    async def test_none_evaluation_is_noop(self) -> None:
        """None evaluation must be a no-op."""
        from agent_core.application.services.reflection import ReflectionService

        reflection = self._make_reflection()
        service = ReflectionService(
            reflection_record_repository=AsyncMock(),
            reflection_action_repository=AsyncMock(),
            goal_repository=AsyncMock(),
            daily_task_repository=AsyncMock(),
            workflow_run_repository=AsyncMock(),
            study_plan_repository=AsyncMock(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=AsyncMock(),
            autonomy_job_service=AsyncMock(),
            audit_service=AsyncMock(),
            llm_provider=MagicMock(),
        )
        result = await service.apply_outcome_feedback(reflection=reflection, evaluation=None)
        assert result is reflection

    @pytest.mark.asyncio
    async def test_ineffective_triggers_needs_review(self) -> None:
        """ineffective status must set reflection to needs_review."""
        from agent_core.application.services.reflection import ReflectionService

        record_repo = AsyncMock()
        action_repo = AsyncMock()
        action_repo.list_by_reflection = AsyncMock(return_value=[])

        # Build real reflection-like mocks
        reflection = MagicMock()
        reflection.id = "reflect-001"
        reflection.learner_goal_id = "goal-001"
        reflection.learner_profile_id = "profile-001"
        reflection.duplicate_count = 0
        reflection.priority_score = 0.3
        reflection.status = "open"
        reflection.last_duplicate_at = None
        reflection.cooldown_until = None

        updated = MagicMock()
        updated.id = "reflect-001"
        updated.learner_goal_id = "goal-001"
        updated.learner_profile_id = "profile-001"
        updated.duplicate_count = 0
        updated.priority_score = 0.45
        updated.status = "open"  # before with_status
        updated.last_duplicate_at = None
        updated.cooldown_until = None

        needs_review = MagicMock()
        needs_review.status = "needs_review"
        needs_review.id = "reflect-001"
        needs_review.learner_goal_id = "goal-001"
        needs_review.learner_profile_id = "profile-001"
        needs_review.priority_score = 0.45

        updated.with_status = MagicMock(return_value=needs_review)
        reflection.with_aggregation_update = MagicMock(return_value=updated)

        memory_service = AsyncMock()
        memory_service.bridge_reflection_outcome = AsyncMock()

        reflective_memory_service = AsyncMock()
        reflective_memory_service.promote_or_refresh_candidate = AsyncMock()

        evaluation = _FakeEvaluation(evaluation_status="ineffective", improvement_score=-0.5)

        service = ReflectionService(
            reflection_record_repository=record_repo,
            reflection_action_repository=action_repo,
            goal_repository=AsyncMock(),
            daily_task_repository=AsyncMock(),
            workflow_run_repository=AsyncMock(),
            study_plan_repository=AsyncMock(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=memory_service,
            reflective_memory_service=reflective_memory_service,
            autonomy_job_service=AsyncMock(),
            audit_service=AsyncMock(),
            llm_provider=MagicMock(),
        )

        result = await service.apply_outcome_feedback(reflection=reflection, evaluation=evaluation)
        # Should have called with_status to set needs_review
        updated.with_status.assert_called_once_with("needs_review")

    @pytest.mark.asyncio
    async def test_effective_does_not_trigger_needs_review(self) -> None:
        """effective outcome must NOT set status to needs_review."""
        from agent_core.application.services.reflection import ReflectionService

        record_repo = AsyncMock()
        action_repo = AsyncMock()
        action_repo.list_by_reflection = AsyncMock(return_value=[])

        reflection = MagicMock()
        reflection.id = "reflect-001"
        reflection.learner_goal_id = "goal-001"
        reflection.learner_profile_id = "profile-001"
        reflection.duplicate_count = 0
        reflection.priority_score = 0.5
        reflection.status = "open"
        reflection.last_duplicate_at = None
        reflection.cooldown_until = None

        updated = MagicMock()
        updated.id = "reflect-001"
        updated.learner_goal_id = "goal-001"
        updated.learner_profile_id = "profile-001"
        updated.duplicate_count = 0
        updated.priority_score = 0.6
        updated.status = "open"
        updated.with_status = MagicMock(return_value=updated)
        reflection.with_aggregation_update = MagicMock(return_value=updated)

        memory_service = AsyncMock()
        memory_service.bridge_reflection_outcome = AsyncMock()

        reflective_memory_service = AsyncMock()
        reflective_memory_service.promote_or_refresh_candidate = AsyncMock()

        evaluation = _FakeEvaluation(evaluation_status="effective")

        service = ReflectionService(
            reflection_record_repository=record_repo,
            reflection_action_repository=action_repo,
            goal_repository=AsyncMock(),
            daily_task_repository=AsyncMock(),
            workflow_run_repository=AsyncMock(),
            study_plan_repository=AsyncMock(),
            task_attempt_repository=None,
            learner_topic_mastery_repository=None,
            goal_autonomy_state_repository=None,
            session_repository=None,
            memory_service=memory_service,
            reflective_memory_service=reflective_memory_service,
            autonomy_job_service=AsyncMock(),
            audit_service=AsyncMock(),
            llm_provider=MagicMock(),
        )

        await service.apply_outcome_feedback(reflection=reflection, evaluation=evaluation)
        # with_status should NOT have been called for effective
        updated.with_status.assert_not_called()


# ===========================================================================
# Phase 3: Proposal source / provenance / evidence snapshot contract
# ===========================================================================


class TestProposalProvenanceContract:
    """Phase 3: Verify provenance builders produce the correct field structures."""

    def test_direct_reflection_has_source(self) -> None:
        snap = direct_reflection_evidence(
            reflection_record_id="r-001",
            learner_goal_id="g-001",
            evidence_payload={"key": "value"},
        )
        assert snap["source"] == PROPOSAL_SOURCE_DIRECT_REFLECTION

    def test_direct_reflection_not_trusted(self) -> None:
        snap = direct_reflection_evidence(
            reflection_record_id="r-001",
            learner_goal_id="g-001",
            evidence_payload={},
        )
        assert not is_trusted_auto_stage_source(snap)

    def test_curator_recommendation_not_trusted(self) -> None:
        snap = curator_recommendation_evidence(
            recommendation_id="rec-001",
            artifact_id="artifact-001",
            skill_name="test_skill",
            scope="goal:g-001",
            surface="chat",
            recommendation_reason_code="patch_needed",
            evidence_snapshot={},
            metrics_snapshot={},
        )
        assert snap["source"] == PROPOSAL_SOURCE_CURATOR_RECOMMENDATION
        assert not is_trusted_auto_stage_source(snap)

    def test_patch_request_realization_is_trusted(self) -> None:
        snap = patch_request_realization_evidence(
            source_skill_patch_request_id="patch-001",
            recommendation_id="rec-001",
            source_artifact_id="artifact-001",
            source_artifact_lineage_id="lineage-001",
            skill_name="test_skill",
            scope="goal:g-001",
        )
        assert snap["source"] == PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION
        assert is_trusted_auto_stage_source(snap)

    def test_curator_merge_is_trusted(self) -> None:
        snap = curator_merge_evidence(
            recommendation_id="rec-merge-001",
            recommendation_reason_code="coverage_overlap",
            source_artifact_id="artifact-001",
            source_artifact_lineage_id="lineage-001",
            merge_artifact_ids=["artifact-002", "artifact-003"],
            evidence_snapshot={"conflict_count": 2},
            metrics_snapshot={"coverage_score": 0.65},
        )
        assert snap["source"] == PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION
        assert is_trusted_auto_stage_source(snap)

    def test_empty_snapshot_not_trusted(self) -> None:
        assert not is_trusted_auto_stage_source({})

    def test_none_source_not_trusted(self) -> None:
        assert not is_trusted_auto_stage_source({"source": None})

    @pytest.mark.parametrize("source", list(TRUSTED_AUTO_STAGE_SOURCES))
    def test_all_trusted_sources_are_trusted(self, source: str) -> None:
        assert is_trusted_auto_stage_source({"source": source})

    def test_minimum_keys_direct_reflection(self) -> None:
        required = minimum_provenance_keys(PROPOSAL_SOURCE_DIRECT_REFLECTION)
        snap = direct_reflection_evidence(
            reflection_record_id="r-001",
            learner_goal_id="g-001",
            evidence_payload={},
        )
        missing = required - snap.keys()
        assert not missing, f"Missing minimum provenance keys: {missing}"

    def test_minimum_keys_patch_request_realization(self) -> None:
        required = minimum_provenance_keys(PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION)
        snap = patch_request_realization_evidence(
            source_skill_patch_request_id="patch-001",
            recommendation_id=None,
            source_artifact_id=None,
            source_artifact_lineage_id=None,
            skill_name="skill_x",
            scope="global",
        )
        missing = required - snap.keys()
        assert not missing, f"Missing minimum provenance keys: {missing}"

    def test_minimum_keys_curator_recommendation(self) -> None:
        required = minimum_provenance_keys(PROPOSAL_SOURCE_CURATOR_RECOMMENDATION)
        snap = curator_recommendation_evidence(
            recommendation_id="rec-001",
            artifact_id=None,
            skill_name="skill_x",
            scope="global",
            surface="chat",
            recommendation_reason_code="patch_needed",
            evidence_snapshot={},
            metrics_snapshot={},
        )
        missing = required - snap.keys()
        assert not missing, f"Missing minimum provenance keys: {missing}"

    def test_minimum_keys_curator_merge(self) -> None:
        required = minimum_provenance_keys(PROPOSAL_SOURCE_CURATOR_MERGE_RECOMMENDATION)
        snap = curator_merge_evidence(
            recommendation_id="rec-001",
            recommendation_reason_code="coverage_overlap",
            source_artifact_id="artifact-001",
            source_artifact_lineage_id=None,
            merge_artifact_ids=["artifact-002"],
            evidence_snapshot={},
            metrics_snapshot={},
        )
        missing = required - snap.keys()
        assert not missing, f"Missing minimum provenance keys: {missing}"

    def test_trusted_sources_in_policy_match_curator(self) -> None:
        """The TRUSTED_AUTO_STAGE_SOURCES in policy and curator must be identical."""
        assert TRUSTED_AUTO_STAGE_SOURCES == CURATOR_TRUSTED_SOURCES, (
            "TRUSTED_AUTO_STAGE_SOURCES in reflection_provenance and curator service are out of sync"
        )


# ===========================================================================
# Phase 4: Curator auto-governance gate matrix
# ===========================================================================


class TestCuratorAutoGovernanceGates:
    """Phase 4: Verify each auto-governance gate suspends or rejects correctly.

    Each test exercises exactly one gate in isolation (all other gates are
    satisfied) to prove the gate is still checked.
    """

    def _good_proposal(self, *, source: str = "skill_patch_request_realization") -> _FakeProposal:
        p = _FakeProposal()
        p.evidence_snapshot = {
            "source": source,
            "source_skill_patch_request_id": "patch-001",
        }
        return p

    def _good_evaluation(self) -> _FakeEvaluation:
        return _FakeEvaluation(evaluation_status="effective", score_delta=0.5)

    def _good_sandbox_run(self) -> _FakeSandboxRun:
        return _FakeSandboxRun(status="completed")

    @pytest.mark.asyncio
    async def test_high_risk_sandbox_suspended(self) -> None:
        proposal = self._good_proposal()
        proposal.risk_level = "high"
        service, audit, _, _ = _make_curator(sandbox_candidates=[proposal])
        result = await service.run_once()
        # Phase 4: high-risk proposals auto-admit to stricter sandbox
        assert result.sandbox_enqueued_count == 1

    @pytest.mark.asyncio
    async def test_failed_sandbox_run_rejected_in_sandbox_phase(self) -> None:
        proposal = self._good_proposal()
        proposal.latest_sandbox_run_id = "sandbox-001"
        failed_run = _FakeSandboxRun(status="failed", error_code="timeout")
        service, audit, _, _ = _make_curator(
            sandbox_candidates=[proposal],
            sandbox_run=failed_run,
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        reason_codes = [e["reason_code"] for e in audit.events]
        assert "sandbox_failed" in reason_codes

    @pytest.mark.asyncio
    async def test_high_risk_auto_stage_suspended(self) -> None:
        proposal = self._good_proposal()
        proposal.risk_level = "high"
        service, audit, _, _ = _make_curator(auto_stage_candidates=[proposal])
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "risk_level_high" for e in audit.events)

    @pytest.mark.asyncio
    async def test_approved_by_missing_suspended(self) -> None:
        proposal = self._good_proposal()
        proposal.status = "approved"
        proposal.approved_by = None
        service, audit, _, _ = _make_curator(auto_stage_candidates=[proposal])
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "approved_by_missing" for e in audit.events)

    @pytest.mark.asyncio
    async def test_approved_by_non_system_suspended(self) -> None:
        proposal = self._good_proposal()
        proposal.status = "approved"
        proposal.approved_by = "human-operator-001"
        service, audit, _, _ = _make_curator(auto_stage_candidates=[proposal])
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "approved_by_non_system" for e in audit.events)

    @pytest.mark.asyncio
    async def test_non_trusted_source_suspended(self) -> None:
        proposal = self._good_proposal(source="skill_curator_recommendation")
        service, audit, _, _ = _make_curator(auto_stage_candidates=[proposal])
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "non_replacement_source" for e in audit.events)

    @pytest.mark.asyncio
    async def test_missing_sandbox_run_rejected(self) -> None:
        proposal = self._good_proposal()
        proposal.latest_sandbox_run_id = None
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=self._good_evaluation(),
            sandbox_run=None,
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        assert any(e["reason_code"] == "missing_sandbox_run" for e in audit.events)

    @pytest.mark.asyncio
    async def test_missing_evaluation_rejected(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=None,
            sandbox_run=self._good_sandbox_run(),
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        assert any(e["reason_code"] == "missing_evaluation" for e in audit.events)

    @pytest.mark.asyncio
    async def test_evaluation_ineffective_rejected(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="ineffective", score_delta=-0.3),
            sandbox_run=self._good_sandbox_run(),
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        assert any(e["reason_code"] == "evaluation_ineffective" for e in audit.events)

    @pytest.mark.asyncio
    async def test_evaluation_inconclusive_rejected(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="inconclusive", score_delta=0.0),
            sandbox_run=self._good_sandbox_run(),
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        assert any(e["reason_code"] == "evaluation_inconclusive" for e in audit.events)

    @pytest.mark.asyncio
    async def test_negative_score_delta_rejected(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="effective", score_delta=-0.1),
            sandbox_run=self._good_sandbox_run(),
        )
        result = await service.run_once()
        assert result.rejected_count == 1
        assert any(e["reason_code"] == "negative_score_delta" for e in audit.events)

    @pytest.mark.asyncio
    async def test_score_delta_below_threshold_suspended(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="effective", score_delta=0.05),
            sandbox_run=self._good_sandbox_run(),
            auto_staging_enabled=True,
            db_session=_FakeDbSession(),
        )
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "score_delta_below_threshold" for e in audit.events)

    @pytest.mark.asyncio
    async def test_auto_staging_disabled_suspended(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=self._good_evaluation(),
            sandbox_run=self._good_sandbox_run(),
            auto_staging_enabled=False,  # disabled by default
            db_session=_FakeDbSession(),
        )
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "auto_staging_disabled" for e in audit.events)

    @pytest.mark.asyncio
    async def test_savepoint_unavailable_suspended(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=self._good_evaluation(),
            sandbox_run=self._good_sandbox_run(),
            auto_staging_enabled=True,
            db_session=None,  # No session -> savepoint unavailable
        )
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "savepoint_unavailable" for e in audit.events)

    @pytest.mark.asyncio
    async def test_rate_limit_reached_suspended(self) -> None:
        proposal = self._good_proposal()
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=self._good_evaluation(),
            sandbox_run=self._good_sandbox_run(),
            auto_staging_enabled=True,
            db_session=_FakeDbSession(),
            recent_staged_count=3,  # at limit
        )
        result = await service.run_once()
        assert result.suspended_count == 1
        assert any(e["reason_code"] == "auto_stage_24h_limit_reached" for e in audit.events)

    @pytest.mark.asyncio
    async def test_all_gates_pass_produces_staged(self) -> None:
        """When all gates pass and auto_staging_enabled=True, result should be staged."""
        proposal = self._good_proposal()
        proposal.status = "sandbox_completed"
        proposal.approved_by = None  # will be approved by system during staging
        service, audit, proposals, staging = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=self._good_evaluation(),
            sandbox_run=self._good_sandbox_run(),
            auto_staging_enabled=True,
            db_session=_FakeDbSession(),
            recent_staged_count=0,
        )
        result = await service.run_once()
        assert result.staged_count == 1
        assert result.rejected_count == 0
        assert result.suspended_count == 0


# ===========================================================================
# Phase 5: Curator governance evidence contract
# ===========================================================================


class TestGovernanceEvidenceContract:
    """Phase 5: Verify governance evidence snapshot structure and constraints."""

    def test_fixture_lists_all_trusted_sources(self) -> None:
        data = _load_fixture("governance_evidence_cases.json")
        trusted_in_fixture = {
            s["source"]
            for s in data["proposal_sources"]
            if s["trusted_for_auto_stage"]
        }
        assert trusted_in_fixture == TRUSTED_AUTO_STAGE_SOURCES

    def test_fixture_trusted_sources_match_curator(self) -> None:
        data = _load_fixture("governance_evidence_cases.json")
        trusted_in_fixture = {
            s["source"]
            for s in data["proposal_sources"]
            if s["trusted_for_auto_stage"]
        }
        assert trusted_in_fixture == CURATOR_TRUSTED_SOURCES

    @pytest.mark.parametrize(
        "entry",
        _load_fixture("governance_evidence_cases.json")["proposal_sources"],
        ids=lambda e: e["source"],
    )
    def test_example_snapshot_has_minimum_keys(self, entry: dict[str, Any]) -> None:
        required = set(entry["minimum_required_keys"])
        example = entry["example"]
        missing = required - example.keys()
        assert not missing, f"[{entry['source']}] missing minimum keys: {missing}"

    @pytest.mark.parametrize(
        "entry",
        _load_fixture("governance_evidence_cases.json")["proposal_sources"],
        ids=lambda e: e["source"],
    )
    def test_trusted_classification_matches_policy(self, entry: dict[str, Any]) -> None:
        example = entry["example"]
        policy_trusted = is_trusted_auto_stage_source(example)
        fixture_trusted = entry["trusted_for_auto_stage"]
        assert policy_trusted == fixture_trusted, (
            f"[{entry['source']}] policy trust ({policy_trusted}) disagrees with fixture ({fixture_trusted})"
        )

    def test_curator_event_data_contains_expected_fields(self) -> None:
        """Verify the fixture documents the curator event data fields."""
        data = _load_fixture("governance_evidence_cases.json")
        event_fields = set(data["curator_event_data_fields"]["fields"])
        required = {
            "proposal_id", "proposal_status", "proposal_type", "learner_goal_id",
            "reason_code", "reason_note", "evaluation_id", "evaluation_status",
            "sandbox_run_id", "score_delta",
        }
        assert required.issubset(event_fields), (
            f"Curator event data missing fields: {required - event_fields}"
        )


# ===========================================================================
# Phase 6: End-to-end closed loop scenarios
# ===========================================================================


class TestEndToEndClosedLoopScenarios:
    """Phase 6: Representative closed-loop regression scenarios.

    Scenario 1: effective reflection -> proposal admitted -> all gates pass -> staged
    Scenario 2: ineffective reflection -> only governance evidence, no skill package
    Scenario 3: duplicate reflection below priority -> no skill package created
    Scenario 4: patch-needed -> patch request -> realization -> trusted replacement -> staged
    Scenario 5: auto-stage blocked at every gate (fail-closed proof)
    """

    def test_scenario1_fixture_correctness(self) -> None:
        """effective outcome path: requires_feedback=True, all downstream triggered."""
        result = evaluate_outcome(
            topic_attempts=[
                _FakeAttempt(id="a1", outcome_status="completed"),
                _FakeAttempt(id="a2", outcome_status="completed"),
                _FakeAttempt(id="a3", outcome_status="failed"),
            ]
        )
        assert result.evaluation_status == "effective"
        assert requires_feedback(result.evaluation_status)
        assert result.improvement_score == pytest.approx(EFFECTIVE_SCORE)

    def test_scenario2_ineffective_blocks_skill_package(self) -> None:
        """ineffective reflection must never create skill packages regardless of priority."""
        assert not skill_package_eligible(
            evaluation_status="ineffective",
            duplicate_count=5,
            priority_score=0.99,
        )
        result = evaluate_outcome(
            topic_attempts=[
                _FakeAttempt(id="a1", outcome_status="failed"),
                _FakeAttempt(id="a2", outcome_status="skipped"),
                _FakeAttempt(id="a3", outcome_status="failed"),
            ]
        )
        assert result.evaluation_status == "ineffective"
        assert not skill_package_eligible(
            evaluation_status=result.evaluation_status,
            duplicate_count=5,
            priority_score=1.0,
        )

    def test_scenario3_no_skill_package_when_below_threshold(self) -> None:
        """duplicate=0, priority=0.5: effective but no skill package."""
        assert not skill_package_eligible(
            evaluation_status="effective",
            duplicate_count=0,
            priority_score=0.5,
        )

    def test_scenario4_patch_realization_is_trusted(self) -> None:
        """patch_request_realization -> replacement is trusted for auto-stage."""
        snap = patch_request_realization_evidence(
            source_skill_patch_request_id="patch-001",
            recommendation_id="rec-001",
            source_artifact_id="artifact-001",
            source_artifact_lineage_id="lineage-001",
            skill_name="concept_explainer",
            scope="goal:g-001",
        )
        assert is_trusted_auto_stage_source(snap)
        assert snap["source"] == PROPOSAL_SOURCE_PATCH_REQUEST_REALIZATION
        assert "source_skill_patch_request_id" in snap

    @pytest.mark.asyncio
    async def test_scenario5_auto_stage_blocked_no_session(self) -> None:
        """All evaluation gates pass but savepoint unavailable -> fail-closed."""
        proposal = _FakeProposal()
        proposal.status = "sandbox_completed"
        proposal.evidence_snapshot = {
            "source": "skill_patch_request_realization",
            "source_skill_patch_request_id": "patch-001",
        }
        proposal.approved_by = None
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="effective", score_delta=0.5),
            sandbox_run=_FakeSandboxRun(status="completed"),
            auto_staging_enabled=True,
            db_session=None,  # no savepoint -> blocked
        )
        result = await service.run_once()
        assert result.staged_count == 0
        assert result.suspended_count == 1
        reason_codes = [e["reason_code"] for e in audit.events]
        assert "savepoint_unavailable" in reason_codes

    @pytest.mark.asyncio
    async def test_scenario5_auto_stage_blocked_non_trusted_source(self) -> None:
        """Non-trusted source -> always fail-closed regardless of other gates."""
        proposal = _FakeProposal()
        proposal.evidence_snapshot = {"source": "reflection_direct"}
        proposal.status = "sandbox_completed"
        proposal.approved_by = "system"
        service, audit, _, _ = _make_curator(
            auto_stage_candidates=[proposal],
            evaluation=_FakeEvaluation(evaluation_status="effective", score_delta=0.5),
            sandbox_run=_FakeSandboxRun(status="completed"),
            auto_staging_enabled=True,
            db_session=_FakeDbSession(),
        )
        result = await service.run_once()
        assert result.staged_count == 0
        assert any(e["reason_code"] == "non_replacement_source" for e in audit.events)

    @pytest.mark.asyncio
    async def test_curator_auto_runs_sandbox_execution(self) -> None:
        """Verify curator executes the sandbox run when a proposal is enqueued."""
        class MockSandboxService:
            def __init__(self) -> None:
                self.executed_proposals: list[str] = []

            async def execute(self, *, proposal_id: str) -> Any:
                self.executed_proposals.append(proposal_id)
                return _FakeSandboxRun(status="completed")

        sandbox_svc = MockSandboxService()
        proposal = _FakeProposal()
        proposal.status = "proposed"
        proposal.risk_level = "low"
        proposal.proposal_type = "skill_package"
        proposal.target_scope = "chat"

        service, audit, proposals, _ = _make_curator(
            sandbox_candidates=[proposal],
            auto_staging_enabled=True,
            db_session=_FakeDbSession(),
            sandbox_service=sandbox_svc,
        )
        result = await service.run_once()
        # Sandbox must be enqueued
        assert result.sandbox_enqueued_count == 1
        # sandbox_service.execute must have been triggered
        assert proposal.id in sandbox_svc.executed_proposals


# ===========================================================================
# Constants contract tests (prevent accidental threshold drift)
# ===========================================================================


class TestPolicyConstantsContract:
    """Verify threshold constants match the expected values from code and fixtures."""

    def test_window_size_default_is_3(self) -> None:
        from agent_core.application.services.reflection_outcome_policy import WINDOW_SIZE_DEFAULT
        assert WINDOW_SIZE_DEFAULT == 3

    def test_effective_score_is_0_7(self) -> None:
        assert EFFECTIVE_SCORE == pytest.approx(0.7)

    def test_ineffective_score_is_negative_0_5(self) -> None:
        from agent_core.application.services.reflection_outcome_policy import INEFFECTIVE_SCORE
        assert INEFFECTIVE_SCORE == pytest.approx(-0.5)

    def test_inconclusive_score_is_0(self) -> None:
        assert INCONCLUSIVE_SCORE == pytest.approx(0.0)

    def test_skill_package_priority_threshold_is_0_7(self) -> None:
        assert SKILL_PACKAGE_PRIORITY_THRESHOLD == pytest.approx(0.7)

    def test_curator_config_auto_staging_disabled_by_default(self) -> None:
        config = ReflectionSkillEvolutionCuratorConfig()
        assert config.auto_staging_enabled is False, (
            "auto_staging_enabled must default to False (fail-closed)"
        )

    def test_curator_config_score_delta_min(self) -> None:
        config = ReflectionSkillEvolutionCuratorConfig()
        assert config.auto_stage_score_delta_min == pytest.approx(0.10)

    def test_curator_config_24h_limit(self) -> None:
        config = ReflectionSkillEvolutionCuratorConfig()
        assert config.auto_stage_24h_limit == 3

    def test_effective_note_is_stable(self) -> None:
        assert EFFECTIVE_NOTE == "follow-up attempts improved"

    def test_ineffective_note_is_stable(self) -> None:
        assert INEFFECTIVE_NOTE == "follow-up attempts did not improve"
