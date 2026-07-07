from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

PLAN_STATUSES = {"active", "superseded", "completed"}
PLAN_TRIGGER_SOURCES = {
    "initial",
    "manual_replan",
    "task_failed",
    "task_skipped",
    "proposal_rollout_activation",
    "proposal_rollout_rollback",
    "learner_ui",
}
TASK_ORIGINS = {"planner", "review_scheduler", "assessment_scheduler", "replan_scheduler"}
TASK_TYPES = {"lesson", "practice", "review", "assessment", "milestone", "repair"}
TASK_EXECUTION_MODES = {"chat", "quiz"}
TASK_STATUSES = {"pending", "in_progress", "completed", "skipped", "failed", "superseded"}
WORKFLOW_TYPES = {"plan_generation", "task_execution", "review_scheduling", "assessment_generation", "plan_extension"}
WORKFLOW_STATUSES = {"running", "completed", "failed"}


@dataclass(frozen=True)
class StudyPlan:
    id: str
    learner_goal_id: str
    version: int
    status: str
    trigger_source: str
    plan_summary: str
    blueprint_payload: dict[str, Any]
    materialized_until_date: date | None
    supersedes_plan_id: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        version: int,
        trigger_source: str,
        plan_summary: str,
        blueprint_payload: dict[str, Any],
        materialized_until_date: date | None,
        supersedes_plan_id: str | None = None,
    ) -> "StudyPlan":
        if trigger_source not in PLAN_TRIGGER_SOURCES:
            raise ValidationError("Unsupported study plan trigger source.")
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            version=version,
            status="active",
            trigger_source=trigger_source,
            plan_summary=plan_summary,
            blueprint_payload=blueprint_payload,
            materialized_until_date=materialized_until_date,
            supersedes_plan_id=supersedes_plan_id,
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: str) -> "StudyPlan":
        if status not in PLAN_STATUSES:
            raise ValidationError("Unsupported study plan status.")
        return StudyPlan(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            version=self.version,
            status=status,
            trigger_source=self.trigger_source,
            plan_summary=self.plan_summary,
            blueprint_payload=self.blueprint_payload,
            materialized_until_date=self.materialized_until_date,
            supersedes_plan_id=self.supersedes_plan_id,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    def with_materialized_until(self, materialized_until_date: date | None) -> "StudyPlan":
        return StudyPlan(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            version=self.version,
            status=self.status,
            trigger_source=self.trigger_source,
            plan_summary=self.plan_summary,
            blueprint_payload=self.blueprint_payload,
            materialized_until_date=materialized_until_date,
            supersedes_plan_id=self.supersedes_plan_id,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class PlanStage:
    id: str
    study_plan_id: str
    position: int
    title: str
    objective: str
    focus_topics: list[str]
    start_date: date
    end_date: date

    @classmethod
    def build(
        cls,
        *,
        study_plan_id: str,
        position: int,
        title: str,
        objective: str,
        focus_topics: list[str],
        start_date: date,
        end_date: date,
    ) -> "PlanStage":
        return cls(
            id=str(uuid4()),
            study_plan_id=study_plan_id,
            position=position,
            title=title,
            objective=objective,
            focus_topics=focus_topics,
            start_date=start_date,
            end_date=end_date,
        )


@dataclass(frozen=True)
class DailyTask:
    id: str
    learner_goal_id: str
    study_plan_id: str
    plan_stage_id: str | None
    task_origin: str
    task_type: str
    execution_mode: str
    title: str
    instructions: str
    topic_focus: str
    difficulty: str | None
    question_count: int | None
    estimated_minutes: int
    scheduled_for: date
    due_on: date
    status: str
    source_task_id: str | None
    execution_session_id: str | None
    last_workflow_run_id: str | None
    result_note: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_goal_id: str,
        study_plan_id: str,
        plan_stage_id: str | None,
        task_origin: str,
        task_type: str,
        execution_mode: str,
        title: str,
        instructions: str,
        topic_focus: str,
        difficulty: str | None,
        question_count: int | None,
        estimated_minutes: int,
        scheduled_for: date,
        due_on: date,
        source_task_id: str | None = None,
    ) -> "DailyTask":
        if task_origin not in TASK_ORIGINS:
            raise ValidationError("Unsupported daily task origin.")
        if task_type not in TASK_TYPES:
            raise ValidationError("Unsupported daily task type.")
        if execution_mode not in TASK_EXECUTION_MODES:
            raise ValidationError("Unsupported daily task execution mode.")
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            learner_goal_id=learner_goal_id,
            study_plan_id=study_plan_id,
            plan_stage_id=plan_stage_id,
            task_origin=task_origin,
            task_type=task_type,
            execution_mode=execution_mode,
            title=title,
            instructions=instructions,
            topic_focus=topic_focus,
            difficulty=difficulty,
            question_count=question_count,
            estimated_minutes=estimated_minutes,
            scheduled_for=scheduled_for,
            due_on=due_on,
            status="pending",
            source_task_id=source_task_id,
            execution_session_id=None,
            last_workflow_run_id=None,
            result_note=None,
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: str, *, result_note: str | None) -> "DailyTask":
        if status not in TASK_STATUSES:
            raise ValidationError("Unsupported daily task status.")
        return DailyTask(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            study_plan_id=self.study_plan_id,
            plan_stage_id=self.plan_stage_id,
            task_origin=self.task_origin,
            task_type=self.task_type,
            execution_mode=self.execution_mode,
            title=self.title,
            instructions=self.instructions,
            topic_focus=self.topic_focus,
            difficulty=self.difficulty,
            question_count=self.question_count,
            estimated_minutes=self.estimated_minutes,
            scheduled_for=self.scheduled_for,
            due_on=self.due_on,
            status=status,
            source_task_id=self.source_task_id,
            execution_session_id=self.execution_session_id,
            last_workflow_run_id=self.last_workflow_run_id,
            result_note=result_note,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    def with_execution_session(self, *, execution_session_id: str, workflow_run_id: str) -> "DailyTask":
        return DailyTask(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            study_plan_id=self.study_plan_id,
            plan_stage_id=self.plan_stage_id,
            task_origin=self.task_origin,
            task_type=self.task_type,
            execution_mode=self.execution_mode,
            title=self.title,
            instructions=self.instructions,
            topic_focus=self.topic_focus,
            difficulty=self.difficulty,
            question_count=self.question_count,
            estimated_minutes=self.estimated_minutes,
            scheduled_for=self.scheduled_for,
            due_on=self.due_on,
            status="in_progress",
            source_task_id=self.source_task_id,
            execution_session_id=execution_session_id,
            last_workflow_run_id=workflow_run_id,
            result_note=self.result_note,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )

    def with_last_workflow_run(self, workflow_run_id: str) -> "DailyTask":
        return DailyTask(
            id=self.id,
            learner_goal_id=self.learner_goal_id,
            study_plan_id=self.study_plan_id,
            plan_stage_id=self.plan_stage_id,
            task_origin=self.task_origin,
            task_type=self.task_type,
            execution_mode=self.execution_mode,
            title=self.title,
            instructions=self.instructions,
            topic_focus=self.topic_focus,
            difficulty=self.difficulty,
            question_count=self.question_count,
            estimated_minutes=self.estimated_minutes,
            scheduled_for=self.scheduled_for,
            due_on=self.due_on,
            status=self.status,
            source_task_id=self.source_task_id,
            execution_session_id=self.execution_session_id,
            last_workflow_run_id=workflow_run_id,
            result_note=self.result_note,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class WorkflowRun:
    id: str
    workflow_type: str
    status: str
    trigger_source: str
    learner_goal_id: str | None
    study_plan_id: str | None
    daily_task_id: str | None
    scheduled_job_id: str | None
    result_resource_type: str | None
    result_resource_ids: list[str]
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def build(
        cls,
        *,
        workflow_type: str,
        trigger_source: str,
        learner_goal_id: str | None,
        study_plan_id: str | None,
        daily_task_id: str | None,
        scheduled_job_id: str | None = None,
    ) -> "WorkflowRun":
        if workflow_type not in WORKFLOW_TYPES:
            raise ValidationError("Unsupported workflow type.")
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            workflow_type=workflow_type,
            status="running",
            trigger_source=trigger_source,
            learner_goal_id=learner_goal_id,
            study_plan_id=study_plan_id,
            daily_task_id=daily_task_id,
            scheduled_job_id=scheduled_job_id,
            result_resource_type=None,
            result_resource_ids=[],
            error_code=None,
            created_at=now,
            started_at=now,
            finished_at=None,
        )

    def complete(
        self,
        *,
        result_resource_type: str | None,
        result_resource_ids: list[str],
    ) -> "WorkflowRun":
        return WorkflowRun(
            id=self.id,
            workflow_type=self.workflow_type,
            status="completed",
            trigger_source=self.trigger_source,
            learner_goal_id=self.learner_goal_id,
            study_plan_id=self.study_plan_id,
            daily_task_id=self.daily_task_id,
            scheduled_job_id=self.scheduled_job_id,
            result_resource_type=result_resource_type,
            result_resource_ids=result_resource_ids,
            error_code=None,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=datetime.now(timezone.utc),
        )

    def fail(self, *, error_code: str | None) -> "WorkflowRun":
        return WorkflowRun(
            id=self.id,
            workflow_type=self.workflow_type,
            status="failed",
            trigger_source=self.trigger_source,
            learner_goal_id=self.learner_goal_id,
            study_plan_id=self.study_plan_id,
            daily_task_id=self.daily_task_id,
            scheduled_job_id=self.scheduled_job_id,
            result_resource_type=self.result_resource_type,
            result_resource_ids=self.result_resource_ids,
            error_code=error_code,
            created_at=self.created_at,
            started_at=self.started_at,
            finished_at=datetime.now(timezone.utc),
        )
