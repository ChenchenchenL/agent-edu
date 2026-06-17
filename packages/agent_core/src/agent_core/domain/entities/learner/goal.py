from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

from agent_core.domain.errors import ValidationError

GOAL_STATUSES = {"active", "paused", "completed", "archived"}


@dataclass(frozen=True)
class LearnerGoal:
    id: str
    learner_profile_id: str
    title: str
    subject: str
    target_outcome: str
    baseline_note: str | None
    deadline_date: date
    weekly_study_minutes: int
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        title: str,
        subject: str,
        target_outcome: str,
        baseline_note: str | None,
        deadline_date: date,
        weekly_study_minutes: int,
    ) -> "LearnerGoal":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            title=title,
            subject=subject,
            target_outcome=target_outcome,
            baseline_note=baseline_note,
            deadline_date=deadline_date,
            weekly_study_minutes=weekly_study_minutes,
            status="active",
            created_at=now,
            updated_at=now,
        )

    def with_status(self, status: str) -> "LearnerGoal":
        if status not in GOAL_STATUSES:
            raise ValidationError("Unsupported learner goal status.")

        return LearnerGoal(
            id=self.id,
            learner_profile_id=self.learner_profile_id,
            title=self.title,
            subject=self.subject,
            target_outcome=self.target_outcome,
            baseline_note=self.baseline_note,
            deadline_date=self.deadline_date,
            weekly_study_minutes=self.weekly_study_minutes,
            status=status,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )
