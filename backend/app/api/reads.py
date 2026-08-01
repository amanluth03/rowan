"""Interface read routes (ADR 0003 "Orchestration -> Interface: read-model
DTOs"). Every handler here calls app/api/read_models.py only — never
app/retrieval directly (ADR 0003 boundary rule #3).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api import read_models
from app.api.deps import Principal, get_organization_id, get_principal, rate_limit
from app.api.schemas import ActivityFeedItemDTO, MeDTO, ReviewQueueItemDTO, RunTraceDTO, VendorStatusDTO
from app.db import org_scoped_tx
from app.retrieval import entity_repo
from app.storage import get_storage

router = APIRouter(prefix="/api/v1", tags=["reads"], dependencies=[Depends(rate_limit)])


@router.get("/me", response_model=MeDTO)
async def get_me(principal: Principal = Depends(get_principal)) -> MeDTO:
    """The caller's own identity and role. Used by the UI to hide owner-only
    actions -- cosmetically. Enforcement is server-side via require_role;
    this endpoint exists so the UI does not offer buttons that will 403."""
    return MeDTO(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        email=principal.email,
        role=principal.role.value,
    )


def _safe_content_disposition_filename(filename: str) -> str:
    """`coi_documents.original_filename` is preserved metadata from an
    UNTRUSTED inbound email attachment (CLAUDE.md) — `file_guardrails.py`'s
    `_is_unsafe_filename` rejects path separators/`..`/NUL for the STORAGE
    path use case, but does not (and doesn't need to, for that use case)
    reject CR/LF or quote characters. Interpolating it verbatim into an HTTP
    response header here would be a header-injection surface (CRLF ->
    injected headers) that file_guardrails.py's existing check does not
    cover. Stripped/escaped here, independently, rather than widening that
    guardrail's contract for an unrelated call site.
    """
    cleaned = filename.replace("\r", "").replace("\n", "").replace('"', "")
    return cleaned[:200] or "document"


_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "tiff": "image/tiff",
    "tif": "image/tiff",
}


def _safe_media_type(storage_path: str) -> str:
    """security-reviewer BLOCK (2026-07-18): this used to echo
    `coi_documents.content_type` (with CR/LF stripped) straight into the
    response. That column is the inbound webhook's ATTACKER-CONTROLLED MIME
    string — stripping CR/LF closes header injection but does nothing to
    stop a vendor from labeling a malicious file `text/html` (or anything
    else) while the ingest guardrail (file_guardrails.py) only checks a
    magic-byte PREFIX, so a PDF-polyglot containing an HTML/JS payload
    passes it. Serving that back with an attacker-chosen Content-Type,
    inline, is exactly CLAUDE.md's "malicious COI -> exfiltrate data"
    highest-risk surface: a PM's (or the frontend's embedded DocumentRef.url)
    browser could render/execute it.

    Fixed by NOT trusting `content_type` at all here. The media type is
    derived solely from the guardrail-DETECTED type, which is exactly what
    `storage_path`'s extension already encodes — see
    `app/orchestration/runner.py::handle_inbound_document`, which builds
    `storage_path` as `f"{vendor_id}/{document_id}.{guardrail.detected_type}"`
    (never from the untrusted filename either, per the earlier path-traversal
    fix). A fixed allowlist keyed on that extension is the only source of
    truth for the response Content-Type; anything unrecognized falls back to
    `application/octet-stream` (never sniffed, never guessed from the
    untrusted column).
    """
    ext = storage_path.rsplit(".", 1)[-1].lower() if "." in storage_path else ""
    return _EXTENSION_MEDIA_TYPES.get(ext, "application/octet-stream")


@router.get("/activity-feed", response_model=list[ActivityFeedItemDTO])
async def get_activity_feed(
    organization_id: UUID = Depends(get_organization_id),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityFeedItemDTO]:
    return await read_models.list_activity_feed(organization_id, limit=limit)


@router.get("/vendors", response_model=list[VendorStatusDTO])
async def list_vendors(organization_id: UUID = Depends(get_organization_id)) -> list[VendorStatusDTO]:
    return await read_models.list_vendor_statuses(organization_id)


@router.get("/vendors/{vendor_id}", response_model=VendorStatusDTO)
async def get_vendor(vendor_id: UUID, organization_id: UUID = Depends(get_organization_id)) -> VendorStatusDTO:
    dto = await read_models.get_vendor_status(organization_id, vendor_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="vendor not found")
    return dto


@router.get("/runs/{run_id}/trace", response_model=RunTraceDTO)
async def get_run_trace(run_id: UUID, organization_id: UUID = Depends(get_organization_id)) -> RunTraceDTO:
    dto = await read_models.get_run_trace(organization_id, run_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="run not found")
    return dto


@router.get("/reviews", response_model=list[ReviewQueueItemDTO])
async def list_review_queue(
    organization_id: UUID = Depends(get_organization_id),
    kind: Literal["needs_human_review", "escalated_to_pm"] | None = Query(default="needs_human_review"),
) -> list[ReviewQueueItemDTO]:
    return await read_models.list_review_queue(organization_id, kind=kind)


@router.get("/reviews/{escalation_id}", response_model=ReviewQueueItemDTO)
async def get_review_queue_item(
    escalation_id: UUID, organization_id: UUID = Depends(get_organization_id)
) -> ReviewQueueItemDTO:
    dto = await read_models.get_review_queue_item(organization_id, escalation_id)
    if dto is None:
        raise HTTPException(status_code=404, detail="escalation not found")
    return dto


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID, organization_id: UUID = Depends(get_organization_id)
) -> Response:
    """Backs `DocumentRef.url` in every DTO above — org-scoped (RLS) lookup
    of the document row, then a storage read. A cross-org document id 404s
    (RLS makes the row invisible; there is no separate check to forget)."""
    async with org_scoped_tx(organization_id) as conn:
        doc = await entity_repo.get_coi_document(conn, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    data = await get_storage().read(storage_path=doc.storage_path)
    safe_filename = _safe_content_disposition_filename(doc.original_filename)
    # security-reviewer BLOCK (2026-07-18): media type is derived from the
    # guardrail-detected type (storage_path's extension), never from the
    # attacker-controlled coi_documents.content_type column — see
    # _safe_media_type's docstring. Served as an attachment (never inline)
    # with X-Content-Type-Options: nosniff, so even a polyglot file that
    # slips past the ingest guardrail's prefix-only magic-byte check cannot
    # get a browser to render/execute it — it downloads as inert bytes.
    return Response(
        content=data,
        media_type=_safe_media_type(doc.storage_path),
        headers={
            "Content-Disposition": f'attachment; filename="{safe_filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
