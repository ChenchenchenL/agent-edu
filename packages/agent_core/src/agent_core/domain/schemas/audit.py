from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    resource_type: str
    resource_id: str | None
    actor: str
    event_data: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
