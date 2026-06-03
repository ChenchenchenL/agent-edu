from __future__ import annotations


def bounded_limit(limit: int, *, max_limit: int = 200) -> int:
    return max(1, min(limit, max_limit))
