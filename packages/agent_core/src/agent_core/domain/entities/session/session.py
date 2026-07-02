from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

SESSION_STATUSES = {"active", "archived", "completed"}


@dataclass(frozen=True)
class LearningSession:
    id: str
    learner_profile_id: str
    learner_goal_id: str | None
    daily_task_id: str | None
    title: str | None
    subject: str | None
    status: str
    message_count: int
    last_activity_at: datetime
    summary: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        daily_task_id: str | None = None,
        title: str | None,
        subject: str | None,
    ) -> "LearningSession":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            title=title,
            subject=subject,
            status="active",
            message_count=0,
            last_activity_at=now,
            summary=None,
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: str) -> "LearningSession":
        if status not in SESSION_STATUSES:
            raise ValueError(f"Unsupported session status: {status}")

        now = datetime.now(timezone.utc)
        return LearningSession(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            daily_task_id=self.daily_task_id,
            title=self.title,
            subject=self.subject,
            status=status,
            message_count=self.message_count,
            last_activity_at=self.last_activity_at,
            summary=self.summary,
            created_at=self.created_at,
            updated_at=now,
        )

    def with_message_activity(
        self,
        *,
        message_count_delta: int,
        last_activity_at: datetime,
        summary: str | None,
    ) -> "LearningSession":
        return LearningSession(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=self.learner_goal_id,
            daily_task_id=self.daily_task_id,
            title=self.title,
            subject=self.subject,
            status=self.status,
            message_count=self.message_count + message_count_delta,
            last_activity_at=last_activity_at,
            summary=summary,
            created_at=self.created_at,
            updated_at=last_activity_at,
        )

    def with_goal(self, learner_goal_id: str | None) -> "LearningSession":
        now = datetime.now(timezone.utc)
        return LearningSession(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=self.daily_task_id,
            title=self.title,
            subject=self.subject,
            status=self.status,
            message_count=self.message_count,
            last_activity_at=self.last_activity_at,
            summary=self.summary,
            created_at=self.created_at,
            updated_at=now,
        )
