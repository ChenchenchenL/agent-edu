from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class AuditEvent:
    id: str
    event_type: str
    resource_type: str
    resource_id: str | None
    actor: str
    event_data: dict[str, Any]
    created_at: datetime

    @classmethod
    def build(
        cls,
        *,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        actor: str,
        event_data: dict[str, Any],
    ) -> "AuditEvent":
        return cls(
            id=str(uuid4()),
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            event_data=event_data,
            created_at=datetime.now(timezone.utc),
        )
