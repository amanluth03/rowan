"""Deterministic UUIDs for fixture data (uuid5 over a fixed namespace), so
fixture files, expected retrieval results, and hand-computed expected
`line_results` can all reference the same stable IDs across files without a
shared mutable registry."""
from __future__ import annotations

import uuid

_NAMESPACE = uuid.UUID("a5e6f6d0-1c0a-4e1b-9b8a-000000000000")


def stable_id(name: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, name)
