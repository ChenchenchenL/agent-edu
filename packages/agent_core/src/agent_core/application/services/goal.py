from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.autonomy import GoalAutonomyState, LearnerAvailability
from agent_core.domain.entities.goal import GOAL_STATUSES, LearnerGoal
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.goal import (
    CreateLearnerGoalRequest,
    LearnerGoalResponse,
    UpdateLearnerGoalStatusRequest,
)
from agent_core.infrastructure.db.repositories import (
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerProfileRepository,
)


class LearnerGoalService:
    def __init__(
        self,
        *,
        repository: LearnerGoalRepository,
        learner_profile_repository: LearnerProfileRepository,
        db_session: AsyncSession,
        audit_service: AuditService,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None = None,
        learner_availability_repository: LearnerAvailabilityRepository | None = None,
    ) -> None:
        self._repository = repository
        self._learner_profile_repository = learner_profile_repository
        self._db_session = db_session
        self._audit_service = audit_service
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._learner_availability_repository = learner_availability_repository

    async def create_goal(
        self,
        *,
        learner_profile_id: str,
        payload: CreateLearnerGoalRequest,
    ) -> LearnerGoalResponse:
        profile = await self._learner_profile_repository.get_by_id(learner_profile_id)
        if profile is None:
            raise NotFoundError(f"Learner profile '{learner_profile_id}' was not found.")
        self._validate_deadline(payload.deadline_date)
        goal = LearnerGoal.build(
            learner_profile_id=learner_profile_id,
            title=payload.title,
            subject=payload.subject,
            target_outcome=payload.target_outcome,
            baseline_note=payload.baseline_note,
            deadline_date=payload.deadline_date,
            weekly_study_minutes=payload.weekly_study_minutes,
        )
        try:
            await self._repository.create(goal)
            await self._bootstrap_autonomy(goal)
            await self._audit_service.record(
                event_type="learner_goal.created",
                resource_type="learner_goal",
                resource_id=goal.id,
                actor="learner",
                event_data={
                    "learner_goal_id": goal.id,
                    "learner_profile_id": learner_profile_id,
                    "subject": goal.subject,
                    "deadline_date": goal.deadline_date.isoformat(),
                    "weekly_study_minutes": goal.weekly_study_minutes,
                },
            )
            await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="learner_goal.create.failed",
                resource_type="learner_goal",
                resource_id=goal.id,
                actor="learner",
                event_data={
                    "learner_goal_id": goal.id,
                    "learner_profile_id": learner_profile_id,
                    "subject": goal.subject,
                    "deadline_date": goal.deadline_date.isoformat(),
                    "weekly_study_minutes": goal.weekly_study_minutes,
                    "error": str(exc),
                },
            )
            raise
        return LearnerGoalResponse.model_validate(goal)

    async def list_goals(self, learner_profile_id: str) -> list[LearnerGoalResponse]:
        profile = await self._learner_profile_repository.get_by_id(learner_profile_id)
        if profile is None:
            raise NotFoundError(f"Learner profile '{learner_profile_id}' was not found.")
        goals = await self._repository.list_by_profile(learner_profile_id)
        return [LearnerGoalResponse.model_validate(item) for item in goals]

    async def get_goal(self, goal_id: str) -> LearnerGoalResponse:
        goal = await self._repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return LearnerGoalResponse.model_validate(goal)

    async def update_goal_status(
        self,
        *,
        goal_id: str,
        payload: UpdateLearnerGoalStatusRequest,
    ) -> LearnerGoalResponse:
        if payload.status not in GOAL_STATUSES:
            raise ValidationError("Unsupported learner goal status.")
        goal = await self._repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        updated = goal.with_status(payload.status)
        try:
            await self._repository.update(updated)
            await self._sync_goal_autonomy_status(updated)
            await self._audit_service.record(
                event_type="learner_goal.status.updated",
                resource_type="learner_goal",
                resource_id=updated.id,
                actor="learner",
                event_data={
                    "learner_goal_id": updated.id,
                    "learner_profile_id": updated.learner_profile_id,
                    "previous_status": goal.status,
                    "new_status": updated.status,
                },
            )
            await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="learner_goal.status.update.failed",
                resource_type="learner_goal",
                resource_id=updated.id,
                actor="learner",
                event_data={
                    "learner_goal_id": updated.id,
                    "learner_profile_id": updated.learner_profile_id,
                    "previous_status": goal.status,
                    "requested_status": payload.status,
                    "error": str(exc),
                },
            )
            raise
        return LearnerGoalResponse.model_validate(updated)

    @staticmethod
    def _validate_deadline(deadline_date: date) -> None:
        minimum_deadline = date.today() + timedelta(days=7)
        if deadline_date < minimum_deadline:
            raise ValidationError("deadline_date must be at least 7 days from today.")

    async def _bootstrap_autonomy(self, goal: LearnerGoal) -> None:
        if self._goal_autonomy_state_repository is not None:
            existing_state = await self._goal_autonomy_state_repository.get_by_goal(goal.id)
            if existing_state is None:
                await self._goal_autonomy_state_repository.create(GoalAutonomyState.build(learner_goal_id=goal.id))
        if self._learner_availability_repository is not None:
            existing_availability = await self._learner_availability_repository.get_by_goal(goal.id)
            if existing_availability is None:
                await self._learner_availability_repository.upsert(
                    LearnerAvailability.build(
                        learner_goal_id=goal.id,
                        max_daily_minutes=max(20, goal.weekly_study_minutes // 7),
                        preferred_session_length_minutes=max(20, goal.weekly_study_minutes // 7),
                    )
                )

    async def _sync_goal_autonomy_status(self, goal: LearnerGoal) -> None:
        if self._goal_autonomy_state_repository is None:
            return
        state = await self._goal_autonomy_state_repository.get_by_goal(goal.id)
        if state is None:
            await self._goal_autonomy_state_repository.create(GoalAutonomyState.build(learner_goal_id=goal.id))
            state = await self._goal_autonomy_state_repository.get_by_goal(goal.id)
        if state is None:
            return
        target_phase = {
            "active": "active",
            "paused": "paused",
            "completed": "completed",
            "archived": "archived",
        }.get(goal.status)
        if target_phase is None or state.phase == target_phase:
            return
        await self._goal_autonomy_state_repository.update(
            state.with_transition(phase=target_phase, reason=f"goal_status:{goal.status}")
        )
