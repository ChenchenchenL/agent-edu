from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.profile_access import generate_profile_access_key, hash_profile_access_key
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.goal import CreateLearnerProfileResponse, LearnerProfileResponse
from agent_core.infrastructure.db.repositories import LearnerProfileRepository


class LearnerProfileService:
    def __init__(
        self,
        repository: LearnerProfileRepository,
        db_session: AsyncSession,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._db_session = db_session
        self._audit_service = audit_service

    async def create_profile(self) -> CreateLearnerProfileResponse:
        access_key = generate_profile_access_key()
        access_key_hash = hash_profile_access_key(access_key)
        profile = LearnerProfile.build()
        profile = profile.with_access_key_hash(
            access_key_hash,
            profile.created_at,
        )
        try:
            await self._repository.create(profile)
            await self._audit_service.record(
                event_type="learner_profile.created",
                resource_type="learner_profile",
                resource_id=profile.id,
                actor="learner",
                event_data={"learner_profile_id": profile.id},
            )
            await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="learner_profile.create.failed",
                resource_type="learner_profile",
                resource_id=profile.id,
                actor="learner",
                event_data={
                    "learner_profile_id": profile.id,
                    "error": str(exc),
                },
            )
            raise
        return CreateLearnerProfileResponse(
            **LearnerProfileResponse.model_validate(profile).model_dump(),
            access_key=access_key,
        )

    async def list_profiles(self) -> list[LearnerProfileResponse]:
        profiles = await self._repository.list_profiles()
        return [LearnerProfileResponse.model_validate(item) for item in profiles]

    async def get_profile(self, profile_id: str) -> LearnerProfileResponse:
        profile = await self._repository.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError(f"Learner profile '{profile_id}' was not found.")
        return LearnerProfileResponse.model_validate(profile)

    async def rotate_access_key(self, profile_id: str, *, operator_id: str) -> CreateLearnerProfileResponse:
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        profile = await self._repository.get_by_id(profile_id)
        if profile is None:
            raise NotFoundError(f"Learner profile '{profile_id}' was not found.")

        access_key = generate_profile_access_key()
        access_key_created_at = datetime.now(timezone.utc)
        updated = profile.with_access_key_hash(
            hash_profile_access_key(access_key),
            access_key_created_at,
        )
        try:
            await self._repository.update(updated)
            await self._audit_service.record(
                event_type="learner_profile.access_key.rotated",
                resource_type="learner_profile",
                resource_id=profile_id,
                actor=operator_id,
                event_data={"learner_profile_id": profile_id, "operator_id": operator_id},
            )
            await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._audit_service.record_durable(
                event_type="learner_profile.access_key.rotate.failed",
                resource_type="learner_profile",
                resource_id=profile_id,
                actor=operator_id,
                event_data={
                    "learner_profile_id": profile_id,
                    "operator_id": operator_id,
                    "error": str(exc),
                },
            )
            raise
        return CreateLearnerProfileResponse(
            **LearnerProfileResponse.model_validate(updated).model_dump(),
            access_key=access_key,
        )
