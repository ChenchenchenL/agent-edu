from datetime import datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, JSON, Integer, String, Text, func, literal_column
from sqlalchemy.orm import Mapped, mapped_column

from agent_core.infrastructure.db.base import Base


class LearningSessionModel(Base):
    __tablename__ = "learning_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    daily_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message_count: Mapped[int] = mapped_column(nullable=False, default=0)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearnerProfileModel(Base):
    __tablename__ = "learner_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    access_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    access_key_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearnerGoalModel(Base):
    __tablename__ = "learner_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    target_outcome: Mapped[str] = mapped_column(Text(), nullable=False)
    baseline_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    deadline_date: Mapped[datetime] = mapped_column(Date(), nullable=False)
    weekly_study_minutes: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StudyPlanModel(Base):
    __tablename__ = "study_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    blueprint_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    materialized_until_date: Mapped[datetime | None] = mapped_column(Date(), nullable=True)
    supersedes_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PlanStageModel(Base):
    __tablename__ = "plan_stages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_plan_id: Mapped[str] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(Text(), nullable=False)
    focus_topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date(), nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date(), nullable=False)


class DailyTaskModel(Base):
    __tablename__ = "daily_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    study_plan_id: Mapped[str] = mapped_column(ForeignKey("study_plans.id"), nullable=False)
    plan_stage_id: Mapped[str | None] = mapped_column(ForeignKey("plan_stages.id"), nullable=True)
    task_origin: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str] = mapped_column(Text(), nullable=False)
    topic_focus: Mapped[str] = mapped_column(String(255), nullable=False)
    difficulty: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_count: Mapped[int | None] = mapped_column(nullable=True)
    estimated_minutes: Mapped[int] = mapped_column(nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(Date(), nullable=False)
    due_on: Mapped[datetime] = mapped_column(Date(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    execution_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    study_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    daily_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(ForeignKey("autonomy_jobs.id"), nullable=True)
    result_resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_resource_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoalAutonomyStateModel(Base):
    __tablename__ = "goal_autonomy_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False, unique=True)
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    current_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    availability_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    mastery_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    last_transition_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_transition_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScheduledAutonomyJobModel(Base):
    __tablename__ = "autonomy_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryMaintenanceJobModel(Base):
    __tablename__ = "memory_maintenance_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    cursor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_memory_maintenance_jobs_status_due",
    MemoryMaintenanceJobModel.status,
    MemoryMaintenanceJobModel.due_at,
)
Index(
    "ix_memory_maintenance_jobs_profile_type_status",
    MemoryMaintenanceJobModel.learner_profile_id,
    MemoryMaintenanceJobModel.job_type,
    MemoryMaintenanceJobModel.status,
)


class LearnerAvailabilityModel(Base):
    __tablename__ = "learner_availabilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False, unique=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available_days: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    time_windows: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    max_daily_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_session_length_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearnerTopicMasteryModel(Base):
    __tablename__ = "learner_topic_masteries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    topic_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_attempt_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TaskAttemptModel(Base):
    __tablename__ = "task_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    daily_task_id: Mapped[str] = mapped_column(ForeignKey("daily_tasks.id"), nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    topic_focus: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    result_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionMessageModel(Base):
    __tablename__ = "session_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    content_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_trace: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionMemoryEventModel(Base):
    __tablename__ = "session_memory_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), nullable=False)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_level: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    progress_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    struggle_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    concept_focus: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("session_messages.id"),
        nullable=True,
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionMemoryEmbeddingModel(Base):
    __tablename__ = "session_memory_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_event_id: Mapped[str] = mapped_column(
        ForeignKey("session_memory_events.id"),
        nullable=False,
        unique=True,
    )
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), nullable=False)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    memory_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_level: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeMemoryModel(Base):
    __tablename__ = "knowledge_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    knowledge_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    details: Mapped[str | None] = mapped_column(Text(), nullable=True)
    knowledge_level: Mapped[str] = mapped_column(String(32), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False)
    goal_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_contradicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promotion_state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    suppressed_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prerequisite_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    compressed_into_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_memories.id"), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    prerequisite_weight: Mapped[float] = mapped_column(Float, nullable=False)
    assessment_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    task_evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_category: Mapped[str] = mapped_column(String(64), nullable=False, default="concept")
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unverified")
    provenance_type: Mapped[str] = mapped_column(String(64), nullable=False, default="system_inference")
    provenance_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    promotion_rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeMemoryEmbeddingModel(Base):
    __tablename__ = "knowledge_memory_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("knowledge_memories.id"), nullable=False, unique=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    knowledge_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    knowledge_level: Mapped[str] = mapped_column(String(32), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False)
    goal_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BehaviorMemoryModel(Base):
    __tablename__ = "behavior_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    behavior_key: Mapped[str] = mapped_column(String(255), nullable=False)
    behavior_category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    details: Mapped[str | None] = mapped_column(Text(), nullable=True)
    behavior_level: Mapped[str] = mapped_column(String(32), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False)
    goal_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    contradiction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_supported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_contradicted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promotion_state_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    suppressed_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    intervention_effect: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    compressed_into_id: Mapped[str | None] = mapped_column(ForeignKey("behavior_memories.id"), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    intervention_success_count: Mapped[int] = mapped_column(Integer, nullable=False)
    intervention_failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cross_session_recurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_category: Mapped[str] = mapped_column(String(64), nullable=False, default="strategy")
    validation_status: Mapped[str] = mapped_column(String(64), nullable=False, default="unverified")
    provenance_type: Mapped[str] = mapped_column(String(64), nullable=False, default="system_inference")
    provenance_source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope_ref: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    promotion_rationale: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BehaviorMemoryEmbeddingModel(Base):
    __tablename__ = "behavior_memory_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("behavior_memories.id"), nullable=False, unique=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    behavior_key: Mapped[str] = mapped_column(String(255), nullable=False)
    behavior_category: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    behavior_level: Mapped[str] = mapped_column(String(32), nullable=False)
    time_horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False)
    goal_relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionQuizModel(Base):
    __tablename__ = "session_quizzes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("learning_sessions.id"), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(64), nullable=False)
    question_count: Mapped[int] = mapped_column(nullable=False)
    skill_trace: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEvidenceLinkModel(Base):
    __tablename__ = "memory_evidence_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    evidence_source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryGovernanceDecisionModel(Base):
    __tablename__ = "memory_governance_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)




class MemoryPromotionEligibilityModel(Base):
    __tablename__ = "memory_promotion_eligibility_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(ForeignKey("knowledge_memories.id"), nullable=False)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    independent_source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    high_signal_source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_span_hours: Mapped[float] = mapped_column(Float, nullable=False)
    conflict_blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    blocked_conflict_set_id: Mapped[str | None] = mapped_column(ForeignKey("memory_conflict_sets.id"), nullable=True)
    blocked_memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryAnnotationModel(Base):
    __tablename__ = "memory_annotations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    annotation_code: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[str] = mapped_column(Text(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryConflictSetModel(Base):
    __tablename__ = "memory_conflict_sets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    topic_key: Mapped[str] = mapped_column(String(255), nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    handling_result: Mapped[str] = mapped_column(String(128), nullable=False)
    status_impact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryConflictMemberModel(Base):
    __tablename__ = "memory_conflict_members"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conflict_set_id: Mapped[str] = mapped_column(ForeignKey("memory_conflict_sets.id"), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_key: Mapped[str] = mapped_column(String(255), nullable=False)
    stance: Mapped[str] = mapped_column(String(32), nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False)
    contradiction_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_CURRENT_MEMORY_IDENTITY_STATUSES = ("candidate", "active", "stable", "suppressed")

Index(
    "uq_knowledge_memories_current_identity",
    KnowledgeMemoryModel.learner_profile_id,
    func.coalesce(KnowledgeMemoryModel.learner_goal_id, literal_column("''")),
    KnowledgeMemoryModel.knowledge_key,
    KnowledgeMemoryModel.semantic_category,
    unique=True,
    postgresql_where=KnowledgeMemoryModel.status.in_(_CURRENT_MEMORY_IDENTITY_STATUSES),
    sqlite_where=KnowledgeMemoryModel.status.in_(_CURRENT_MEMORY_IDENTITY_STATUSES),
)
Index(
    "uq_behavior_memories_current_identity",
    BehaviorMemoryModel.learner_profile_id,
    func.coalesce(BehaviorMemoryModel.learner_goal_id, literal_column("''")),
    BehaviorMemoryModel.behavior_key,
    BehaviorMemoryModel.behavior_category,
    unique=True,
    postgresql_where=BehaviorMemoryModel.status.in_(_CURRENT_MEMORY_IDENTITY_STATUSES),
    sqlite_where=BehaviorMemoryModel.status.in_(_CURRENT_MEMORY_IDENTITY_STATUSES),
)
Index(
    "uq_memory_evidence_links_identity",
    MemoryEvidenceLinkModel.memory_type,
    MemoryEvidenceLinkModel.memory_id,
    MemoryEvidenceLinkModel.evidence_source_type,
    MemoryEvidenceLinkModel.evidence_source_id,
    MemoryEvidenceLinkModel.evidence_role,
    unique=True,
)
Index(
    "uq_memory_conflict_sets_open_identity",
    MemoryConflictSetModel.learner_profile_id,
    func.coalesce(MemoryConflictSetModel.learner_goal_id, literal_column("''")),
    MemoryConflictSetModel.topic_key,
    MemoryConflictSetModel.conflict_type,
    unique=True,
    postgresql_where=MemoryConflictSetModel.status == "open",
    sqlite_where=MemoryConflictSetModel.status == "open",
)
Index(
    "ix_memory_promotion_eligibility_current_memory",
    MemoryPromotionEligibilityModel.memory_id,
    unique=True,
    postgresql_where=MemoryPromotionEligibilityModel.superseded_at.is_(None),
    sqlite_where=MemoryPromotionEligibilityModel.superseded_at.is_(None),
)
Index(
    "ix_memory_promotion_eligibility_profile_goal_status",
    MemoryPromotionEligibilityModel.learner_profile_id,
    MemoryPromotionEligibilityModel.learner_goal_id,
    MemoryPromotionEligibilityModel.status,
    MemoryPromotionEligibilityModel.evaluated_at,
)


class SessionQuizQuestionModel(Base):
    __tablename__ = "session_quiz_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("session_quizzes.id"), nullable=False)
    position: Mapped[int] = mapped_column(nullable=False)
    prompt: Mapped[str] = mapped_column(Text(), nullable=False)
    answer: Mapped[str] = mapped_column(Text(), nullable=False)


class SkillArtifactModel(Base):
    __tablename__ = "skill_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("skill_artifacts.id"), nullable=True)
    supersedes_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("skill_artifacts.id"), nullable=True)
    skill_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text(), nullable=False)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    runtime_directives: Mapped[dict] = mapped_column(JSON, nullable=False)
    tool_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    compatibility_contract: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_reflection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_proposal_id: Mapped[str | None] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=True)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suppressed_previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("uq_skill_artifacts_name_version", SkillArtifactModel.name, SkillArtifactModel.version, unique=True)
Index("ix_skill_artifacts_status_name", SkillArtifactModel.status, SkillArtifactModel.name)
Index("ix_skill_artifacts_lineage_updated", SkillArtifactModel.lineage_id, SkillArtifactModel.updated_at)
Index(
    "uq_skill_artifacts_selectable_name_scope",
    SkillArtifactModel.name,
    SkillArtifactModel.scope,
    unique=True,
    postgresql_where=SkillArtifactModel.status.in_(["active", "stable"]),
    sqlite_where=SkillArtifactModel.status.in_(["active", "stable"]),
)
Index(
    "uq_skill_artifacts_suppressed_name_scope",
    SkillArtifactModel.name,
    SkillArtifactModel.scope,
    unique=True,
    postgresql_where=SkillArtifactModel.status == "suppressed",
    sqlite_where=SkillArtifactModel.status == "suppressed",
)


class SkillUsageEventModel(Base):
    __tablename__ = "skill_usage_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("skill_artifacts.id"), nullable=True)
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    skill_status_at_use: Mapped[str | None] = mapped_column(String(32), nullable=True)
    learner_profile_id: Mapped[str | None] = mapped_column(ForeignKey("learner_profiles.id"), nullable=True)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("learning_sessions.id"), nullable=True)
    daily_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True)
    surface: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trigger_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    output_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolver_status: Mapped[str] = mapped_column(String(32), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_signals: Mapped[dict] = mapped_column(JSON, nullable=False)
    usage_metadata: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index("ix_skill_usage_events_artifact_created", SkillUsageEventModel.skill_artifact_id, SkillUsageEventModel.created_at)
Index(
    "ix_skill_usage_events_goal_surface_created",
    SkillUsageEventModel.learner_goal_id,
    SkillUsageEventModel.surface,
    SkillUsageEventModel.created_at,
)
Index("ix_skill_usage_events_session_created", SkillUsageEventModel.session_id, SkillUsageEventModel.created_at)


class SkillCuratorRecommendationModel(Base):
    __tablename__ = "skill_curator_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("skill_artifacts.id"), nullable=True)
    skill_name: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    lineage_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    surface: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    metrics_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    related_artifact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    decision_reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    action_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


Index(
    "ix_skill_curator_recs_status_type_created",
    SkillCuratorRecommendationModel.status,
    SkillCuratorRecommendationModel.recommendation_type,
    SkillCuratorRecommendationModel.created_at,
)
Index(
    "ix_skill_curator_recs_artifact_status_created",
    SkillCuratorRecommendationModel.artifact_id,
    SkillCuratorRecommendationModel.status,
    SkillCuratorRecommendationModel.created_at,
)
Index(
    "ix_skill_curator_recs_skill_scope_surface_status",
    SkillCuratorRecommendationModel.skill_name,
    SkillCuratorRecommendationModel.scope,
    SkillCuratorRecommendationModel.surface,
    SkillCuratorRecommendationModel.status,
)


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    event_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionRecordModel(Base):
    __tablename__ = "reflection_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    daily_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True)
    study_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reflection_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    aggregation_key: Mapped[str] = mapped_column(String(255), nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_duplicate_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    primary_root_cause: Mapped[str] = mapped_column(String(64), nullable=False)
    secondary_root_causes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    recommended_next_step: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReflectionActionModel(Base):
    __tablename__ = "reflection_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reflection_record_id: Mapped[str] = mapped_column(ForeignKey("reflection_records.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_required: Mapped[bool] = mapped_column(nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    execution_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReflectionEvidenceSignalModel(Base):
    __tablename__ = "reflection_evidence_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("learning_sessions.id"), nullable=True)
    daily_task_id: Mapped[str | None] = mapped_column(ForeignKey("daily_tasks.id"), nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    signal_code: Mapped[str] = mapped_column(String(128), nullable=False)
    topic_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    severity_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionOutcomeEvaluationModel(Base):
    __tablename__ = "reflection_outcome_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reflection_record_id: Mapped[str] = mapped_column(ForeignKey("reflection_records.id"), nullable=False, unique=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    topic_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evaluation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    outcome_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    improvement_score: Mapped[float] = mapped_column(Float, nullable=False)
    evaluation_note: Mapped[str] = mapped_column(Text(), nullable=False)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionReviewDecisionModel(Base):
    __tablename__ = "reflection_review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reflection_record_id: Mapped[str] = mapped_column(ForeignKey("reflection_records.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_root_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_root_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_action_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_action_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    operator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LearnerGoalStrategyCardModel(Base):
    __tablename__ = "learner_goal_strategy_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reflection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    primary_instruction_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    difficulty_bias: Mapped[str] = mapped_column(String(32), nullable=False)
    review_bias: Mapped[str] = mapped_column(String(32), nullable=False)
    replan_bias: Mapped[str] = mapped_column(String(32), nullable=False)
    assessment_bias: Mapped[str] = mapped_column(String(32), nullable=False)
    intervention_policy: Mapped[dict] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text(), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectiveMemoryModel(Base):
    __tablename__ = "reflective_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    learner_profile_id: Mapped[str] = mapped_column(ForeignKey("learner_profiles.id"), nullable=False)
    learner_goal_id: Mapped[str | None] = mapped_column(ForeignKey("learner_goals.id"), nullable=True)
    reflection_record_id: Mapped[str] = mapped_column(ForeignKey("reflection_records.id"), nullable=False)
    memory_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    details: Mapped[str] = mapped_column(Text(), nullable=False)
    memory_level: Mapped[str] = mapped_column(String(32), nullable=False)
    importance_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_score: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reflection_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_action_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalModel(Base):
    __tablename__ = "reflection_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reflection_record_id: Mapped[str] = mapped_column(ForeignKey("reflection_records.id"), nullable=False)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text(), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text(), nullable=False)
    structured_patch_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_improvement: Mapped[str] = mapped_column(Text(), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    evaluation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evaluation_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    latest_sandbox_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_reason_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    proposal_bundle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalEvaluationModel(Base):
    __tablename__ = "reflection_proposal_evaluations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False, unique=True)
    evaluation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    comparison_window_size: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_policy_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    simulated_outcome_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    score_delta: Mapped[float] = mapped_column(Float, nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sandbox_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalSandboxRunModel(Base):
    __tablename__ = "reflection_proposal_sandbox_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evaluator_type: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    score_delta: Mapped[float] = mapped_column(Float, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalApprovalDecisionModel(Base):
    __tablename__ = "reflection_proposal_approval_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    operator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalRolloutModel(Base):
    __tablename__ = "reflection_proposal_rollouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False, unique=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    baseline_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    runtime_overlay_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    latest_observation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    staged_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    rollback_restored_plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), nullable=True)
    activated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalRolloutObservationModel(Base):
    __tablename__ = "reflection_proposal_rollout_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rollout_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposal_rollouts.id"), nullable=False)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_score: Mapped[float] = mapped_column(Float, nullable=False)
    negative_score: Mapped[float] = mapped_column(Float, nullable=False)
    signal_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReflectionProposalRolloutDecisionModel(Base):
    __tablename__ = "reflection_proposal_rollout_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rollout_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposal_rollouts.id"), nullable=False)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(32), nullable=False)
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    operator_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class GoalSkillBindingModel(Base):
    __tablename__ = "goal_skill_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposals.id"), nullable=False)
    rollout_id: Mapped[str] = mapped_column(ForeignKey("reflection_proposal_rollouts.id"), nullable=False, unique=True)
    learner_goal_id: Mapped[str] = mapped_column(ForeignKey("learner_goals.id"), nullable=False)
    surface: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    match_rules: Mapped[dict] = mapped_column(JSON, nullable=False)
    runtime_directives: Mapped[dict] = mapped_column(JSON, nullable=False)
    tool_plan: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
