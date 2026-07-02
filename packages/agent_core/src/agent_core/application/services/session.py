from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.session import LearningSession, SESSION_STATUSES
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.session import (
    CreateSessionRequest,
    SessionResponse,
    UpdateSessionStatusRequest,
)
from agent_core.infrastructure.db.repositories import LearnerGoalRepository, LearnerProfileRepository, SessionRepository


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        learner_profile_repository: LearnerProfileRepository,
        learner_goal_repository: LearnerGoalRepository,
        db_session: AsyncSession,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._learner_profile_repository = learner_profile_repository
        self._learner_goal_repository = learner_goal_repository
        self._db_session = db_session
        self._audit_service = audit_service

    async def create_session(
        self,
        payload: CreateSessionRequest,
        daily_task_id: str | None = None,
        goal: LearnerGoal | None = None,
        commit: bool = True,
    ) -> SessionResponse:
        learner_profile = None
        learner_profile_id = payload.learner_profile_id
        learner_goal_id = payload.learner_goal_id or (goal.id if goal is not None else None)
        if goal is None and learner_goal_id is not None:
            goal = await self._learner_goal_repository.get_by_id(learner_goal_id)
            if goal is None:
                raise NotFoundError(f"Learner goal '{learner_goal_id}' was not found.")
        if goal is not None:
            if learner_profile_id is not None and learner_profile_id != goal.learner_profile_id:
                raise ValidationError("learner_profile_id does not match learner_goal_id.")
            learner_profile_id = goal.learner_profile_id
        if learner_profile_id is None:
            learner_profile = LearnerProfile.build()
            learner_profile_id = learner_profile.id
        else:
            existing_profile = await self._learner_profile_repository.get_by_id(learner_profile_id)
            if existing_profile is None:
                raise NotFoundError(f"Learner profile '{learner_profile_id}' was not found.")
        session = LearningSession.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            title=payload.title,
            subject=payload.subject,
        )
        try:
            if learner_profile is not None:
                await self._learner_profile_repository.create(learner_profile)
            await self._repository.create(session)
            await self._audit_service.record(
                event_type="session.created",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "learner_goal_id": session.learner_goal_id,
                    "daily_task_id": session.daily_task_id,
                    "title": session.title,
                    "subject": session.subject,
                    "status": session.status,
                },
            )
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="session.create.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "learner_goal_id": session.learner_goal_id,
                    "daily_task_id": session.daily_task_id,
                    "title": session.title,
                    "subject": session.subject,
                    "error": str(exc),
                },
            )
            raise
        return SessionResponse.model_validate(session)

    async def list_sessions(self) -> list[SessionResponse]:
        sessions = await self._repository.list_sessions()
        return [SessionResponse.model_validate(session) for session in sessions]

    async def get_session(self, session_id: str) -> SessionResponse:
        session = await self._repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")
        return SessionResponse.model_validate(session)

    async def update_session_status(
        self,
        session_id: str,
        payload: UpdateSessionStatusRequest,
        commit: bool = True,
    ) -> SessionResponse:
        if payload.status not in SESSION_STATUSES:
            raise ValidationError(
                "Unsupported session status. Expected one of: active, archived, completed."
            )

        session = await self._repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")

        updated = session.with_status(payload.status)
        try:
            await self._repository.update(updated)
            await self._audit_service.record(
                event_type="session.status.updated",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "previous_status": session.status,
                    "new_status": updated.status,
                },
            )
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="session.status.update.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "session_id": session.id,
                    "learner_profile_id": session.learner_profile_id,
                    "previous_status": session.status,
                    "requested_status": payload.status,
                    "error": str(exc),
                },
            )
            raise
        return SessionResponse.model_validate(updated)

    async def bind_goal(
        self,
        session_id: str,
        learner_goal_id: str | None,
        commit: bool = True,
    ) -> SessionResponse:
        session = await self._repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")

        if learner_goal_id is not None:
            goal = await self._learner_goal_repository.get_by_id(learner_goal_id)
            if goal is None:
                raise NotFoundError(f"Learner goal '{learner_goal_id}' was not found.")
            if goal.learner_profile_id != session.learner_profile_id:
                raise ValidationError("Goal does not belong to the same learner profile.")

        updated = session.with_goal(learner_goal_id)
        try:
            await self._repository.update(updated)
            await self._audit_service.record(
                event_type="session.goal.bound",
                resource_type="learning_session",
                resource_id=session.id,
                actor="learner",
                event_data={
                    "session_id": session.id,
                    "previous_goal_id": session.learner_goal_id,
                    "new_goal_id": learner_goal_id,
                },
            )
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            raise
        return SessionResponse.model_validate(updated)
