from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from agent_core.domain.entities.skill.package import SkillPackage


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reason_code: str
    verified_at: datetime


class SkillPackageVerifier:
    def verify(self, package: SkillPackage) -> VerificationResult:
        now = datetime.now(timezone.utc)
        computed = self._compute_hash(
            manifest=package.manifest,
            algorithm=package.signature_algorithm,
        )
        if computed != package.signature_hash:
            return VerificationResult(
                verified=False,
                reason_code="signature_mismatch",
                verified_at=now,
            )
        return VerificationResult(
            verified=True,
            reason_code="signature_valid",
            verified_at=now,
        )

    @staticmethod
    def _compute_hash(*, manifest: dict[str, Any], algorithm: str) -> str:
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if algorithm == "sha256":
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if algorithm == "sha512":
            return hashlib.sha512(canonical.encode("utf-8")).hexdigest()
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    @staticmethod
    def compute_signature_hash(*, manifest: dict[str, Any], algorithm: str = "sha256") -> str:
        return SkillPackageVerifier._compute_hash(manifest=manifest, algorithm=algorithm)
