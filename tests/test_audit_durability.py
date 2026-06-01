from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.application.services.audit import AuditService
from agent_core.application.services.session import SessionService
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.schemas.session import UpdateSessionStatusRequest
from agent_core.infrastructure.db.base import Base
from agent_core.infrastructure.db.models import AuditEventModel, LearningSessionModel
from agent_core.infrastructure.db.repositories import AuditRepository, LearnerGoalRepository, LearnerProfileRepository, SessionRepository


class FailingSessionUpdateRepository:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def get_by_id(self, session_id: str) -> LearningSession | None:
        return await self._repository.get_by_id(session_id)

    async def update(self, entity: LearningSession) -> None:
        raise RuntimeError("simulated update failure")


@pytest.mark.asyncio
async def test_durable_audit_survives_session_update_rollback(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'audit-durable.db'}"
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        session_entity = LearningSession.build(
            learner_profile_id="profile-seed",
            title="Algebra",
            subject="Equations",
        )
        learner_profile = LearnerProfile(
            id=session_entity.learner_profile_id,
            created_at=session_entity.created_at,
            updated_at=session_entity.updated_at,
        )

        async with session_factory() as seed_session:
            await LearnerProfileRepository(seed_session).create(learner_profile)
            await SessionRepository(seed_session).create(session_entity)
            await seed_session.commit()

        async with session_factory() as session:
            service = SessionService(
                FailingSessionUpdateRepository(SessionRepository(session)),
                LearnerProfileRepository(session),
                LearnerGoalRepository(session),
                session,
                AuditService(AuditRepository(session), session_factory),
            )

            with pytest.raises(RuntimeError, match="simulated update failure"):
                await service.update_session_status(
                    session_entity.id,
                    UpdateSessionStatusRequest(status="archived"),
                )

        async with session_factory() as verification_session:
            stored_session = await verification_session.get(LearningSessionModel, session_entity.id)
            assert stored_session is not None
            assert stored_session.status == "active"

            result = await verification_session.execute(
                select(AuditEventModel).where(
                    AuditEventModel.event_type == "session.status.update.failed"
                )
            )
            audit_events = result.scalars().all()
            assert len(audit_events) == 1
            assert audit_events[0].resource_id == session_entity.id
            assert audit_events[0].event_data["requested_status"] == "archived"
    finally:
        await engine.dispose()
