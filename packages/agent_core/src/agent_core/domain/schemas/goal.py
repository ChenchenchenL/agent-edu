from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class CreateLearnerProfileRequest(BaseModel):
    model_config = {"extra": "forbid"}


class LearnerProfileResponse(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CreateLearnerProfileResponse(LearnerProfileResponse):
    access_key: str


class CreateLearnerGoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    target_outcome: str = Field(min_length=1, max_length=1000)
    baseline_note: str | None = Field(default=None, max_length=2000)
    deadline_date: date
    weekly_study_minutes: int = Field(ge=60, le=1200)
    preferred_language: str = Field(default="zh", min_length=1, max_length=16)


class UpdateLearnerGoalStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=32)


class LearnerGoalResponse(BaseModel):
    id: str
    learner_profile_id: str
    title: str
    subject: str
    target_outcome: str
    baseline_note: str | None
    deadline_date: date
    weekly_study_minutes: int
    preferred_language: str = "zh"
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
