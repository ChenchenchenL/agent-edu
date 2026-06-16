from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class SessionMessage:
    id: str
    session_id: str
    role: str
    content: str
    mode: str | None
    skill_trace: list[str]
    created_at: datetime
    content_payload: dict[str, Any] | None = None

    @classmethod
    def build(
        cls,
        *,
        session_id: str,
        role: str,
        content: str,
        mode: str | None,
        skill_trace: list[str],
        content_payload: dict[str, Any] | None = None,
    ) -> "SessionMessage":
        return cls(
            id=str(uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            mode=mode,
            skill_trace=skill_trace,
            created_at=datetime.now(timezone.utc),
            content_payload=content_payload,
        )
