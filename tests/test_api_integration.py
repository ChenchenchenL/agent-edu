from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, timedelta
from hashlib import sha256
import os

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from agent_core.api.app import create_app
from agent_core.api.dependencies import (
    get_db_session,
    get_skill_artifact_lifecycle_service,
    get_skill_replacement_staging_service,
    require_operator_api_key,
)
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.models import AuditEventModel
from agent_core.infrastructure.db.repositories import (
    GoalSkillBindingRepository,
    ReflectionRecordRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    SkillArtifactRepository,
    SkillUsageEventRepository,
)


async def _audit_event_types() -> list[str]:
    engine = create_async_engine(os.environ["AGENT_EDU_DATABASE_URL"], future=True)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(select(AuditEventModel.event_type).order_by(AuditEventModel.created_at))
            return list(result.scalars().all())
    finally:
        await engine.dispose()


async def _audit_events() -> list[dict[str, object]]:
    engine = create_async_engine(os.environ["AGENT_EDU_DATABASE_URL"], future=True)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                select(
                    AuditEventModel.event_type,
                    AuditEventModel.actor,
                    AuditEventModel.event_data,
                ).order_by(AuditEventModel.created_at)
            )
            return [
                {
                    "event_type": event_type,
                    "actor": actor,
                    "event_data": event_data,
                }
                for event_type, actor, event_data in result.all()
            ]
    finally:
        await engine.dispose()


def _create_profile_with_key(client) -> tuple[str, str]:
    response = client.post("/api/v1/learner-profiles", json={})
    assert response.status_code == 200
    payload = response.json()
    return payload["id"], payload["access_key"]


def _learner_headers(access_key: str) -> dict[str, str]:
    return {"X-Learner-Key": access_key}


def _operator_headers() -> dict[str, str]:
    return {"X-Operator-Key": "secret-operator"}


def _operator_actor_id() -> str:
    return f"operator:{sha256('secret-operator'.encode('utf-8')).hexdigest()[:12]}"


def _run_autonomy_worker_once() -> None:
    from agent_core.api import dependencies as api_dependencies

    async def run_worker_once() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            service = api_dependencies.get_task_service(db)
            await service.run_due_autonomy_jobs(raise_on_error=True, lease_owner="test-worker")

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_worker_once())
    finally:
        loop.close()


async def _seed_replaceable_skill_artifacts(
    *,
    learner_profile_id: str,
    learner_goal_id: str,
) -> tuple[SkillArtifact, SkillArtifact]:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        current = SkillArtifact.build(
            name="create_quiz",
            version="0.1.98",
            skill_type="learned",
            scope="quiz",
            status="stable",
            description="Current quiz skill package.",
            quality_score=0.8,
            approved_by="operator:seed",
        )
        await SkillArtifactRepository(db).create(current)

        payload = {
            "artifact_kind": "declarative_skill_package",
            "skill_name": "create_quiz",
            "bundle_id": "replace-bundle",
            "surface": "quiz",
            "match_rules": {"task_types": ["practice"]},
            "runtime_directives": {"feedback_style": "guided_correction"},
            "tool_plan": [],
            "scoring_contract": {"mode": "rule_replay_live_llm"},
        }
        reflection = ReflectionRecord.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=None,
            workflow_run_id=None,
            study_plan_id=None,
            scope="goal",
            target_type="learner_goal",
            target_id=learner_goal_id,
            trigger_source="consecutive_failure_pattern",
            reflection_depth=1,
            dedupe_key=f"replace-skill:{learner_goal_id}",
            aggregation_key=f"replace-skill:{learner_goal_id}",
            duplicate_count=1,
            priority_score=0.8,
            last_duplicate_at=None,
            cooldown_until=None,
            primary_root_cause="knowledge_gap",
            secondary_root_causes=[],
            severity="medium",
            confidence_score=0.8,
            summary="Seeded replacement skill package reflection.",
            evidence_summary="Seeded API integration evidence.",
            recommended_next_step="Replace quiz skill package.",
            evidence_payload={"source": "api_integration"},
        )
        await ReflectionRecordRepository(db).create(reflection)
        proposal = ReflectionProposal.build(
            reflection_record_id=reflection.id,
            learner_goal_id=learner_goal_id,
            proposal_type="skill_package",
            target_scope="quiz",
            priority_score=0.8,
            hypothesis="Replacement quiz package improves remediation.",
            change_summary="Replace quiz skill package.",
            structured_patch_payload=payload,
            expected_improvement="Better quiz remediation.",
            risk_level="low",
            evidence_snapshot={
                "source": "skill_patch_request_realization",
                "source_skill_patch_request_id": "patch-request-seed",
                "source_artifact_id": current.id,
                "source_artifact_lineage_id": current.lineage_id,
                "usage_event_ids": ["usage-seed-1", "usage-seed-2", "usage-seed-3"],
            },
        ).enqueue_sandbox(
            sandbox_run_id="sandbox-replace",
        ).start_sandbox(
            sandbox_run_id="sandbox-replace",
        ).complete_sandbox(
            sandbox_run_id="sandbox-replace",
            evaluation_status="effective",
            evaluation_summary="sandbox:0.20",
        ).approve(
            operator_id="operator:seed",
            reason_code="validated",
            reason_note=None,
        )
        await ReflectionProposalRepository(db).create(proposal)
        evaluation = ReflectionProposalEvaluation.build(
            proposal_id=proposal.id,
            comparison_window_size=3,
            baseline_policy_snapshot={},
            candidate_policy_snapshot=payload,
            evaluator_type="rule",
            sandbox_run_id="sandbox-replace",
        ).with_result(
            evaluation_status="effective",
            simulated_outcome_summary={"score_delta": 0.2},
            score_delta=0.2,
            sandbox_run_id="sandbox-replace",
        )
        await ReflectionProposalEvaluationRepository(db).create(evaluation)

        replacement = SkillArtifact.build(
            name="create_quiz",
            version="0.1.99",
            lineage_id=current.lineage_id,
            parent_artifact_id=current.id,
            supersedes_artifact_id=current.id,
            skill_type="learned",
            scope="quiz",
            status="staged",
            description=proposal.change_summary,
            definition={
                "artifact_kind": payload["artifact_kind"],
                "hypothesis": proposal.hypothesis,
                "change_summary": proposal.change_summary,
                "expected_improvement": proposal.expected_improvement,
                "match_rules": dict(payload["match_rules"]),
                "scoring_contract": dict(payload["scoring_contract"]),
                "source_proposal": {
                    "id": proposal.id,
                    "risk_level": proposal.risk_level,
                    "evaluation_status": evaluation.evaluation_status,
                    "score_delta": evaluation.score_delta,
                    "sandbox_run_id": evaluation.sandbox_run_id,
                },
            },
            runtime_directives=dict(payload["runtime_directives"]),
            tool_plan=[],
            compatibility_contract={
                "surfaces": ["quiz"],
                "implementation_binding": "create_quiz",
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=[proposal.reflection_record_id],
            source_memory_ids=["memory-replace"],
            source_proposal_id=proposal.id,
            quality_score=0.7,
            created_by="operator:seed",
        )
        await SkillArtifactRepository(db).create(replacement)

        rollout = ReflectionProposalRollout.build(
            proposal_id=proposal.id,
            learner_goal_id=learner_goal_id,
            surface="quiz",
            baseline_snapshot=payload,
            runtime_overlay_payload={
                "skill_name": "create_quiz",
                "surface": "quiz",
                "match_rules": dict(payload["match_rules"]),
                "runtime_directives": dict(payload["runtime_directives"]),
                "tool_plan": [],
            },
            activated_by="operator:seed",
        )
        binding = GoalSkillBinding.build(
            proposal_id=proposal.id,
            rollout_id=rollout.id,
            learner_goal_id=learner_goal_id,
            surface="quiz",
            priority_score=proposal.priority_score,
            match_rules=dict(payload["match_rules"]),
            runtime_directives=dict(payload["runtime_directives"]),
            tool_plan=[],
        ).with_status("rolled_out")
        observation = ReflectionProposalRolloutObservation.build(
            rollout_id=rollout.id,
            proposal_id=proposal.id,
            learner_goal_id=learner_goal_id,
            surface="quiz",
            recommendation="promote",
            observed_sample_count=3,
            positive_score=0.8,
            negative_score=0.0,
            signal_summary={"completed_usage_count": 1},
            reason_codes=["usage_promoted"],
        )
        observation_2 = replace(
            ReflectionProposalRolloutObservation.build(
                rollout_id=rollout.id,
                proposal_id=proposal.id,
                learner_goal_id=learner_goal_id,
                surface="quiz",
                recommendation="promote",
                observed_sample_count=4,
                positive_score=0.9,
                negative_score=0.0,
                signal_summary={"completed_usage_count": 3},
                reason_codes=["stable_usage_promoted"],
            ),
            created_at=observation.created_at + timedelta(minutes=1),
        )
        rollout = rollout.with_status("rolled_out", latest_observation_id=observation_2.id)
        await ReflectionProposalRolloutRepository(db).create(rollout)
        await GoalSkillBindingRepository(db).create(binding)
        await ReflectionProposalRolloutObservationRepository(db).create(observation)
        await ReflectionProposalRolloutObservationRepository(db).create(observation_2)
        usage_repository = SkillUsageEventRepository(db)
        for index in range(3):
            usage_event = replace(
                SkillUsageEvent.build(
                    skill_artifact_id=None,
                    skill_name="create_quiz",
                    skill_version=None,
                    skill_status_at_use=None,
                    learner_goal_id=learner_goal_id,
                    surface="quiz",
                    outcome_status="completed",
                    resolver_status="missing_artifact",
                    selection_reason="artifact_missing_static_fallback",
                    metadata={
                        "skill_package_rollout": {
                            "proposal_id": proposal.id,
                            "rollout_id": rollout.id,
                            "binding_id": binding.id,
                            "skill_name": "create_quiz",
                            "surface": "quiz",
                        }
                    },
                ),
                created_at=rollout.activated_at + timedelta(minutes=index + 1),
            )
            await usage_repository.create(usage_event)
        await db.commit()
        return current, replacement


async def _seed_active_quiz_runtime_artifact() -> SkillArtifact:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        artifact = SkillArtifact.build(
            name="create_quiz",
            version="1.0.1",
            skill_type="learned",
            scope="quiz",
            status="active",
            description="Active governed quiz runtime artifact.",
            runtime_directives={
                "question_count": 3,
                "skill_directives": ["show_work"],
                "feedback_style": "guided_correction",
            },
            compatibility_contract={
                "surfaces": ["quiz"],
                "implementation_binding": "llm_create_quiz_v1",
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            quality_score=0.9,
            approved_by="operator:seed",
        )
        await SkillArtifactRepository(db).create(artifact)
        await db.commit()
        return artifact


async def _seed_skill_curator_recommendation(
    *,
    recommendation_type: str = "patch_needed",
    recommended_action: str = "none",
    reason_code: str = "quality_regression",
    artifact_id: str | None = None,
    skill_name: str = "create_quiz",
    scope: str = "quiz",
    surface: str = "quiz",
    evidence_snapshot: dict[str, object] | None = None,
    metrics_snapshot: dict[str, object] | None = None,
    related_artifact_ids: list[str] | None = None,
) -> str:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        service = api_dependencies.get_skill_curator_recommendation_service(db)
        recommendation = await service.create_recommendation(
            artifact_id=artifact_id,
            skill_name=skill_name,
            scope=scope,
            surface=surface,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            reason_code=reason_code,
            reason_note="Seeded API integration recommendation.",
            evidence_snapshot=evidence_snapshot or {"usage_event_ids": ["usage-api-1"]},
            metrics_snapshot=metrics_snapshot or {"negative_usage_rate": 0.4},
            related_artifact_ids=related_artifact_ids,
            created_by="skill_curator:test",
        )
        await db.commit()
        return recommendation.id


async def _seed_merge_candidate_skill_artifacts(
    *,
    learner_profile_id: str,
    learner_goal_id: str,
) -> tuple[SkillArtifact, SkillArtifact, str]:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        source_artifact = SkillArtifact.build(
            name="create_quiz",
            version="0.1.80",
            skill_type="learned",
            scope="quiz",
            status="stable",
            description="Current quiz skill package.",
            definition={
                "artifact_kind": "declarative_skill_package",
                "match_rules": {"task_types": ["practice"], "topic_keys": ["algebra"]},
                "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
            },
            runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
            tool_plan=[],
            compatibility_contract={
                "surfaces": ["quiz"],
                "implementation_binding": "create_quiz",
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=["reflection-source"],
            source_memory_ids=["memory-source"],
            source_proposal_id="proposal-source",
            quality_score=0.8,
            created_by="operator:seed",
            approved_by="operator:seed",
        )
        related_artifact = SkillArtifact.build(
            name="create_quiz",
            version="0.1.81",
            skill_type="learned",
            scope="quiz",
            status="deprecated",
            description="Overlapping quiz skill package.",
            definition={
                "artifact_kind": "declarative_skill_package",
                "match_rules": {"task_types": ["review", "practice"], "topic_keys": ["linear-systems"]},
                "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 4},
            },
            runtime_directives={"question_count": 5, "feedback_style": "direct"},
            tool_plan=[],
            compatibility_contract={
                "surfaces": ["quiz"],
                "implementation_binding": "create_quiz",
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=["reflection-related"],
            source_memory_ids=["memory-related"],
            source_proposal_id="proposal-related",
            quality_score=0.75,
            created_by="operator:seed",
            approved_by="operator:seed",
        )
        await SkillArtifactRepository(db).create(source_artifact)
        await SkillArtifactRepository(db).create(related_artifact)
        reflection = ReflectionRecord.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=None,
            workflow_run_id=None,
            study_plan_id=None,
            scope="goal",
            target_type="learner_goal",
            target_id=learner_goal_id,
            trigger_source="consecutive_failure_pattern",
            reflection_depth=1,
            dedupe_key=f"merge-skill:{learner_goal_id}",
            aggregation_key=f"merge-skill:{learner_goal_id}",
            duplicate_count=1,
            priority_score=0.8,
            last_duplicate_at=None,
            cooldown_until=None,
            primary_root_cause="knowledge_gap",
            secondary_root_causes=[],
            severity="medium",
            confidence_score=0.8,
            summary="Seeded merge candidate reflection.",
            evidence_summary="Seeded overlapping skill package evidence.",
            recommended_next_step="Merge overlapping quiz skill package coverage.",
            evidence_payload={"source": "api_integration"},
        )
        await ReflectionRecordRepository(db).create(reflection)
        await db.commit()
        return source_artifact, related_artifact, reflection.id


async def _seed_realizable_skill_patch_request(
    *,
    learner_profile_id: str,
    learner_goal_id: str,
) -> tuple[SkillArtifact, ReflectionProposal]:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        source_artifact = SkillArtifact.build(
            name="create_quiz",
            version="0.1.77",
            skill_type="learned",
            scope="quiz",
            status="stable",
            description="Current quiz skill package.",
            definition={
                "artifact_kind": "declarative_skill_package",
                "match_rules": {"task_types": ["practice"], "topic_keys": ["algebra"]},
                "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
            },
            runtime_directives={"question_count": 3, "feedback_style": "guided_correction"},
            tool_plan=[],
            compatibility_contract={
                "surfaces": ["quiz"],
                "implementation_binding": "create_quiz",
                "input_schema_version": "1.0",
                "output_schema_version": "1.0",
                "dynamic_execution": False,
            },
            source_reflection_ids=["reflection-source"],
            source_memory_ids=["memory-source"],
            source_proposal_id="proposal-source",
            quality_score=0.8,
            created_by="operator:seed",
            approved_by="operator:seed",
        )
        await SkillArtifactRepository(db).create(source_artifact)
        reflection = ReflectionRecord.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=None,
            workflow_run_id=None,
            study_plan_id=None,
            scope="goal",
            target_type="learner_goal",
            target_id=learner_goal_id,
            trigger_source="consecutive_failure_pattern",
            reflection_depth=1,
            dedupe_key=f"realize-skill-patch:{learner_goal_id}",
            aggregation_key=f"realize-skill-patch:{learner_goal_id}",
            duplicate_count=1,
            priority_score=0.8,
            last_duplicate_at=None,
            cooldown_until=None,
            primary_root_cause="knowledge_gap",
            secondary_root_causes=[],
            severity="medium",
            confidence_score=0.8,
            summary="Seeded skill patch request reflection.",
            evidence_summary="Seeded API integration evidence.",
            recommended_next_step="Realize governed skill patch request.",
            evidence_payload={"source": "api_integration"},
        )
        await ReflectionRecordRepository(db).create(reflection)
        patch_request = ReflectionProposal.build(
            reflection_record_id=reflection.id,
            learner_goal_id=learner_goal_id,
            proposal_type="skill_patch_request",
            target_scope="quiz",
            priority_score=0.8,
            hypothesis="Curator evidence indicates create_quiz may need a governed skill patch.",
            change_summary="Create a governed patch request for create_quiz on quiz.",
            structured_patch_payload={
                "artifact_id": source_artifact.id,
                "skill_name": source_artifact.name,
                "skill_version": source_artifact.version,
                "scope": source_artifact.scope,
                "surface": source_artifact.scope,
                "recommendation_id": "recommendation-api-1",
                "recommendation_reason_code": "quality_regression",
                "usage_event_ids": ["usage-api-1", "usage-api-2"],
                "related_artifact_ids": [],
                "evidence_snapshot": {"usage_event_ids": ["usage-api-1", "usage-api-2"]},
                "metrics_snapshot": {"negative_usage_rate": 0.5},
            },
            expected_improvement="Route negative skill evidence into sandboxed proposal review before artifact changes.",
            risk_level="medium",
            evidence_snapshot={
                "source": "skill_curator_recommendation",
                "recommendation_id": "recommendation-api-1",
            },
        ).enqueue_sandbox(
            sandbox_run_id="sandbox-patch-api",
        ).start_sandbox(
            sandbox_run_id="sandbox-patch-api",
        ).complete_sandbox(
            sandbox_run_id="sandbox-patch-api",
            evaluation_status="effective",
            evaluation_summary="sandbox:0.15",
        ).approve(
            operator_id="operator:seed",
            reason_code="validated",
            reason_note=None,
        )
        await ReflectionProposalRepository(db).create(patch_request)
        evaluation = ReflectionProposalEvaluation.build(
            proposal_id=patch_request.id,
            comparison_window_size=2,
            baseline_policy_snapshot={"artifact_id": source_artifact.id},
            candidate_policy_snapshot={"usage_event_ids": ["usage-api-1", "usage-api-2"]},
            evaluator_type="rule",
            sandbox_run_id="sandbox-patch-api",
        ).with_result(
            evaluation_status="effective",
            simulated_outcome_summary={"score_delta": 0.15},
            score_delta=0.15,
            sandbox_run_id="sandbox-patch-api",
        )
        await ReflectionProposalEvaluationRepository(db).create(evaluation)
        await db.commit()
        return source_artifact, patch_request


async def _approve_realized_replacement_proposal(proposal_id: str) -> ReflectionProposal:
    from agent_core.api import dependencies as api_dependencies

    session_factory = api_dependencies.get_session_factory()
    async with session_factory() as db:
        proposal_repository = ReflectionProposalRepository(db)
        proposal = await proposal_repository.get_by_id(proposal_id)
        assert proposal is not None

        sandbox_run_id = proposal.latest_sandbox_run_id or f"sandbox-realized-{proposal.id}"
        if proposal.status == "proposed":
            proposal = proposal.enqueue_sandbox(sandbox_run_id=sandbox_run_id)
        if proposal.status == "sandbox_queued":
            proposal = proposal.start_sandbox(sandbox_run_id=sandbox_run_id)
        if proposal.status == "sandbox_running":
            proposal = proposal.complete_sandbox(
                sandbox_run_id=sandbox_run_id,
                evaluation_status="effective",
                evaluation_summary="sandbox:0.20",
            )
        if proposal.status == "sandbox_completed":
            proposal = proposal.approve(
                operator_id="operator:seed",
                reason_code="validated",
                reason_note=None,
            )
        assert proposal.status == "approved"
        assert proposal.evaluation_status == "effective"
        await proposal_repository.update(proposal)

        evaluation_repository = ReflectionProposalEvaluationRepository(db)
        existing_evaluation = await evaluation_repository.get_by_proposal(proposal.id)
        evaluation = ReflectionProposalEvaluation.build(
            proposal_id=proposal.id,
            comparison_window_size=3,
            baseline_policy_snapshot={"source_artifact_id": proposal.evidence_snapshot["source_artifact_id"]},
            candidate_policy_snapshot=proposal.structured_patch_payload,
            evaluator_type="rule",
            sandbox_run_id=sandbox_run_id,
        ).with_result(
            evaluation_status="effective",
            simulated_outcome_summary={"score_delta": 0.2},
            score_delta=0.2,
            sandbox_run_id=sandbox_run_id,
        )
        if existing_evaluation is None:
            await evaluation_repository.create(evaluation)
        else:
            await evaluation_repository.update(
                ReflectionProposalEvaluation(
                    id=existing_evaluation.id,
                    proposal_id=existing_evaluation.proposal_id,
                    evaluation_status=evaluation.evaluation_status,
                    comparison_window_size=existing_evaluation.comparison_window_size,
                    baseline_policy_snapshot=existing_evaluation.baseline_policy_snapshot,
                    candidate_policy_snapshot=existing_evaluation.candidate_policy_snapshot,
                    simulated_outcome_summary=evaluation.simulated_outcome_summary,
                    score_delta=evaluation.score_delta,
                    evaluator_type=existing_evaluation.evaluator_type,
                    sandbox_run_id=evaluation.sandbox_run_id,
                    created_at=existing_evaluation.created_at,
                    updated_at=evaluation.updated_at,
                )
            )
        await db.commit()
        return proposal


def test_session_endpoints_cover_create_list_get_update_and_errors(app_client_factory):
    client = app_client_factory()

    first = client.post("/api/v1/sessions", json={"title": "Algebra", "subject": "Equations"})
    assert first.status_code == 200
    first_payload = first.json()

    second = client.post("/api/v1/sessions", json={"title": "Geometry", "subject": "Triangles"})
    assert second.status_code == 200
    second_payload = second.json()

    listed = client.get("/api/v1/sessions")
    assert listed.status_code == 200
    session_ids = {item["id"] for item in listed.json()}
    assert {first_payload["id"], second_payload["id"]}.issubset(session_ids)

    fetched = client.get(f"/api/v1/sessions/{first_payload['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["subject"] == "Equations"

    updated = client.patch(
        f"/api/v1/sessions/{first_payload['id']}/status",
        json={"status": "archived"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "archived"

    missing = client.get("/api/v1/sessions/missing-session")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    invalid_status = client.patch(
        f"/api/v1/sessions/{first_payload['id']}/status",
        json={"status": "paused"},
    )
    assert invalid_status.status_code == 400
    assert invalid_status.json()["error"]["code"] == "validation_error"


def test_message_endpoints_persist_history_and_validate_errors(app_client_factory):
    client = app_client_factory()
    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    session_id = session_response.json()["id"]

    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
    )
    assert chat_response.status_code == 200
    chat_payload = chat_response.json()
    assert chat_payload["assistant_payload"]["type"] == "explanation"
    assert chat_payload["skill_trace"] == ["explain_concept"]

    hint_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Give me a hint instead.", "mode": "hint"},
    )
    assert hint_response.status_code == 200
    assert hint_response.json()["assistant_payload"]["type"] == "hint"

    history_response = client.get(f"/api/v1/sessions/{session_id}/messages", params={"limit": 2})
    assert history_response.status_code == 200
    history_payload = history_response.json()
    assert history_payload["total"] == 4
    assert len(history_payload["items"]) == 2
    assert history_payload["items"][-1]["role"] == "assistant"
    assert history_payload["next_before_id"] is not None

    paged_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"limit": 2, "before_id": history_payload["next_before_id"]},
    )
    assert paged_response.status_code == 200
    assert len(paged_response.json()["items"]) >= 1

    invalid_cursor = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        params={"before_id": "missing-cursor"},
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["error"]["code"] == "validation_error"

    invalid_mode = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain this.", "mode": "quiz"},
    )
    assert invalid_mode.status_code == 422

    missing_session = client.post(
        "/api/v1/sessions/missing-session/messages",
        json={"content": "Explain this.", "mode": "chat"},
    )
    assert missing_session.status_code == 404


def test_quiz_endpoints_cover_generate_list_detail_and_errors(app_client_factory):
    client = app_client_factory()
    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Probability", "subject": "Distributions"},
    )
    session_id = session_response.json()["id"]

    generated = client.post(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        json={"topic": "Distributions", "difficulty": "easy", "question_count": 2},
    )
    assert generated.status_code == 200
    quiz_payload = generated.json()
    assert quiz_payload["question_count"] == 2
    assert quiz_payload["skill_trace"] == ["create_quiz"]

    listed = client.get(f"/api/v1/sessions/{session_id}/quizzes")
    assert listed.status_code == 200
    assert listed.json()[0]["quiz_id"] == quiz_payload["quiz_id"]

    detail = client.get(f"/api/v1/sessions/{session_id}/quizzes/{quiz_payload['quiz_id']}")
    assert detail.status_code == 200
    assert len(detail.json()["questions"]) == 2

    missing_session = client.get("/api/v1/sessions/missing-session/quizzes")
    assert missing_session.status_code == 404

    missing_quiz = client.get(f"/api/v1/sessions/{session_id}/quizzes/missing-quiz")
    assert missing_quiz.status_code == 404


def test_quiz_generation_consumes_active_runtime_artifact_directives(app_client_factory):
    client = app_client_factory()
    asyncio.run(_seed_active_quiz_runtime_artifact())

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Probability", "subject": "Distributions"},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    generated = client.post(
        f"/api/v1/sessions/{session_id}/quizzes/generate",
        json={"topic": "Distributions", "difficulty": "easy", "question_count": 1},
    )
    assert generated.status_code == 200
    quiz_payload = generated.json()
    assert quiz_payload["question_count"] == 3


def test_profile_access_key_api_returns_key_once_and_rotates_operator_only(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_payload = profile.json()
    profile_id = profile_payload["id"]
    access_key = profile_payload["access_key"]
    assert access_key.startswith("edu_prof_")

    listed = client.get("/api/v1/learner-profiles")
    assert listed.status_code == 401

    listed = client.get("/api/v1/learner-profiles", headers=_operator_headers())
    assert listed.status_code == 200
    assert "access_key" not in listed.json()[0]
    assert "access_key_hash" not in listed.json()[0]

    fetched = client.get(f"/api/v1/learner-profiles/{profile_id}")
    assert fetched.status_code == 401

    fetched = client.get(f"/api/v1/learner-profiles/{profile_id}", headers=_learner_headers(access_key))
    assert fetched.status_code == 200
    assert "access_key" not in fetched.json()
    assert "access_key_hash" not in fetched.json()

    own_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
    )
    assert own_workspace.status_code == 200

    learner_rotate = client.post(
        f"/api/v1/learner-profiles/{profile_id}/access-key/rotate",
        headers=_learner_headers(access_key),
    )
    assert learner_rotate.status_code == 403

    rotated = client.post(
        f"/api/v1/learner-profiles/{profile_id}/access-key/rotate",
        headers=_operator_headers(),
    )
    assert rotated.status_code == 200
    rotated_key = rotated.json()["access_key"]
    assert rotated_key != access_key

    old_key_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
    )
    assert old_key_workspace.status_code == 401

    new_key_workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(rotated_key),
    )
    assert new_key_workspace.status_code == 200


def test_profile_goal_and_autonomy_routes_require_owner_or_operator(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    other_profile_id, other_access_key = _create_profile_with_key(client)
    headers = _learner_headers(access_key)
    other_headers = _learner_headers(other_access_key)

    missing_profile_goals = client.get(f"/api/v1/learner-profiles/{profile_id}/goals")
    assert missing_profile_goals.status_code == 401

    wrong_profile_goals = client.get(f"/api/v1/learner-profiles/{profile_id}/goals", headers=other_headers)
    assert wrong_profile_goals.status_code == 404

    wrong_create_goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=other_headers,
        json={
            "title": "Should not create",
            "subject": "Linear Algebra",
            "target_outcome": "No access",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert wrong_create_goal.status_code == 404

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve matrix exercises",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    missing_goal = client.get(f"/api/v1/goals/{goal_id}")
    assert missing_goal.status_code == 401

    wrong_goal = client.get(f"/api/v1/goals/{goal_id}", headers=other_headers)
    assert wrong_goal.status_code == 404

    operator_goal = client.get(f"/api/v1/goals/{goal_id}", headers=_operator_headers())
    assert operator_goal.status_code == 200
    assert operator_goal.json()["learner_profile_id"] == profile_id

    plan = client.post(
        f"/api/v1/goals/{goal_id}/plans",
        headers=headers,
        json={"trigger_source": "initial"},
    )
    assert plan.status_code == 200
    plan_id = plan.json()["id"]

    missing_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks")
    assert missing_tasks.status_code == 401

    wrong_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=other_headers)
    assert wrong_tasks.status_code == 404

    operator_tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=_operator_headers())
    assert operator_tasks.status_code == 200
    task_id = operator_tasks.json()[0]["id"]

    wrong_plan = client.get(f"/api/v1/plans/{plan_id}", headers=other_headers)
    assert wrong_plan.status_code == 404

    operator_plan = client.get(f"/api/v1/plans/{plan_id}", headers=_operator_headers())
    assert operator_plan.status_code == 200

    wrong_task = client.get(f"/api/v1/tasks/{task_id}", headers=other_headers)
    assert wrong_task.status_code == 404

    operator_task = client.get(f"/api/v1/tasks/{task_id}", headers=_operator_headers())
    assert operator_task.status_code == 200

    wrong_autonomy = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=other_headers)
    assert wrong_autonomy.status_code == 404

    operator_autonomy = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=_operator_headers())
    assert operator_autonomy.status_code == 200
    assert other_profile_id != profile_id


def test_memory_endpoints_are_available(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    other_profile_id, other_access_key = _create_profile_with_key(client)

    knowledge = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert knowledge.status_code == 200
    assert "items" in knowledge.json()

    behavior = client.get(
        "/api/v1/memory/behavior",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "query_text": "I need a hint"},
    )
    assert behavior.status_code == 200
    assert "items" in behavior.json()

    missing_key = client.get(
        "/api/v1/memory/knowledge",
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert missing_key.status_code == 401

    wrong_key = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers("wrong-key"),
        params={"learner_profile_id": profile_id, "query_text": "matrix multiplication"},
    )
    assert wrong_key.status_code == 401

    wrong_profile = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": other_profile_id, "query_text": "matrix multiplication"},
    )
    assert wrong_profile.status_code == 404

    own_other_profile = client.get(
        "/api/v1/memory/knowledge",
        headers=_learner_headers(other_access_key),
        params={"learner_profile_id": other_profile_id, "query_text": "matrix multiplication"},
    )
    assert own_other_profile.status_code == 200

    corpus = client.get(
        "/api/v1/memory/reflection-corpus",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert corpus.status_code == 200
    assert "items" in corpus.json()
    assert "summary" in corpus.json()

    learner_corpus = client.get(
        "/api/v1/memory/reflection-corpus",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id},
    )
    assert learner_corpus.status_code == 403

    summary = client.get(
        "/api/v1/memory/governance-summary",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert summary.status_code == 200
    assert "knowledge_total" in summary.json()
    assert "behavior_total" in summary.json()

    interpretation = client.get(
        "/api/v1/memory/interpretation",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert interpretation.status_code == 200
    assert "facts" in interpretation.json()
    assert "recommended_constraints" in interpretation.json()

    conflicts = client.get(
        "/api/v1/memory/conflicts",
        headers=_operator_headers(),
        params={"learner_profile_id": profile_id},
    )
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)


def test_memory_operator_endpoints_cover_detail_suppress_restore_and_annotation(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Linear Algebra", "subject": "Matrices"},
    )
    session_id = session_response.json()["id"]
    message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "I am confused about matrix multiplication.", "mode": "chat"},
    )
    assert message_response.status_code == 200

    learner_profile_id = client.get(f"/api/v1/sessions/{session_id}").json()["learner_profile_id"]

    unauthorized = client.post(
        "/api/v1/memory/knowledge/missing/suppress",
        json={"reason_code": "manual_block", "note": "bad memory"},
    )
    assert unauthorized.status_code == 403

    from agent_core.api import dependencies as api_dependencies
    from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
    import asyncio

    async def seed_memory_direct() -> str:
        session_factory = api_dependencies.get_session_factory()
        source_message_id = message_response.json()["user_message_id"]
        async with session_factory() as db:
            service = api_dependencies.get_memory_service(db)
            materialization_service = LongTermMemoryMaterializationService(service)
            memory_events = await service.record_learning_memories(
                session_id=session_id,
                learner_profile_id=learner_profile_id,
                learner_message="I am confused about matrix multiplication.",
                assistant_message="Matrix multiplication combines rows and columns.",
                source_message_id=source_message_id,
                mode="chat",
                subject="Matrices",
                session_title="Linear Algebra",
            )
            result = await materialization_service.materialize_from_chat_turn(
                session_id=session_id,
                learner_profile_id=learner_profile_id,
                learner_goal_id=None,
                learner_message="I am confused about matrix multiplication.",
                assistant_message="Matrix multiplication combines rows and columns.",
                source_message_id=source_message_id,
                mode="chat",
                subject="Matrices",
                session_title="Linear Algebra",
                memory_events=memory_events,
                persist_embeddings=True,
            )
            await db.commit()
            return result.knowledge[0].memory.id

    loop = asyncio.new_event_loop()
    try:
        knowledge_id = loop.run_until_complete(seed_memory_direct())
    finally:
        loop.close()

    detail = client.get(f"/api/v1/memory/knowledge/{knowledge_id}", headers=_operator_headers())
    assert detail.status_code == 200
    assert detail.json()["status"] == "candidate"

    rotated = client.post(
        f"/api/v1/learner-profiles/{learner_profile_id}/access-key/rotate",
        headers=_operator_headers(),
    )
    assert rotated.status_code == 200
    learner_detail = client.get(
        f"/api/v1/memory/knowledge/{knowledge_id}",
        headers=_learner_headers(rotated.json()["access_key"]),
    )
    assert learner_detail.status_code == 200
    assert learner_detail.json()["details"] is None
    assert learner_detail.json()["source_event_ids"] == []
    assert learner_detail.json()["source_memory_ids"] == []
    assert learner_detail.json()["provenance_source_id"] is None
    assert learner_detail.json()["scope_ref"] == {}
    assert learner_detail.json()["promotion_rationale"] is None

    other_profile_id, other_access_key = _create_profile_with_key(client)
    other_detail = client.get(
        f"/api/v1/memory/knowledge/{knowledge_id}",
        headers=_learner_headers(other_access_key),
    )
    assert other_profile_id != learner_profile_id
    assert other_detail.status_code == 404

    suppressed = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/suppress",
        headers=_operator_headers(),
        json={"reason_code": "manual_block", "note": "Needs review"},
    )
    assert suppressed.status_code == 200
    assert suppressed.json()["status"] == "suppressed"

    annotation = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/annotate",
        headers=_operator_headers(),
        json={"annotation_code": "promotion_blocker", "note": "Reviewed by operator"},
    )
    assert annotation.status_code == 200
    assert annotation.json()["annotation_code"] == "promotion_blocker"

    annotations = client.get(f"/api/v1/memory/knowledge/{knowledge_id}/annotations", headers=_operator_headers())
    assert annotations.status_code == 200
    assert len(annotations.json()) == 1

    restored = client.post(
        f"/api/v1/memory/knowledge/{knowledge_id}/restore",
        headers=_operator_headers(),
        json={"restore_to_status": "active", "reason": "Approved"},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"


def test_reflection_endpoints_cover_goal_task_and_detail(app_client_factory):
    client = app_client_factory()

    profile_response = client.post("/api/v1/learner-profiles", json={})
    assert profile_response.status_code == 200
    profile_id = profile_response.json()["id"]
    access_key = profile_response.json()["access_key"]
    headers = _learner_headers(access_key)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    plan_response = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert plan_response.status_code == 200

    tasks_response = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_response.status_code == 200
    task_id = tasks_response.json()[0]["id"]

    execute_response = client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
    assert execute_response.status_code == 200

    failed_response = client.patch(
        f"/api/v1/tasks/{task_id}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Still confused"},
    )
    assert failed_response.status_code == 200
    _run_autonomy_worker_once()

    goal_reflections = client.get(f"/api/v1/goals/{goal_id}/reflections", headers=headers)
    assert goal_reflections.status_code == 200
    assert goal_reflections.json()["total"] >= 1

    task_reflections = client.get(f"/api/v1/tasks/{task_id}/reflections", headers=headers)
    assert task_reflections.status_code == 200
    assert task_reflections.json()["total"] >= 1

    reflection_id = task_reflections.json()["items"][0]["id"]
    detail = client.get(f"/api/v1/reflections/{reflection_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == reflection_id
    assert "actions" in detail.json()


def test_reflective_memories_route_requires_owner_and_returns_redacted_shape(app_client_factory):
    client = app_client_factory()
    profile_id, access_key = _create_profile_with_key(client)
    _, other_access_key = _create_profile_with_key(client)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve matrix exercises",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    from agent_core.api import dependencies as api_dependencies
    from agent_core.domain.entities.reflection import ReflectionRecord
    from agent_core.domain.entities.reflection_v2 import ReflectiveMemory
    from agent_core.infrastructure.db.repositories import ReflectionRecordRepository, ReflectiveMemoryRepository
    import asyncio

    async def seed_reflective_memory() -> None:
        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            reflection = ReflectionRecord.build(
                learner_profile_id=profile_id,
                learner_goal_id=goal_id,
                daily_task_id=None,
                workflow_run_id=None,
                study_plan_id=None,
                scope="goal",
                target_type="learner_goal",
                target_id=goal_id,
                trigger_source="task_failed",
                reflection_depth=1,
                dedupe_key=f"test-reflective-memory:{goal_id}",
                aggregation_key=f"test-reflective-memory:{goal_id}",
                duplicate_count=0,
                priority_score=0.7,
                last_duplicate_at=None,
                cooldown_until=None,
                primary_root_cause="knowledge_gap",
                secondary_root_causes=[],
                severity="medium",
                confidence_score=0.8,
                summary="Learner needs more worked examples.",
                evidence_summary="Internal reflection evidence.",
                recommended_next_step="Add guided practice.",
                evidence_payload={"internal": "evidence"},
            )
            await ReflectionRecordRepository(db).create(reflection)
            await ReflectiveMemoryRepository(db).create(
                ReflectiveMemory.build(
                    learner_profile_id=profile_id,
                    learner_goal_id=goal_id,
                    reflection_record_id=reflection.id,
                    memory_key=f"goal:{goal_id}:strategy:knowledge_gap",
                    title="Guided practice helps",
                    summary="Use guided matrix practice.",
                    details="Internal reflection details should not be returned.",
                    memory_level="pattern",
                    importance_score=0.7,
                    confidence_score=0.8,
                    freshness_score=1.0,
                    evidence_count=1,
                    source_reflection_ids=[reflection.id],
                    source_action_ids=["action-1"],
                    tags=["knowledge_gap"],
                    status="active",
                )
            )
            await db.commit()

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed_reflective_memory())
    finally:
        loop.close()

    missing_key = client.get(f"/api/v1/goals/{goal_id}/reflective-memories")
    assert missing_key.status_code == 401

    wrong_key = client.get(
        f"/api/v1/goals/{goal_id}/reflective-memories",
        headers=_learner_headers(other_access_key),
    )
    assert wrong_key.status_code == 404

    response = client.get(
        f"/api/v1/goals/{goal_id}/reflective-memories",
        headers=_learner_headers(access_key),
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["summary"] == "Use guided matrix practice."
    assert "details" not in payload[0]
    assert "reflection_record_id" not in payload[0]
    assert "source_reflection_ids" not in payload[0]
    assert "source_action_ids" not in payload[0]


def test_reflection_proposal_sandbox_and_approval_endpoints(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})

    profile_response = client.post("/api/v1/learner-profiles", json={})
    assert profile_response.status_code == 200
    profile_id = profile_response.json()["id"]
    access_key = profile_response.json()["access_key"]
    headers = _learner_headers(access_key)

    goal_response = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal_response.status_code == 200
    goal_id = goal_response.json()["id"]

    plan_response = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert plan_response.status_code == 200

    tasks_response = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_response.status_code == 200
    task_payload = tasks_response.json()[0]
    task_id = task_payload["id"]
    task_topic = task_payload["topic_focus"]

    execute_response = client.post(f"/api/v1/tasks/{task_id}/execute", headers=headers)
    assert execute_response.status_code == 200

    failed_response = client.patch(
        f"/api/v1/tasks/{task_id}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Still confused"},
    )
    assert failed_response.status_code == 200
    _run_autonomy_worker_once()

    reflections = client.get(f"/api/v1/tasks/{task_id}/reflections", headers=headers)
    assert reflections.status_code == 200
    reflection_id = reflections.json()["items"][0]["id"]

    proposals = client.get(f"/api/v1/reflections/{reflection_id}/proposals", headers=headers)
    assert proposals.status_code == 200
    assert len(proposals.json()) >= 1
    skill_package_payload = next(
        (
            item
            for item in proposals.json()
            if item["proposal_type"] == "skill_package" and item["activation_surface"] in {"chat", "hint"}
        ),
        None,
    )
    proposal_payload = skill_package_payload or proposals.json()[0]
    proposal_id = proposal_payload["id"]

    unauthorized = client.post(
        f"/api/v1/proposals/{proposal_id}/sandbox",
        json={"reason_code": "queue", "reason_note": "Run sandbox"},
    )
    assert unauthorized.status_code == 403

    queued = client.post(
        f"/api/v1/proposals/{proposal_id}/sandbox",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "queue", "reason_note": "Run sandbox"},
    )
    assert queued.status_code == 200
    assert queued.json()["status"] in {"sandbox_queued", "sandbox_running", "sandbox_completed"}

    _run_autonomy_worker_once()

    proposal_detail = client.get(
        f"/api/v1/proposals/{proposal_id}",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert proposal_detail.status_code == 200
    proposal_payload = proposal_detail.json()
    assert proposal_payload["status"] == "sandbox_completed"
    assert proposal_payload["latest_sandbox_run_id"] is not None
    assert "auto_sandbox_eligible" in proposal_payload
    assert "activation_surface" in proposal_payload

    learner_proposal_detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers)
    assert learner_proposal_detail.status_code == 200

    missing_proposal_key = client.get(f"/api/v1/proposals/{proposal_id}")
    assert missing_proposal_key.status_code == 401

    sandbox_runs = client.get(
        f"/api/v1/proposals/{proposal_id}/sandbox-runs",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert sandbox_runs.status_code == 200
    assert len(sandbox_runs.json()) >= 1

    evaluation = client.get(
        f"/api/v1/proposals/{proposal_id}/evaluation",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert evaluation.status_code == 200
    assert evaluation.json()["proposal_id"] == proposal_id

    approved = client.post(
        f"/api/v1/proposals/{proposal_id}/approve",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "validated", "reason_note": "Sandbox passed"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    candidate_unauthorized = client.post(
        "/api/v1/skill-artifacts/from-reflection-proposal",
        json={"proposal_id": proposal_id},
    )
    assert candidate_unauthorized.status_code == 403

    candidate = client.post(
        "/api/v1/skill-artifacts/from-reflection-proposal",
        headers={"X-Operator-Key": "secret-operator"},
        json={"proposal_id": proposal_id},
    )
    staged_payload = None
    if approved.json()["proposal_type"] == "skill_package" and evaluation.json()["evaluation_status"] == "effective":
        assert candidate.status_code == 200
        candidate_payload = candidate.json()
        assert candidate_payload["status"] == "candidate"
        assert candidate_payload["source_proposal_id"] == proposal_id
        assert candidate_payload["source_reflection_ids"] == [reflection_id]
        assert candidate_payload["version"] == "0.1.0"
        candidate_repeat = client.post(
            "/api/v1/skill-artifacts/from-reflection-proposal",
            headers={"X-Operator-Key": "secret-operator"},
            json={"proposal_id": proposal_id},
        )
        assert candidate_repeat.status_code == 200
        assert candidate_repeat.json()["id"] == candidate_payload["id"]
        stage_unauthorized = client.post(
            f"/api/v1/skill-artifacts/{candidate_payload['id']}/stage",
            json={"reason_code": "reviewed", "reason_note": "Operator reviewed candidate"},
        )
        assert stage_unauthorized.status_code == 403

        staged = client.post(
            f"/api/v1/skill-artifacts/{candidate_payload['id']}/stage",
            headers={"X-Operator-Key": "secret-operator"},
            json={"reason_code": "reviewed", "reason_note": "Operator reviewed candidate"},
        )
        assert staged.status_code == 200
        staged_payload = staged.json()
        assert staged_payload["id"] == candidate_payload["id"]
        assert staged_payload["status"] == "staged"
        assert staged_payload["version"] == candidate_payload["version"]
        assert staged_payload["approved_by"] is None
        assert staged_payload["approved_at"] is None

        staged_resolution = client.get(
            "/api/v1/skill-resolution",
            headers={"X-Operator-Key": "secret-operator"},
            params={"skill_name": staged_payload["name"], "surface": staged_payload["scope"]},
        )
        assert staged_resolution.status_code == 200
        assert staged_resolution.json()["resolver_status"] == "missing_artifact"

        staged_repeat = client.post(
            f"/api/v1/skill-artifacts/{candidate_payload['id']}/stage",
            headers={"X-Operator-Key": "secret-operator"},
            json={"reason_code": "reviewed", "reason_note": "Operator reviewed candidate"},
        )
        assert staged_repeat.status_code == 200
        assert staged_repeat.json()["id"] == staged_payload["id"]
        assert staged_repeat.json()["version"] == staged_payload["version"]
    else:
        assert candidate.status_code == 400

    activated = client.post(
        f"/api/v1/proposals/{proposal_id}/activate",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "activate", "reason_note": "Start staged rollout"},
    )
    assert activated.status_code == 200
    assert activated.json()["status"] == "staged"
    rollout_id = activated.json()["id"]

    rollout_list = client.get(
        f"/api/v1/proposals/{proposal_id}/rollouts",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert rollout_list.status_code == 200
    assert len(rollout_list.json()) == 1

    rollout_session = client.post(
        "/api/v1/sessions",
        json={
            "learner_profile_id": profile_id,
            "learner_goal_id": goal_id,
            "title": "Matrices rollout check",
            "subject": task_topic,
        },
    )
    assert rollout_session.status_code == 200
    rollout_session_id = rollout_session.json()["id"]

    rollout_mode = proposal_payload["activation_surface"]
    for index in range(3):
        message_payload = {
            "content": f"Rollout check turn {index + 1}.",
            "mode": rollout_mode,
        }
        if rollout_mode == "hint":
            message_payload["question_prompt"] = "What is the next step in matrix multiplication?"
        rollout_message = client.post(
            f"/api/v1/sessions/{rollout_session_id}/messages",
            json=message_payload,
        )
        assert rollout_message.status_code == 200
        if rollout_mode == "hint":
            assert rollout_message.json()["assistant_payload"]["hint_level"] in {"conceptual", "scaffolded", "targeted"}

    observed = client.post(
        f"/api/v1/rollouts/{rollout_id}/observe",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "manual_observe", "reason_note": "Rollout usage collected"},
    )
    assert observed.status_code == 200
    assert observed.json()["recommendation"] == "promote"

    observations = client.get(
        f"/api/v1/rollouts/{rollout_id}/observations",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert observations.status_code == 200
    assert len(observations.json()) >= 1
    assert observations.json()[0]["recommendation"] == "promote"

    promoted = client.post(
        f"/api/v1/rollouts/{rollout_id}/promote",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "promote", "reason_note": "Signals look stable"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "rolled_out"
    if approved.json()["proposal_type"] != "skill_package":
        rolled_back = client.post(
            f"/api/v1/rollouts/{rollout_id}/rollback",
            headers={"X-Operator-Key": "secret-operator"},
            json={"reason_code": "rollback", "reason_note": "End staged rollout"},
        )
        assert rolled_back.status_code == 200
        assert rolled_back.json()["status"] == "rolled_back"
        return
    assert staged_payload is not None

    activate_unauthorized = client.post(
        f"/api/v1/skill-artifacts/{staged_payload['id']}/activate",
        json={"reason_code": "rollout_promoted", "reason_note": "Promote staged artifact"},
    )
    assert activate_unauthorized.status_code == 403

    artifact_activation = client.post(
        f"/api/v1/skill-artifacts/{staged_payload['id']}/activate",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "rollout_promoted", "reason_note": "Promote staged artifact"},
    )
    assert artifact_activation.status_code == 200
    activated_artifact_payload = artifact_activation.json()
    assert activated_artifact_payload["id"] == staged_payload["id"]
    assert activated_artifact_payload["status"] == "active"
    assert activated_artifact_payload["version"] == staged_payload["version"]
    assert activated_artifact_payload["approved_by"] == _operator_actor_id()
    assert activated_artifact_payload["approved_at"] is not None

    active_resolution = client.get(
        "/api/v1/skill-resolution",
        headers={"X-Operator-Key": "secret-operator"},
        params={
            "skill_name": activated_artifact_payload["name"],
            "surface": activated_artifact_payload["scope"],
        },
    )
    assert active_resolution.status_code == 200
    assert active_resolution.json()["resolver_status"] == "resolved"
    assert active_resolution.json()["artifact_id"] == activated_artifact_payload["id"]

    artifact_activation_repeat = client.post(
        f"/api/v1/skill-artifacts/{staged_payload['id']}/activate",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "rollout_promoted", "reason_note": "Promote staged artifact"},
    )
    assert artifact_activation_repeat.status_code == 200
    assert artifact_activation_repeat.json()["id"] == staged_payload["id"]
    assert artifact_activation_repeat.json()["version"] == staged_payload["version"]

    stabilize_unauthorized = client.post(
        f"/api/v1/skill-artifacts/{activated_artifact_payload['id']}/stabilize",
        json={"reason_code": "stable_evidence", "reason_note": "Promote active artifact to stable"},
    )
    assert stabilize_unauthorized.status_code == 403

    for index in range(5):
        message_payload = {
            "content": f"Stable evidence turn {index + 1}.",
            "mode": rollout_mode,
        }
        if rollout_mode == "hint":
            message_payload["question_prompt"] = "What is the next step in matrix multiplication?"
        stable_message = client.post(
            f"/api/v1/sessions/{rollout_session_id}/messages",
            json=message_payload,
        )
        assert stable_message.status_code == 200

    for _ in range(2):
        stable_observed = client.post(
            f"/api/v1/rollouts/{rollout_id}/observe",
            headers={"X-Operator-Key": "secret-operator"},
            json={"reason_code": "manual_observe", "reason_note": "Stable artifact evidence collected"},
        )
        assert stable_observed.status_code == 200
        assert stable_observed.json()["recommendation"] == "promote"

    stable_artifact = client.post(
        f"/api/v1/skill-artifacts/{activated_artifact_payload['id']}/stabilize",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "stable_evidence", "reason_note": "Promote active artifact to stable"},
    )
    assert stable_artifact.status_code == 200
    stable_artifact_payload = stable_artifact.json()
    assert stable_artifact_payload["id"] == activated_artifact_payload["id"]
    assert stable_artifact_payload["status"] == "stable"
    assert stable_artifact_payload["approved_by"] == _operator_actor_id()
    assert stable_artifact_payload["approved_at"] is not None

    stable_resolution = client.get(
        "/api/v1/skill-resolution",
        headers={"X-Operator-Key": "secret-operator"},
        params={
            "skill_name": stable_artifact_payload["name"],
            "surface": stable_artifact_payload["scope"],
        },
    )
    assert stable_resolution.status_code == 200
    assert stable_resolution.json()["resolver_status"] == "resolved"
    assert stable_resolution.json()["artifact_id"] == stable_artifact_payload["id"]
    assert stable_resolution.json()["artifact_status"] == "stable"

    rolled_back = client.post(
        f"/api/v1/rollouts/{rollout_id}/rollback",
        headers={"X-Operator-Key": "secret-operator"},
        json={"reason_code": "rollback", "reason_note": "End staged rollout"},
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json()["status"] == "rolled_back"

    deactivated_artifact = client.get(
        f"/api/v1/skill-artifacts/{stable_artifact_payload['id']}",
        headers={"X-Operator-Key": "secret-operator"},
    )
    assert deactivated_artifact.status_code == 200
    assert deactivated_artifact.json()["id"] == stable_artifact_payload["id"]
    assert deactivated_artifact.json()["status"] == "deprecated"
    assert deactivated_artifact.json()["deprecated_by"] == _operator_actor_id()
    assert deactivated_artifact.json()["deprecated_at"] is not None

    deactivated_resolution = client.get(
        "/api/v1/skill-resolution",
        headers={"X-Operator-Key": "secret-operator"},
        params={
            "skill_name": stable_artifact_payload["name"],
            "surface": stable_artifact_payload["scope"],
        },
    )
    assert deactivated_resolution.status_code == 200
    assert deactivated_resolution.json()["resolver_status"] == "missing_artifact"
    assert deactivated_resolution.json()["artifact_id"] is None


def test_workspace_summary_and_memory_browse_endpoints(app_client_factory):
    client = app_client_factory()
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    other_profile_id, other_access_key = _create_profile_with_key(client)

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Linear Algebra",
            "subject": "Matrices",
            "target_outcome": "Understand matrix operations.",
            "baseline_note": "Needs structure.",
            "deadline_date": (date.today() + timedelta(days=30)).isoformat(),
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=_learner_headers(access_key), json={"trigger_source": "initial"})
    assert plan.status_code == 200

    session = client.post(
        "/api/v1/sessions",
        json={
            "learner_profile_id": profile_id,
            "learner_goal_id": goal_id,
            "title": "Matrices intro",
            "subject": "Matrices",
        },
    )
    assert session.status_code == 200
    session_id = session.json()["id"]

    message = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain matrix multiplication simply.", "mode": "chat"},
    )
    assert message.status_code == 200

    missing_workspace_key = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        params={"goal_id": goal_id},
    )
    assert missing_workspace_key.status_code == 401

    wrong_workspace_key = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(other_access_key),
        params={"goal_id": goal_id},
    )
    assert other_profile_id != profile_id
    assert wrong_workspace_key.status_code == 404

    workspace = client.get(
        f"/api/v1/learner-profiles/{profile_id}/workspace",
        headers=_learner_headers(access_key),
        params={"goal_id": goal_id},
    )
    assert workspace.status_code == 200
    workspace_payload = workspace.json()
    assert workspace_payload["learner_goal"]["id"] == goal_id
    assert workspace_payload["active_plan"] is not None
    assert len(workspace_payload["today_tasks"]) >= 1
    assert workspace_payload["memory_summary"]["knowledge_count"] >= 1
    assert workspace_payload["memory_summary"]["behavior_count"] >= 1
    assert any(item["id"] == session_id for item in workspace_payload["recent_sessions"])

    filtered_tasks = client.get(
        f"/api/v1/goals/{goal_id}/tasks",
        headers=_learner_headers(access_key),
        params={
            "status": ["pending"],
            "scheduled_to": (date.today() + timedelta(days=14)).isoformat(),
        },
    )
    assert filtered_tasks.status_code == 200
    assert len(filtered_tasks.json()) >= 1
    assert all(item["status"] == "pending" for item in filtered_tasks.json())

    knowledge_browse = client.get(
        "/api/v1/memory/knowledge/browse",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "learner_goal_id": goal_id, "limit": 5, "offset": 0},
    )
    assert knowledge_browse.status_code == 200
    assert knowledge_browse.json()["total"] >= 1
    assert len(knowledge_browse.json()["items"]) >= 1

    behavior_browse = client.get(
        "/api/v1/memory/behavior/browse",
        headers=_learner_headers(access_key),
        params={"learner_profile_id": profile_id, "learner_goal_id": goal_id, "limit": 5, "offset": 0},
    )
    assert behavior_browse.status_code == 200
    assert behavior_browse.json()["total"] >= 1


def test_skills_readyz_and_metrics_endpoints(app_client_factory):
    client = app_client_factory(
        env_overrides={
            "AGENT_EDU_METRICS_ENABLED": "1",
            "AGENT_EDU_OPERATOR_API_KEY": "secret-operator",
        }
    )

    skills = client.get("/api/v1/skills")
    assert skills.status_code == 401

    skills = client.get("/api/v1/skills", headers=_operator_headers())
    assert skills.status_code == 200
    assert len(skills.json()) >= 1

    _, access_key = _create_profile_with_key(client)
    learner_skills = client.get("/api/v1/skills", headers=_learner_headers(access_key))
    assert learner_skills.status_code == 200
    assert len(learner_skills.json()) >= 1

    healthz = client.get("/healthz")
    assert healthz.status_code == 200
    assert healthz.json() == {"status": "ok"}

    readyz = client.get("/readyz")
    assert readyz.status_code == 200
    assert readyz.json() == {"status": "ready"}

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Calculus", "subject": "Derivatives"},
    )
    session_id = session_response.json()["id"]
    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain derivatives simply.", "mode": "chat"},
    )
    assert chat_response.status_code == 200

    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "agent_edu_http_requests_total" in metrics.text
    assert 'route="/api/v1/sessions/{session_id}/messages"' in metrics.text
    assert "agent_edu_llm_operations_total" in metrics.text
    assert "agent_edu_audit_writes_total" in metrics.text
    assert "agent_edu_skill_resolutions_total" in metrics.text
    assert "agent_edu_skill_usage_events_total" in metrics.text
    assert "agent_edu_skill_artifacts" in metrics.text
    assert "agent_edu_skill_curator_pending_recommendations" in metrics.text


def test_replace_skill_artifact_route_supersedes_current_selectable(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Master quiz replacement",
            "subject": "Algebra",
            "target_outcome": "Practice with better generated quizzes",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    current, replacement = asyncio.run(
        _seed_replaceable_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )

    unauthorized = client.post(
        f"/api/v1/skill-artifacts/{replacement.id}/replace",
        json={"reason_code": "superseded", "reason_note": "Replace current quiz package."},
    )
    assert unauthorized.status_code == 403

    replaced = client.post(
        f"/api/v1/skill-artifacts/{replacement.id}/replace",
        headers=_operator_headers(),
        json={"reason_code": "superseded", "reason_note": "Replace current quiz package."},
    )
    assert replaced.status_code == 200
    replacement_payload = replaced.json()
    assert replacement_payload["id"] == replacement.id
    assert replacement_payload["status"] == "active"
    assert replacement_payload["lineage_id"] == current.lineage_id
    assert replacement_payload["parent_artifact_id"] == current.id
    assert replacement_payload["supersedes_artifact_id"] == current.id
    assert replacement_payload["approved_by"] == _operator_actor_id()
    assert replacement_payload["approved_at"] is not None

    current_response = client.get(f"/api/v1/skill-artifacts/{current.id}", headers=_operator_headers())
    assert current_response.status_code == 200
    current_payload = current_response.json()
    assert current_payload["status"] == "deprecated"
    assert current_payload["deprecated_by"] == _operator_actor_id()
    assert current_payload["deprecated_at"] is not None

    resolution = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "create_quiz", "surface": "quiz"},
    )
    assert resolution.status_code == 200
    assert resolution.json()["resolver_status"] == "resolved"
    assert resolution.json()["artifact_id"] == replacement.id
    assert resolution.json()["artifact_status"] == "active"

    repeated = client.post(
        f"/api/v1/skill-artifacts/{replacement.id}/replace",
        headers=_operator_headers(),
        json={"reason_code": "superseded", "reason_note": "Repeat replacement."},
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == replacement.id

    event_types = asyncio.run(_audit_event_types())
    assert "skill.artifact.deactivated" in event_types
    assert "skill.artifact.replaced" in event_types
    assert "skill.artifact.replace_reused" in event_types


def test_skill_replacement_readiness_route_reports_governed_replace_readiness(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Check governed replacement readiness",
            "subject": "Algebra",
            "target_outcome": "Review staged replacement evidence before replace",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    current, replacement = asyncio.run(
        _seed_replaceable_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )

    unauthorized = client.get(f"/api/v1/skill-artifacts/{replacement.id}/replacement-readiness")
    assert unauthorized.status_code == 403

    readiness = client.get(
        f"/api/v1/skill-artifacts/{replacement.id}/replacement-readiness",
        headers=_operator_headers(),
    )
    assert readiness.status_code == 200
    payload = readiness.json()
    assert payload["artifact_id"] == replacement.id
    assert payload["proposal_source"] == "skill_patch_request_realization"
    assert payload["recommended_action"] == "replace_selectable"
    assert payload["source_anchor"]["source_artifact_id"] == current.id
    assert payload["activate_readiness"]["status"] == "blocked"
    assert "current_selectable_conflict" in payload["activate_readiness"]["reason_codes"]
    assert payload["replace_readiness"]["status"] == "ready"
    assert payload["thresholds"]["successful_usage_min"] == 3
    assert payload["usage_evidence"]["successful_count"] == 3


def test_suppress_restore_skill_artifact_routes_gate_runtime_resolution(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Master quiz suppression",
            "subject": "Algebra",
            "target_outcome": "Practice with governed quiz packages",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    current, _replacement = asyncio.run(
        _seed_replaceable_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )

    unauthorized = client.post(
        f"/api/v1/skill-artifacts/{current.id}/suppress",
        json={"reason_code": "safety_risk", "reason_note": "Investigate package."},
    )
    assert unauthorized.status_code == 403

    suppressed = client.post(
        f"/api/v1/skill-artifacts/{current.id}/suppress",
        headers=_operator_headers(),
        json={"reason_code": "safety_risk", "reason_note": "Investigate package."},
    )
    assert suppressed.status_code == 200
    suppressed_payload = suppressed.json()
    assert suppressed_payload["id"] == current.id
    assert suppressed_payload["status"] == "suppressed"
    assert suppressed_payload["suppressed_reason_code"] == "safety_risk"
    assert suppressed_payload["suppressed_reason_note"] == "Investigate package."
    assert suppressed_payload["suppressed_by"] == _operator_actor_id()
    assert suppressed_payload["suppressed_at"] is not None
    assert suppressed_payload["suppressed_previous_status"] == "stable"

    blocked_resolution = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "create_quiz", "surface": "quiz"},
    )
    assert blocked_resolution.status_code == 200
    assert blocked_resolution.json()["resolver_status"] == "blocked"
    assert blocked_resolution.json()["selection_reason"] == "suppressed_artifact"
    assert blocked_resolution.json()["artifact_id"] == current.id
    assert blocked_resolution.json()["artifact_status"] == "suppressed"

    restored = client.post(
        f"/api/v1/skill-artifacts/{current.id}/restore",
        headers=_operator_headers(),
        json={"reason_code": "risk_mitigated", "reason_note": "Investigation cleared."},
    )
    assert restored.status_code == 200
    restored_payload = restored.json()
    assert restored_payload["id"] == current.id
    assert restored_payload["status"] == "stable"
    assert restored_payload["suppressed_reason_code"] is None
    assert restored_payload["suppressed_reason_note"] is None
    assert restored_payload["suppressed_by"] is None
    assert restored_payload["suppressed_at"] is None
    assert restored_payload["suppressed_previous_status"] is None

    resolved = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "create_quiz", "surface": "quiz"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolver_status"] == "resolved"
    assert resolved.json()["artifact_id"] == current.id
    assert resolved.json()["artifact_status"] == "stable"

    repeated_restore = client.post(
        f"/api/v1/skill-artifacts/{current.id}/restore",
        headers=_operator_headers(),
        json={"reason_code": "operator_restore", "reason_note": "Repeat restore."},
    )
    assert repeated_restore.status_code == 200
    assert repeated_restore.json()["id"] == current.id
    assert repeated_restore.json()["status"] == "stable"

    event_types = asyncio.run(_audit_event_types())
    assert "skill.artifact.suppressed" in event_types
    assert "skill.resolution.blocked" not in event_types
    assert "skill.artifact.restored" in event_types
    assert "skill.artifact.restore_reused" in event_types


def test_archive_skill_artifact_route_archives_deprecated_artifact(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Master quiz archival",
            "subject": "Algebra",
            "target_outcome": "Retire stale quiz packages",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    current, _replacement = asyncio.run(
        _seed_replaceable_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )

    unauthorized = client.post(
        f"/api/v1/skill-artifacts/{current.id}/archive",
        json={"reason_code": "stale_deprecated", "reason_note": "Archive stale package."},
    )
    assert unauthorized.status_code == 403

    rejected_selectable = client.post(
        f"/api/v1/skill-artifacts/{current.id}/archive",
        headers=_operator_headers(),
        json={"reason_code": "stale_deprecated", "reason_note": "Not deprecated yet."},
    )
    assert rejected_selectable.status_code == 400

    deactivated = client.post(
        f"/api/v1/skill-artifacts/{current.id}/deactivate",
        headers=_operator_headers(),
        json={"reason_code": "operator_request", "reason_note": "Prepare archive."},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "deprecated"

    archived = client.post(
        f"/api/v1/skill-artifacts/{current.id}/archive",
        headers=_operator_headers(),
        json={"reason_code": "stale_deprecated", "reason_note": "Archive stale package."},
    )
    assert archived.status_code == 200
    archived_payload = archived.json()
    assert archived_payload["id"] == current.id
    assert archived_payload["status"] == "archived"
    assert archived_payload["lineage_id"] == current.lineage_id
    assert archived_payload["deprecated_by"] == _operator_actor_id()
    assert archived_payload["deprecated_at"] is not None

    resolution = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "create_quiz", "surface": "quiz"},
    )
    assert resolution.status_code == 200
    assert resolution.json()["resolver_status"] == "missing_artifact"
    assert resolution.json()["artifact_id"] is None

    repeated = client.post(
        f"/api/v1/skill-artifacts/{current.id}/archive",
        headers=_operator_headers(),
        json={"reason_code": "cleanup", "reason_note": "Repeat archive."},
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == current.id
    assert repeated.json()["status"] == "archived"

    restore_archived = client.post(
        f"/api/v1/skill-artifacts/{current.id}/restore",
        headers=_operator_headers(),
        json={"reason_code": "operator_restore", "reason_note": "Cannot restore archived."},
    )
    assert restore_archived.status_code == 400

    event_types = asyncio.run(_audit_event_types())
    assert "skill.artifact.archived" in event_types
    assert "skill.artifact.archive_reused" in event_types


def test_skill_curator_recommendation_operator_routes_cover_list_get_accept_and_dismiss(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    recommendation_id = asyncio.run(
        _seed_skill_curator_recommendation(
            recommendation_type="rollback_review",
            recommended_action="none",
            reason_code="rollback_recommended",
        )
    )
    dismiss_recommendation_id = asyncio.run(
        _seed_skill_curator_recommendation(
            recommendation_type="flag_for_review",
            recommended_action="none",
            reason_code="manual_review",
        )
    )

    unauthorized_list = client.get("/api/v1/skill-curator-recommendations")
    assert unauthorized_list.status_code == 403

    no_create = client.post(
        "/api/v1/skill-curator-recommendations",
        headers=_operator_headers(),
        json={"recommendation_type": "patch_needed"},
    )
    assert no_create.status_code == 405

    listed = client.get(
        "/api/v1/skill-curator-recommendations",
        headers=_operator_headers(),
        params={
            "status": "pending",
            "recommendation_type": "rollback_review",
            "recommended_action": "none",
            "skill_name": "create_quiz",
            "scope": "quiz",
            "surface": "quiz",
        },
    )
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert [item["id"] for item in listed_payload] == [recommendation_id]
    assert listed_payload[0]["status"] == "pending"
    assert listed_payload[0]["evidence_snapshot"] == {"usage_event_ids": ["usage-api-1"]}
    assert listed_payload[0]["metrics_snapshot"] == {"negative_usage_rate": 0.4}

    detail = client.get(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}",
        headers=_operator_headers(),
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == recommendation_id

    accepted = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Accept merge candidate note."},
    )
    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["id"] == recommendation_id
    assert accepted_payload["status"] == "accepted"
    assert accepted_payload["accepted_by"] == _operator_actor_id()
    assert accepted_payload["accepted_at"] is not None
    assert accepted_payload["decision_reason_code"] == "operator_reviewed"
    assert accepted_payload["action_result"] == {"executed": False, "recommended_action": "none"}

    repeated_accept = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Repeat accept."},
    )
    assert repeated_accept.status_code == 200
    assert repeated_accept.json()["status"] == "accepted"

    dismissed = client.post(
        f"/api/v1/skill-curator-recommendations/{dismiss_recommendation_id}/dismiss",
        headers=_operator_headers(),
        json={"reason_code": "false_positive", "reason_note": "No longer relevant."},
    )
    assert dismissed.status_code == 200
    dismissed_payload = dismissed.json()
    assert dismissed_payload["id"] == dismiss_recommendation_id
    assert dismissed_payload["status"] == "dismissed"
    assert dismissed_payload["dismissed_by"] == _operator_actor_id()
    assert dismissed_payload["dismissed_at"] is not None

    cannot_dismiss_accepted = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/dismiss",
        headers=_operator_headers(),
        json={"reason_code": "false_positive", "reason_note": "Too late."},
    )
    assert cannot_dismiss_accepted.status_code == 400

    event_types = asyncio.run(_audit_event_types())
    assert "skill.curator.recommendation.created" in event_types
    assert "skill.curator.recommendation.accepted" in event_types
    assert "skill.curator.recommendation.accept_reused" in event_types
    assert "skill.curator.recommendation.dismissed" in event_types


def test_skill_curator_recommendation_accept_patch_needed_creates_skill_patch_proposal(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Accept patch recommendation",
            "subject": "Algebra",
            "target_outcome": "Route skill patch recommendations through governance",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    async def seed_reflection() -> str:
        from agent_core.api import dependencies as api_dependencies

        session_factory = api_dependencies.get_session_factory()
        async with session_factory() as db:
            reflection = ReflectionRecord.build(
                learner_profile_id=profile_id,
                learner_goal_id=goal_id,
                daily_task_id=None,
                workflow_run_id=None,
                study_plan_id=None,
                scope="goal",
                target_type="learner_goal",
                target_id=goal_id,
                trigger_source="consecutive_failure_pattern",
                reflection_depth=1,
                dedupe_key=f"patch-recommendation:{goal_id}",
                aggregation_key=f"patch-recommendation:{goal_id}",
                duplicate_count=1,
                priority_score=0.8,
                last_duplicate_at=None,
                cooldown_until=None,
                primary_root_cause="knowledge_gap",
                secondary_root_causes=[],
                severity="medium",
                confidence_score=0.8,
                summary="Seeded patch recommendation reflection.",
                evidence_summary="Seeded API integration evidence.",
                recommended_next_step="Create a governed skill patch request.",
                evidence_payload={"source": "api_integration"},
            )
            await ReflectionRecordRepository(db).create(reflection)
            await db.commit()
            return reflection.id

    reflection_id = asyncio.run(seed_reflection())
    recommendation_id = asyncio.run(
        _seed_skill_curator_recommendation(
            recommendation_type="patch_needed",
            recommended_action="none",
            reason_code="quality_regression",
            evidence_snapshot={
                "learner_goal_id": goal_id,
                "reflection_record_id": reflection_id,
                "usage_event_ids": ["usage-api-1", "usage-api-2"],
            },
            metrics_snapshot={"negative_usage_rate": 0.5},
        )
    )

    accepted = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Create governed patch proposal."},
    )

    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["status"] == "accepted"
    assert accepted_payload["action_result"]["executed"] is True
    assert accepted_payload["action_result"]["recommended_action"] == "create_skill_patch_proposal"
    proposal_id = accepted_payload["action_result"]["proposal_id"]
    assert accepted_payload["action_result"]["proposal_type"] == "skill_patch_request"
    assert accepted_payload["action_result"]["proposal_status"] in {"proposed", "sandbox_queued"}

    proposal = client.get(f"/api/v1/proposals/{proposal_id}", headers=_operator_headers())
    assert proposal.status_code == 200
    proposal_payload = proposal.json()
    assert proposal_payload["proposal_type"] == "skill_patch_request"
    assert proposal_payload["reflection_record_id"] == reflection_id
    assert proposal_payload["learner_goal_id"] == goal_id
    assert proposal_payload["rollout_eligible"] is False
    assert proposal_payload["activation_surface"] is None
    assert proposal_payload["structured_patch_payload"]["recommendation_id"] == recommendation_id
    assert proposal_payload["structured_patch_payload"]["usage_event_ids"] == ["usage-api-1", "usage-api-2"]
    assert "runtime_directives" not in proposal_payload["structured_patch_payload"]
    assert "tool_plan" not in proposal_payload["structured_patch_payload"]

    rollout = client.post(
        f"/api/v1/proposals/{proposal_id}/activate",
        headers=_operator_headers(),
        json={"reason_code": "activate", "reason_note": "Should be blocked."},
    )
    assert rollout.status_code == 400

    candidate = client.post(
        "/api/v1/skill-artifacts/from-reflection-proposal",
        headers=_operator_headers(),
        json={"proposal_id": proposal_id},
    )
    assert candidate.status_code == 400

    event_types = asyncio.run(_audit_event_types())
    assert "reflection.proposal.created" in event_types
    assert "skill.curator.recommendation.accepted" in event_types


def test_skill_curator_recommendation_accept_merge_candidate_creates_merge_proposal_and_stages(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Accept merge recommendation",
            "subject": "Algebra",
            "target_outcome": "Route merge recommendations through governed skill package proposals",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]
    source_artifact, related_artifact, reflection_id = asyncio.run(
        _seed_merge_candidate_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal_id,
        )
    )
    recommendation_id = asyncio.run(
        _seed_skill_curator_recommendation(
            recommendation_type="merge_candidate",
            recommended_action="none",
            reason_code="merge_candidate",
            artifact_id=source_artifact.id,
            evidence_snapshot={
                "learner_goal_id": goal_id,
                "reflection_record_id": reflection_id,
                "overlap_reason": "duplicate topic coverage",
            },
            metrics_snapshot={"overlap_score": 0.8},
            related_artifact_ids=[related_artifact.id],
        )
    )

    unauthorized = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        json={"reason_code": "operator_reviewed", "reason_note": "Missing operator key."},
    )
    assert unauthorized.status_code == 403

    accepted = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Create governed merge proposal."},
    )

    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["status"] == "accepted"
    assert accepted_payload["action_result"]["executed"] is True
    assert accepted_payload["action_result"]["recommended_action"] == "create_skill_merge_proposal"
    assert accepted_payload["action_result"]["proposal_type"] == "skill_package"
    assert accepted_payload["action_result"]["proposal_status"] in {"proposed", "sandbox_queued"}
    assert accepted_payload["action_result"]["artifact_id"] == source_artifact.id
    assert accepted_payload["action_result"]["merge_source_artifact_ids"] == [related_artifact.id]

    proposal_id = accepted_payload["action_result"]["proposal_id"]
    proposal = client.get(f"/api/v1/proposals/{proposal_id}", headers=_operator_headers())
    assert proposal.status_code == 200
    proposal_payload = proposal.json()
    assert proposal_payload["proposal_type"] == "skill_package"
    assert proposal_payload["reflection_record_id"] == reflection_id
    assert proposal_payload["learner_goal_id"] == goal_id
    assert proposal_payload["rollout_eligible"] is True
    assert proposal_payload["activation_surface"] == "quiz"
    assert proposal_payload["structured_patch_payload"] == {
        "artifact_kind": "declarative_skill_package",
        "skill_name": "create_quiz",
        "surface": "quiz",
        "match_rules": {
            "task_types": ["practice", "review"],
            "topic_keys": ["algebra", "linear-systems"],
        },
        "runtime_directives": {"question_count": 3, "feedback_style": "guided_correction"},
        "tool_plan": [],
        "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
    }
    assert proposal_payload["evidence_snapshot"]["source"] == "skill_curator_merge_recommendation"
    assert proposal_payload["evidence_snapshot"]["recommendation_id"] == recommendation_id
    assert proposal_payload["evidence_snapshot"]["source_artifact_id"] == source_artifact.id
    assert proposal_payload["evidence_snapshot"]["source_artifact_lineage_id"] == source_artifact.lineage_id
    assert proposal_payload["evidence_snapshot"]["merge_source_artifact_ids"] == [related_artifact.id]

    rejected_stage = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        headers=_operator_headers(),
        json={
            "proposal_id": proposal_id,
            "reason_code": "reviewed",
            "reason_note": "Not approved yet.",
        },
    )
    assert rejected_stage.status_code == 400

    approved_merge = asyncio.run(_approve_realized_replacement_proposal(proposal_id))
    assert approved_merge.status == "approved"

    staged = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        headers=_operator_headers(),
        json={
            "proposal_id": proposal_id,
            "reason_code": "reviewed",
            "reason_note": "Stage governed merge replacement.",
        },
    )
    assert staged.status_code == 200
    staged_payload = staged.json()
    assert staged_payload["status"] == "staged"
    assert staged_payload["source_proposal_id"] == proposal_id
    assert staged_payload["lineage_id"] == source_artifact.lineage_id
    assert staged_payload["parent_artifact_id"] == source_artifact.id
    assert staged_payload["supersedes_artifact_id"] == source_artifact.id
    assert staged_payload["approved_by"] is None
    assert staged_payload["approved_at"] is None

    source_after_stage = client.get(f"/api/v1/skill-artifacts/{source_artifact.id}", headers=_operator_headers())
    assert source_after_stage.status_code == 200
    assert source_after_stage.json()["status"] == "stable"

    event_types = asyncio.run(_audit_event_types())
    assert "reflection.proposal.skill_merge_created" in event_types
    assert "skill.curator.recommendation.accepted" in event_types
    assert "skill.artifact.replacement_proposal_staged" in event_types


def test_realize_skill_patch_request_route_creates_replacement_skill_package_proposal(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Realize patch request",
            "subject": "Algebra",
            "target_outcome": "Turn approved patch request into governed replacement proposal",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    source_artifact, patch_request = asyncio.run(
        _seed_realizable_skill_patch_request(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )

    unauthorized = client.post(
        f"/api/v1/proposals/{patch_request.id}/realize-skill-patch",
        json={"reason_code": "operator_reviewed", "reason_note": "Missing operator key."},
    )
    assert unauthorized.status_code == 403

    realized = client.post(
        f"/api/v1/proposals/{patch_request.id}/realize-skill-patch",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Create replacement proposal."},
    )

    assert realized.status_code == 200
    realized_payload = realized.json()
    assert realized_payload["proposal_type"] == "skill_package"
    assert realized_payload["status"] in {"proposed", "sandbox_queued"}
    assert realized_payload["target_scope"] == "quiz"
    assert realized_payload["rollout_eligible"] is True
    assert realized_payload["activation_surface"] == "quiz"
    assert realized_payload["structured_patch_payload"] == {
        "artifact_kind": "declarative_skill_package",
        "skill_name": "create_quiz",
        "surface": "quiz",
        "match_rules": {"task_types": ["practice"], "topic_keys": ["algebra"]},
        "runtime_directives": {"question_count": 3, "feedback_style": "guided_correction"},
        "tool_plan": [],
        "scoring_contract": {"mode": "rule_replay_live_llm", "minimum_sample_count": 2},
    }
    assert realized_payload["evidence_snapshot"]["source"] == "skill_patch_request_realization"
    assert realized_payload["evidence_snapshot"]["source_skill_patch_request_id"] == patch_request.id
    assert realized_payload["evidence_snapshot"]["source_artifact_id"] == source_artifact.id
    assert realized_payload["evidence_snapshot"]["source_artifact_lineage_id"] == source_artifact.lineage_id
    assert realized_payload["evidence_snapshot"]["usage_event_ids"] == ["usage-api-1", "usage-api-2"]
    assert realized_payload["evidence_snapshot"]["patch_request_evaluation"]["score_delta"] == 0.15

    source_after = client.get(f"/api/v1/skill-artifacts/{source_artifact.id}", headers=_operator_headers())
    assert source_after.status_code == 200
    assert source_after.json()["status"] == "stable"

    candidate = client.post(
        "/api/v1/skill-artifacts/from-reflection-proposal",
        headers=_operator_headers(),
        json={"proposal_id": realized_payload["id"]},
    )
    assert candidate.status_code == 400

    unauthorized_stage = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        json={
            "proposal_id": realized_payload["id"],
            "reason_code": "reviewed",
            "reason_note": "Missing operator key.",
        },
    )
    assert unauthorized_stage.status_code == 403

    rejected_stage = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        headers=_operator_headers(),
        json={
            "proposal_id": realized_payload["id"],
            "reason_code": "reviewed",
            "reason_note": "Not approved yet.",
        },
    )
    assert rejected_stage.status_code == 400

    approved_replacement = asyncio.run(_approve_realized_replacement_proposal(realized_payload["id"]))
    assert approved_replacement.status == "approved"

    staged = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        headers=_operator_headers(),
        json={
            "proposal_id": realized_payload["id"],
            "reason_code": "reviewed",
            "reason_note": "Stage governed replacement.",
        },
    )
    assert staged.status_code == 200
    staged_payload = staged.json()
    assert staged_payload["status"] == "staged"
    assert staged_payload["source_proposal_id"] == realized_payload["id"]
    assert staged_payload["lineage_id"] == source_artifact.lineage_id
    assert staged_payload["parent_artifact_id"] == source_artifact.id
    assert staged_payload["supersedes_artifact_id"] == source_artifact.id
    assert staged_payload["approved_by"] is None
    assert staged_payload["approved_at"] is None

    source_after_stage = client.get(f"/api/v1/skill-artifacts/{source_artifact.id}", headers=_operator_headers())
    assert source_after_stage.status_code == 200
    assert source_after_stage.json()["status"] == "stable"

    repeated_stage = client.post(
        "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
        headers=_operator_headers(),
        json={
            "proposal_id": realized_payload["id"],
            "reason_code": "reviewed",
            "reason_note": "Repeat staging.",
        },
    )
    assert repeated_stage.status_code == 200
    assert repeated_stage.json()["id"] == staged_payload["id"]
    assert repeated_stage.json()["status"] == "staged"

    repeated = client.post(
        f"/api/v1/proposals/{patch_request.id}/realize-skill-patch",
        headers=_operator_headers(),
        json={"reason_code": "operator_reviewed", "reason_note": "Repeat."},
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == realized_payload["id"]

    event_types = asyncio.run(_audit_event_types())
    assert "reflection.proposal.skill_patch_realized" in event_types
    assert "reflection.proposal.skill_patch_realize_reused" in event_types
    assert "skill.artifact.replacement_proposal_staged" in event_types


def test_skill_curator_recommendation_accept_archive_candidate_archives_artifact(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    profile_id, access_key = _create_profile_with_key(client)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=_learner_headers(access_key),
        json={
            "title": "Accept archive recommendation",
            "subject": "Algebra",
            "target_outcome": "Archive stale skill package recommendations",
            "deadline_date": (date.today() + timedelta(days=21)).isoformat(),
            "weekly_study_minutes": 120,
        },
    )
    assert goal.status_code == 200
    current, _replacement = asyncio.run(
        _seed_replaceable_skill_artifacts(
            learner_profile_id=profile_id,
            learner_goal_id=goal.json()["id"],
        )
    )
    deactivated = client.post(
        f"/api/v1/skill-artifacts/{current.id}/deactivate",
        headers=_operator_headers(),
        json={"reason_code": "operator_request", "reason_note": "Prepare archive recommendation."},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["status"] == "deprecated"
    recommendation_id = asyncio.run(
        _seed_skill_curator_recommendation(
            recommendation_type="archive_candidate",
            recommended_action="archive_deprecated",
            reason_code="stale_deprecated",
            artifact_id=current.id,
        )
    )

    accepted = client.post(
        f"/api/v1/skill-curator-recommendations/{recommendation_id}/accept",
        headers=_operator_headers(),
        json={"reason_code": "stale_deprecated", "reason_note": "Accept archive recommendation."},
    )

    assert accepted.status_code == 200
    accepted_payload = accepted.json()
    assert accepted_payload["id"] == recommendation_id
    assert accepted_payload["status"] == "accepted"
    assert accepted_payload["action_result"] == {
        "executed": True,
        "recommended_action": "archive_deprecated",
        "artifact_id": current.id,
        "artifact_status": "archived",
        "skill_name": "create_quiz",
        "skill_version": current.version,
        "scope": "quiz",
    }
    archived = client.get(f"/api/v1/skill-artifacts/{current.id}", headers=_operator_headers())
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    event_types = asyncio.run(_audit_event_types())
    assert "skill.artifact.archived" in event_types
    assert "skill.curator.recommendation.accepted" in event_types


def test_deactivate_skill_artifact_route_rolls_back_on_service_error(monkeypatch):
    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            self.rollbacks += 1

    class FailingLifecycleService:
        async def deactivate_active(self, **_kwargs):
            raise ValidationError("Cannot deactivate skill artifact while active rollouts exist.")

    fake_session = FakeSession()
    monkeypatch.setenv("AGENT_EDU_APP_ENV", "testing")
    monkeypatch.setenv("AGENT_EDU_OPERATOR_API_KEY", "secret-operator")
    app = create_app()

    async def override_session():
        return fake_session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_skill_artifact_lifecycle_service] = lambda: FailingLifecycleService()
    app.dependency_overrides[require_operator_api_key] = lambda: _operator_actor_id()

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/skill-artifacts/artifact-1/deactivate",
                headers=_operator_headers(),
                json={"reason_code": "rollout_rollback", "reason_note": "blocked"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1


def test_stage_replacement_route_rolls_back_on_service_error(monkeypatch):
    class FakeSession:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            self.rollbacks += 1

    class FailingReplacementStagingService:
        async def stage_replacement_from_proposal(self, **_kwargs):
            raise ValidationError("Only approved skill_package proposals can create skill candidates.")

    fake_session = FakeSession()
    monkeypatch.setenv("AGENT_EDU_APP_ENV", "testing")
    monkeypatch.setenv("AGENT_EDU_OPERATOR_API_KEY", "secret-operator")
    app = create_app()

    async def override_session():
        return fake_session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_skill_replacement_staging_service] = lambda: FailingReplacementStagingService()
    app.dependency_overrides[require_operator_api_key] = lambda: _operator_actor_id()

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/skill-artifacts/staged-replacements/from-reflection-proposal",
                headers=_operator_headers(),
                json={
                    "proposal_id": "proposal-1",
                    "reason_code": "reviewed",
                    "reason_note": "blocked",
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1


def test_phase2_profile_goal_plan_task_workflow_chain(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)

    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": "Learner struggles with dimensions.",
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    plan = client.post(
        f"/api/v1/goals/{goal_id}/plans",
        headers=headers,
        json={"trigger_source": "initial"},
    )
    assert plan.status_code == 200
    plan_payload = plan.json()
    assert plan_payload["version"] == 1
    assert len(plan_payload["stages"]) >= 2

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks.status_code == 200
    task_payloads = tasks.json()
    assert len(task_payloads) >= 1
    first_task = task_payloads[0]

    execute = client.post(f"/api/v1/tasks/{first_task['id']}/execute", headers=headers)
    assert execute.status_code == 200
    execute_payload = execute.json()
    assert execute_payload["reused_existing_execution"] is False
    assert execute_payload["task"]["status"] == "in_progress"
    assert execute_payload["execution_session_id"] is not None

    complete = client.patch(
        f"/api/v1/tasks/{first_task['id']}/status",
        headers=headers,
        json={"status": "completed", "result_note": "Finished"},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"

    _run_autonomy_worker_once()
    tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_after.status_code == 200
    assert any(item["task_type"] == "review" for item in tasks_after.json())

    runs = client.get(f"/api/v1/goals/{goal_id}/workflow-runs", headers=headers)
    assert runs.status_code == 200
    workflow_types = {item["workflow_type"] for item in runs.json()}
    assert {"plan_generation", "task_execution", "review_scheduling"}.issubset(workflow_types)


def test_phase2_failed_task_triggers_replan_and_supersedes_future_tasks(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    goal_id = goal.json()["id"]
    initial_plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"}).json()

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers).json()
    pending_task = tasks[0]
    failed = client.patch(
        f"/api/v1/tasks/{pending_task['id']}/status",
        headers=headers,
        json={"status": "failed", "result_note": "Learner blocked"},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    _run_autonomy_worker_once()

    plans = client.get(f"/api/v1/goals/{goal_id}/plans", headers=headers)
    assert plans.status_code == 200
    plan_versions = sorted(item["version"] for item in plans.json())
    assert plan_versions == [1, 2]
    latest_plan = plans.json()[0]
    assert latest_plan["version"] == 2

    old_plan = next(item for item in plans.json() if item["id"] == initial_plan["id"])
    assert old_plan["status"] == "superseded"


def test_autonomy_endpoints_cover_state_availability_pause_and_manual_replan(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()

    profile = client.post("/api/v1/learner-profiles", json={})
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    goal_id = goal.json()["id"]
    plan = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"}).json()

    state = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=headers)
    assert state.status_code == 200
    state_payload = state.json()
    assert state_payload["phase"] == "active"
    assert state_payload["current_plan_id"] == plan["id"]

    availability = client.put(
        f"/api/v1/goals/{goal_id}/availability",
        headers=headers,
        json={
            "timezone": "Asia/Shanghai",
            "available_days": ["mon", "wed", "fri"],
            "time_windows": [{"start": "19:00", "end": "21:00"}],
            "max_daily_minutes": 90,
            "preferred_session_length_minutes": 45,
        },
    )
    assert availability.status_code == 200
    assert availability.json()["timezone"] == "Asia/Shanghai"

    listed_mastery = client.get(f"/api/v1/goals/{goal_id}/mastery", headers=headers)
    assert listed_mastery.status_code == 200
    assert listed_mastery.json() == []

    jobs = client.get(f"/api/v1/goals/{goal_id}/autonomy/jobs", headers=headers)
    assert jobs.status_code == 200
    assert isinstance(jobs.json(), list)
    materialization_jobs = [item for item in jobs.json() if item["job_type"] == "daily_task_materialization"]
    assert materialization_jobs
    assert materialization_jobs[0]["payload"]["target_timezone"] == "Asia/Shanghai"
    assert materialization_jobs[0]["payload"]["scheduled_local_time"] == "19:00"

    paused = client.patch(
        f"/api/v1/goals/{goal_id}/autonomy/pause",
        headers=headers,
        json={"reason": "travel"},
    )
    assert paused.status_code == 200
    assert paused.json()["phase"] == "paused"

    resumed = client.patch(f"/api/v1/goals/{goal_id}/autonomy/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["phase"] == "active"

    replanned = client.post(
        f"/api/v1/goals/{goal_id}/replan",
        headers=headers,
        json={"trigger_source": "manual_replan", "mode": "full"},
    )
    assert replanned.status_code == 200
    assert replanned.json()["phase"] == "active"

    materialized = client.post(f"/api/v1/goals/{goal_id}/autonomy/materialize-today", headers=headers)
    assert materialized.status_code == 200
    assert materialized.json()["phase"] == "active"

    plans = client.get(f"/api/v1/goals/{goal_id}/plans", headers=headers)
    assert plans.status_code == 200
    plan_versions = sorted(item["version"] for item in plans.json())
    assert plan_versions == [1, 2]


def test_milestone_gate_surfaces_assessment_due_phase(app_client_factory):
    client = app_client_factory()
    deadline = (date.today() + timedelta(days=21)).isoformat()
    profile = client.post("/api/v1/learner-profiles", json={})
    assert profile.status_code == 200
    profile_id = profile.json()["id"]
    access_key = profile.json()["access_key"]
    headers = _learner_headers(access_key)
    goal = client.post(
        f"/api/v1/learner-profiles/{profile_id}/goals",
        headers=headers,
        json={
            "title": "Master matrices",
            "subject": "Linear Algebra",
            "target_outcome": "Solve core matrix exercises independently",
            "baseline_note": None,
            "deadline_date": deadline,
            "weekly_study_minutes": 180,
        },
    )
    assert goal.status_code == 200
    goal_id = goal.json()["id"]

    planned = client.post(f"/api/v1/goals/{goal_id}/plans", headers=headers, json={"trigger_source": "initial"})
    assert planned.status_code == 200

    tasks = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks.status_code == 200
    first_stage_id = tasks.json()[0]["plan_stage_id"]
    first_stage_tasks = [item for item in tasks.json() if item["plan_stage_id"] == first_stage_id and item["task_type"] in {"lesson", "practice"}]
    target_count = max(1, (len(first_stage_tasks) + 1) // 2)
    for item in first_stage_tasks[:target_count]:
        executed = client.post(f"/api/v1/tasks/{item['id']}/execute", headers=headers)
        assert executed.status_code == 200
        completed = client.patch(
            f"/api/v1/tasks/{item['id']}/status",
            headers=headers,
            json={"status": "completed", "result_note": "Done"},
        )
        assert completed.status_code == 200
        _run_autonomy_worker_once()

    worker_materialized = client.post(f"/api/v1/goals/{goal_id}/autonomy/materialize-today", headers=headers)
    assert worker_materialized.status_code == 200

    state = client.get(f"/api/v1/goals/{goal_id}/autonomy", headers=headers)
    assert state.status_code == 200
    assert state.json()["phase"] in {"active", "assessment_due"}

    tasks_after = client.get(f"/api/v1/goals/{goal_id}/tasks", headers=headers)
    assert tasks_after.status_code == 200
    assert any(item["task_type"] == "milestone" for item in tasks_after.json())


def test_skill_operator_usage_api_records_chat_usage(app_client_factory):
    client = app_client_factory(env_overrides={"AGENT_EDU_OPERATOR_API_KEY": "secret-operator"})
    missing_key = client.get("/api/v1/skill-usage")
    assert missing_key.status_code == 403
    wrong_key = client.get("/api/v1/skill-usage", headers={"X-Operator-Key": "wrong-secret"})
    assert wrong_key.status_code == 403
    auth_failures = [
        item
        for item in asyncio.run(_audit_events())
        if item["event_type"] == "auth.operator_api_key.rejected"
    ]
    assert len(auth_failures) == 2
    assert {item["actor"] for item in auth_failures} == {"anonymous"}
    assert all("wrong-secret" not in str(item["event_data"]) for item in auth_failures)

    session_response = client.post(
        "/api/v1/sessions",
        json={"title": "Algebra", "subject": "Equations"},
    )
    assert session_response.status_code == 200
    session_id = session_response.json()["id"]

    chat_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"content": "Explain linear equations.", "mode": "chat"},
    )
    assert chat_response.status_code == 200

    usage_response = client.get(
        "/api/v1/skill-usage",
        headers=_operator_headers(),
        params={"session_id": session_id},
    )
    assert usage_response.status_code == 200
    usage = usage_response.json()
    chat_usage = next(item for item in usage if item["skill_name"] == "explain_concept" and item["surface"] == "chat")
    assert chat_usage["resolver_status"] == "missing_artifact"
    assert chat_usage["selection_reason"] == "artifact_missing_static_fallback"
    assert chat_usage["input_fingerprint"] is not None
    assert chat_usage["output_fingerprint"] is not None
    assert chat_usage["outcome_signals"] == {}

    artifacts_response = client.get("/api/v1/skill-artifacts", headers=_operator_headers())
    assert artifacts_response.status_code == 200

    filtered_usage = client.get(
        "/api/v1/skill-usage",
        headers=_operator_headers(),
        params={"resolver_status": "missing_artifact", "surface": "chat"},
    )
    assert filtered_usage.status_code == 200
    assert any(item["id"] == chat_usage["id"] for item in filtered_usage.json())

    before_resolution_probe = asyncio.run(_audit_event_types())
    resolution_response = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "explain_concept", "surface": "chat"},
    )
    assert resolution_response.status_code == 200
    assert resolution_response.json()["resolver_status"] == "missing_artifact"
    after_default_probe = asyncio.run(_audit_event_types())
    assert after_default_probe.count("skill.resolution.probed") == before_resolution_probe.count(
        "skill.resolution.probed"
    )
    assert after_default_probe.count("skill.resolution.missing_artifact") == before_resolution_probe.count(
        "skill.resolution.missing_artifact"
    )

    audited_resolution_response = client.get(
        "/api/v1/skill-resolution",
        headers=_operator_headers(),
        params={"skill_name": "explain_concept", "surface": "chat", "audit": "true"},
    )
    assert audited_resolution_response.status_code == 200
    assert audited_resolution_response.json()["resolver_status"] == "missing_artifact"
    after_audited_probe = asyncio.run(_audit_event_types())
    assert after_audited_probe.count("skill.resolution.probed") == after_default_probe.count(
        "skill.resolution.probed"
    ) + 1
    assert after_audited_probe.count("skill.resolution.missing_artifact") == after_default_probe.count(
        "skill.resolution.missing_artifact"
    ) + 1
