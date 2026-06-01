from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4


@dataclass(frozen=True)
class LearnerProfile:
    id: str
    created_at: datetime
    updated_at: datetime
    access_key_hash: str | None = None
    access_key_created_at: datetime | None = None

    @classmethod
    def build(
        cls,
        *,
        access_key_hash: str | None = None,
        access_key_created_at: datetime | None = None,
    ) -> "LearnerProfile":
        now = datetime.now(timezone.utc)
        return cls(
            id=str(uuid4()),
            created_at=now,
            updated_at=now,
            access_key_hash=access_key_hash,
            access_key_created_at=access_key_created_at,
        )

    def with_access_key_hash(self, access_key_hash: str, access_key_created_at: datetime) -> "LearnerProfile":
        return LearnerProfile(
            id=self.id,
            created_at=self.created_at,
            updated_at=access_key_created_at,
            access_key_hash=access_key_hash,
            access_key_created_at=access_key_created_at,
        )
