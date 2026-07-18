"""Document blob storage abstraction.

# ASSUMPTION: real Supabase Storage wiring (bucket, service-role upload
credentials) is deferred to a follow-up PR once Supabase project credentials
exist — this repo currently has no live Supabase project to point at. The
`DocumentStorage` Protocol is the seam: `SupabaseStorage` will implement it
with zero changes to any caller (webhook handler, `file_document` tool,
`parse_document` tool all depend on the Protocol, never a concrete client).
`LocalFilesystemStorage` is the dev/test implementation, storing under
`ROWAN_STORAGE_DIR` (defaults to a temp dir) — good enough to exercise the
full pipeline (store attachment -> parse -> file) without external
credentials.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol


class DocumentStorage(Protocol):
    async def write(self, *, storage_path: str, data: bytes) -> None: ...
    async def read(self, *, storage_path: str) -> bytes: ...


class LocalFilesystemStorage:
    def __init__(self, base_dir: str | None = None) -> None:
        self.base_dir = Path(base_dir or os.environ.get("ROWAN_STORAGE_DIR") or tempfile.gettempdir() / Path("rowan-storage"))
        self.base_dir.mkdir(parents=True, exist_ok=True)

    async def write(self, *, storage_path: str, data: bytes) -> None:
        path = self.base_dir / storage_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def read(self, *, storage_path: str) -> bytes:
        path = self.base_dir / storage_path
        return path.read_bytes()


_default_storage: DocumentStorage | None = None


def get_storage() -> DocumentStorage:
    global _default_storage
    if _default_storage is None:
        _default_storage = LocalFilesystemStorage()
    return _default_storage
