"""App-side UUID v7 (time-sortable) ID generation.

Per ADR 0000's cross-cutting conventions: "UUID v7 (time-sortable) primary
keys, generated app-side, column `id`." This is the authoritative generator;
the SQL-side `uuid_generate_v7()` default (migrations/0001_extensions.sql)
is a fallback for rows inserted outside the app, not the primary path.

# ASSUMPTION: Python's stdlib does not yet ship uuid.uuid7() on the pinned
3.12 runtime, so this is a small RFC 9562-shaped implementation (48-bit ms
timestamp, version 7, variant bits, 74 random bits) — sortable and unique,
not required to match any particular vendor library bit-for-bit.
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = int(time.time() * 1000)
    ts_bytes = unix_ms.to_bytes(6, byteorder="big")

    rand = bytearray(os.urandom(10))
    # Version 7 in the high nibble of byte 6.
    rand[0] = (rand[0] & 0x0F) | 0x70
    # Variant 10xxxxxx in the high bits of byte 8.
    rand[2] = (rand[2] & 0x3F) | 0x80

    return uuid.UUID(bytes=ts_bytes + bytes(rand))
