"""Repository for SessionQuizAnswerAttempt entities."""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.infrastructure.db.models import SessionQuizAnswerAttemptModel

_MAX_LIST_LIMIT = 200


def _bounded(limit: int | None, default: int = 50) -> int:
    if limit is None:
        return default
    return max(1, min(limit, _MAX_LIST_LIMIT))


class SessionQuizAnswerAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SessionQuizAnswerAttempt) -> None:
        self._session.add(self._to_model(entity))
        await self._session.flush()

    async def get_by_id(self, attempt_id: str) -> SessionQuizAnswerAttempt | None:
        model = await self._session.get(SessionQuizAnswerAttemptModel, attempt_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_quiz(
        self,
        *,
        session_id: str,
        quiz_id: str,
        limit: int = 50,
    ) -> list[SessionQuizAnswerAttempt]:
        bounded = _bounded(limit, default=50)
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(
                SessionQuizAnswerAttemptModel.session_id == session_id,
                SessionQuizAnswerAttemptModel.quiz_id == quiz_id,
            )
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(bounded)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_recent_by_goal_topic(
        self,
        *,
        learner_goal_id: str,
        topic_key: str,
        limit: int = 20,
    ) -> list[SessionQuizAnswerAttempt]:
        bounded = _bounded(limit, default=20)
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(
                SessionQuizAnswerAttemptModel.learner_goal_id == learner_goal_id,
                SessionQuizAnswerAttemptModel.topic_key == topic_key,
            )
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(bounded)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_by_question(self, question_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(SessionQuizAnswerAttemptModel)
            .where(SessionQuizAnswerAttemptModel.question_id == question_id)
        )
        return int(result.scalar_one())

    async def count_all(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(SessionQuizAnswerAttemptModel)
        )
        return int(result.scalar_one())

    async def list_by_learner(
        self,
        *,
        learner_profile_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SessionQuizAnswerAttempt]:
        bounded = max(1, min(limit, 1000))
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(
                SessionQuizAnswerAttemptModel.learner_profile_id == learner_profile_id,
            )
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(bounded)
            .offset(offset)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_needs_review(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SessionQuizAnswerAttempt]:
        bounded = max(1, min(limit, 1000))
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(SessionQuizAnswerAttemptModel.grading_status == "needs_review")
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(bounded)
            .offset(offset)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_recent(
        self, *, limit: int = 1000, offset: int = 0
    ) -> list[SessionQuizAnswerAttempt]:
        bounded = max(1, min(limit, 10000))
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(bounded)
            .offset(offset)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_latest_by_learner(
        self, learner_profile_id: str
    ) -> SessionQuizAnswerAttempt | None:
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(
                SessionQuizAnswerAttemptModel.learner_profile_id == learner_profile_id,
            )
            .order_by(desc(SessionQuizAnswerAttemptModel.created_at))
            .limit(1)
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_last_by_question(
        self, question_id: str
    ) -> SessionQuizAnswerAttempt | None:
        result = await self._session.execute(
            select(SessionQuizAnswerAttemptModel)
            .where(SessionQuizAnswerAttemptModel.question_id == question_id)
            .order_by(desc(SessionQuizAnswerAttemptModel.attempt_number))
            .limit(1)
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    @staticmethod
    def _to_model(entity: SessionQuizAnswerAttempt) -> SessionQuizAnswerAttemptModel:
        return SessionQuizAnswerAttemptModel(
            id=entity.id,
            session_id=entity.session_id,
            quiz_id=entity.quiz_id,
            question_id=entity.question_id,
            learner_profile_id=entity.learner_profile_id,
            learner_goal_id=entity.learner_goal_id,
            daily_task_id=entity.daily_task_id,
            topic_key=entity.topic_key,
            subskill_keys=list(entity.subskill_keys),
            question_prompt=entity.question_prompt,
            reference_answer=entity.reference_answer,
            learner_answer=entity.learner_answer,
            grading_status=entity.grading_status,
            grading_source=entity.grading_source,
            score=entity.score,
            is_correct=entity.is_correct,
            confidence=entity.confidence,
            rubric_feedback=entity.rubric_feedback,
            misconception_codes=list(entity.misconception_codes),
            hint_used=entity.hint_used,
            hint_count=entity.hint_count,
            attempt_number=entity.attempt_number,
            metadata_=dict(entity.metadata),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: SessionQuizAnswerAttemptModel) -> SessionQuizAnswerAttempt:
        return SessionQuizAnswerAttempt(
            id=model.id,
            session_id=model.session_id,
            quiz_id=model.quiz_id,
            question_id=model.question_id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            daily_task_id=model.daily_task_id,
            topic_key=model.topic_key,
            subskill_keys=tuple(model.subskill_keys or ()),
            question_prompt=model.question_prompt,
            reference_answer=model.reference_answer,
            learner_answer=model.learner_answer,
            grading_status=model.grading_status,
            grading_source=model.grading_source,
            score=model.score,
            is_correct=model.is_correct,
            confidence=model.confidence,
            rubric_feedback=model.rubric_feedback,
            misconception_codes=tuple(model.misconception_codes or ()),
            hint_used=model.hint_used,
            hint_count=model.hint_count,
            attempt_number=model.attempt_number,
            metadata=dict(model.metadata_ or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
