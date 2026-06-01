from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_core.domain.schemas.session import ExplanationPayload, MessageRequest
from agent_core.domain.schemas.session import SessionResponse


def test_session_response_contains_session_metadata():
    payload = SessionResponse.model_validate(
        {
            "id": "session-1",
            "learner_profile_id": "profile-1",
            "title": "Algebra",
            "subject": "Vectors",
            "status": "active",
            "message_count": 2,
            "last_activity_at": datetime.now(timezone.utc),
            "summary": "User is learning vector basics.",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )

    assert payload.message_count == 2
    assert payload.summary == "User is learning vector basics."
    assert payload.status == "active"


def test_message_request_rejects_unsupported_mode():
    with pytest.raises(ValidationError):
        MessageRequest(content="Explain this.", mode="quiz")


def test_explanation_payload_requires_non_empty_structure():
    payload = ExplanationPayload(
        definition="Vector is a directed quantity.",
        core_principles=["Magnitude and direction both matter."],
        worked_example="A displacement vector moves 3 units right.",
        common_mistake="Treating a vector as only a number.",
        next_step="Compare vectors with scalars.",
    )

    assert payload.type == "explanation"
    assert payload.core_principles == ["Magnitude and direction both matter."]
