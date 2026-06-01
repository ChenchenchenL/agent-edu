from __future__ import annotations

import hashlib
import secrets


ACCESS_KEY_PREFIX = "edu_prof_"


def generate_profile_access_key() -> str:
    return f"{ACCESS_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_profile_access_key(raw_access_key: str) -> str:
    return hashlib.sha256(raw_access_key.encode("utf-8")).hexdigest()
