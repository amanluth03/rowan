"""Entity retrieval (tier b) + the entity-table writes issued by the tools
layer. All functions take an already org-scoped `asyncpg.Connection` (see
app/db.py:org_scoped_tx) — RLS does the tenant-isolation enforcement; these
functions never add their own `WHERE organization_id = ...` as the *only*
guard (defense-in-depth aside), so a caller cannot bypass isolation by
forgetting a clause.

Read functions first, per CLAUDE.md's build-order rule ("Build read-only
tools before write-action tools" — the same discipline applies one layer
down, since every write-action tool is built on top of these reads).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

import asyncpg

from app.retrieval.models import (
    AgentEventRow,
    CoiDocumentRow,
    CoiExtractionRow,
    CoiValidationRow,
    ComplianceRequirementRow,
    EmailMessageRow,
    EscalationRow,
    OrganizationRow,
    PropertyRow,
    VendorCoverageRequirementRow,
    VendorRow,
)

# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


async def get_organization(conn: asyncpg.Connection, organization_id: UUID) -> OrganizationRow | None:
    row = await conn.fetchrow(
        "select id, name, agent_enabled, settings, created_at from organizations where id = $1",
        organization_id,
    )
    if row is None:
        return None
    return OrganizationRow(**_with_json(row, "settings"))


async def get_primary_user_email(conn: asyncpg.Connection, organization_id: UUID) -> str | None:
    """# ASSUMPTION: single user per org in v1 (ADR 0001) means "the PM to
    notify" is unambiguous — the org's first/only user row. Ordered by
    created_at so behavior is deterministic if this assumption is ever
    violated before the schema is revisited.
    """
    row = await conn.fetchrow(
        "select email from users where organization_id = $1 order by created_at asc limit 1",
        organization_id,
    )
    return row["email"] if row else None


async def get_vendor(conn: asyncpg.Connection, vendor_id: UUID) -> VendorRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, name, primary_email, vendor_role, status,
               primary_property_id, notes
        from vendors where id = $1
        """,
        vendor_id,
    )
    return VendorRow(**dict(row)) if row else None


async def get_property(conn: asyncpg.Connection, property_id: UUID) -> "PropertyRow | None":
    row = await conn.fetchrow(
        """
        select id, organization_id, name, line1, city, state, county, postal_code, country,
               hoa_name, property_type, attributes
        from properties where id = $1
        """,
        property_id,
    )
    if row is None:
        return None
    return PropertyRow(**_with_json(row, "attributes"))


async def list_vendors(conn: asyncpg.Connection) -> list[VendorRow]:
    """Every vendor in the caller's org (RLS-scoped by the enclosing
    org_scoped_tx — no explicit organization_id filter needed, matching this
    module's existing convention, e.g. get_vendor/list_coi_document_history)."""
    rows = await conn.fetch(
        """
        select id, organization_id, name, primary_email, vendor_role, status,
               primary_property_id, notes
        from vendors order by name
        """
    )
    return [VendorRow(**dict(r)) for r in rows]


async def get_vendor_coverage_requirements(
    conn: asyncpg.Connection, vendor_id: UUID
) -> list[VendorCoverageRequirementRow]:
    rows = await conn.fetch(
        """
        select id, organization_id, vendor_id, coverage_type, min_each_occurrence,
               min_aggregate, requires_additional_insured, requires_waiver_of_subrogation,
               requires_primary_noncontributory, source_compliance_requirement_id, confirmed_by_pm
        from vendor_coverage_requirements
        where vendor_id = $1
        """,
        vendor_id,
    )
    return [VendorCoverageRequirementRow(**dict(r)) for r in rows]


async def get_compliance_requirement(
    conn: asyncpg.Connection, requirement_id: UUID
) -> ComplianceRequirementRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, jurisdiction_state, jurisdiction_city, jurisdiction_hoa,
               property_type, vendor_role, coverage_type, min_each_occurrence, min_aggregate,
               requires_additional_insured, requires_waiver_of_subrogation,
               requires_primary_noncontributory, source_citation, source_url,
               last_verified_at, active
        from compliance_requirements where id = $1
        """,
        requirement_id,
    )
    return ComplianceRequirementRow(**dict(row)) if row else None


async def get_current_coi_document(conn: asyncpg.Connection, vendor_id: UUID) -> CoiDocumentRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, vendor_id, run_id, storage_path, original_filename,
               content_type, byte_size, sha256, source, version_number, supersedes_document_id,
               status, valid_from, valid_to, is_current, received_at
        from coi_documents where vendor_id = $1 and is_current
        """,
        vendor_id,
    )
    return CoiDocumentRow(**dict(row)) if row else None


async def get_coi_document(conn: asyncpg.Connection, document_id: UUID) -> CoiDocumentRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, vendor_id, run_id, storage_path, original_filename,
               content_type, byte_size, sha256, source, version_number, supersedes_document_id,
               status, valid_from, valid_to, is_current, received_at
        from coi_documents where id = $1
        """,
        document_id,
    )
    return CoiDocumentRow(**dict(row)) if row else None


async def list_coi_document_history(conn: asyncpg.Connection, vendor_id: UUID) -> list[CoiDocumentRow]:
    rows = await conn.fetch(
        """
        select id, organization_id, vendor_id, run_id, storage_path, original_filename,
               content_type, byte_size, sha256, source, version_number, supersedes_document_id,
               status, valid_from, valid_to, is_current, received_at
        from coi_documents where vendor_id = $1 order by version_number desc
        """,
        vendor_id,
    )
    return [CoiDocumentRow(**dict(r)) for r in rows]


async def get_current_extraction(
    conn: asyncpg.Connection, coi_document_id: UUID
) -> CoiExtractionRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, coi_document_id, extracted, field_confidence,
               overall_confidence, model, prompt_hash, input_tokens, output_tokens, cost_cents,
               is_current, created_at
        from coi_extractions where coi_document_id = $1 and is_current
        order by created_at desc limit 1
        """,
        coi_document_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["extracted"] = _loads(d["extracted"])
    d["field_confidence"] = _loads(d["field_confidence"])
    d["overall_confidence"] = float(d["overall_confidence"])
    return CoiExtractionRow(**d)


async def get_extraction(conn: asyncpg.Connection, extraction_id: UUID) -> CoiExtractionRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, coi_document_id, extracted, field_confidence,
               overall_confidence, model, prompt_hash, input_tokens, output_tokens, cost_cents,
               is_current, created_at
        from coi_extractions where id = $1
        """,
        extraction_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["extracted"] = _loads(d["extracted"])
    d["field_confidence"] = _loads(d["field_confidence"])
    d["overall_confidence"] = float(d["overall_confidence"])
    return CoiExtractionRow(**d)


async def get_validation(conn: asyncpg.Connection, validation_id: UUID) -> CoiValidationRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, coi_extraction_id, result, line_results,
               flags, faithfulness_ok, created_at
        from coi_validations where id = $1
        """,
        validation_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["line_results"] = _loads(d["line_results"])
    d["flags"] = _loads(d["flags"])
    return CoiValidationRow(**d)


async def get_latest_validation_for_extraction(
    conn: asyncpg.Connection, coi_extraction_id: UUID
) -> CoiValidationRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, coi_extraction_id, result, line_results,
               flags, faithfulness_ok, created_at
        from coi_validations where coi_extraction_id = $1
        order by created_at desc limit 1
        """,
        coi_extraction_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["line_results"] = _loads(d["line_results"])
    d["flags"] = _loads(d["flags"])
    return CoiValidationRow(**d)


async def get_open_escalation(
    conn: asyncpg.Connection, run_id: UUID, reason_code: str, state: str
) -> EscalationRow | None:
    """Escalations dedupe on (run, reason, state) per ADR 0004's idempotency
    key `sha256(run_id | reason_code | run_state)` — one open escalation per
    tuple; re-entry updates rather than duplicates.
    """
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
               details, status, resolution, created_at, resolved_at
        from escalations
        where run_id = $1 and reason_code = $2 and status != 'resolved'
          and details->>'run_state' = $3
        order by created_at desc limit 1
        """,
        run_id,
        reason_code,
        state,
    )
    if row is None:
        return None
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


async def get_escalation(conn: asyncpg.Connection, escalation_id: UUID) -> EscalationRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
               details, status, resolution, created_at, resolved_at
        from escalations where id = $1
        """,
        escalation_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


async def list_open_escalations(
    conn: asyncpg.Connection, *, kind: str | None = None
) -> list[EscalationRow]:
    """The human-review-queue / PM-escalations-queue read path.

    Deliberately filters ONLY on `status = 'open'` (+ optional `kind`) —
    NOT on the owning run's current state. security-reviewer flagged
    (non-blocking, prior review) that `escalations` are created keyed on the
    run_state AT CREATION TIME (see `get_open_escalation` above, used only
    for escalate_to_pm's own dedupe), while an open escalation must still be
    resolvable even after the run has since moved on (e.g. a crash-recovery
    path advanced the run past `needs_human_review` in some edge case, or a
    second reason code parked the run in a different state before this one
    was resolved). Joining against `runs.state` here would silently hide
    exactly the escalations most in need of PM attention. See
    tests/test_api_reads.py::test_review_queue_finds_escalation_even_if_run_state_has_moved_on.
    """
    if kind is not None:
        rows = await conn.fetch(
            """
            select id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
                   details, status, resolution, created_at, resolved_at
            from escalations
            where status = 'open' and kind = $1
            order by created_at desc
            """,
            kind,
        )
    else:
        rows = await conn.fetch(
            """
            select id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
                   details, status, resolution, created_at, resolved_at
            from escalations
            where status = 'open'
            order by created_at desc
            """
        )
    out = []
    for r in rows:
        d = dict(r)
        d["details"] = _loads(d["details"])
        out.append(EscalationRow(**d))
    return out


async def get_latest_approved_escalation(conn: asyncpg.Connection, run_id: UUID) -> EscalationRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
               details, status, resolution, created_at, resolved_at
        from escalations
        where run_id = $1 and status = 'resolved' and resolution = 'approved'
        order by resolved_at desc limit 1
        """,
        run_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


# --------------------------------------------------------------------------
# Writes (invoked only from the tools layer, after policy + idempotency
# checks have already passed — see app/tools/*.py)
# --------------------------------------------------------------------------


async def insert_vendor(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    name: str,
    primary_email: str | None,
    vendor_role: str,
    primary_property_id: UUID | None,
    notes: str | None,
) -> VendorRow:
    row = await conn.fetchrow(
        """
        insert into vendors (
            id, organization_id, name, primary_email, vendor_role, status,
            primary_property_id, notes
        ) values ($1,$2,$3,$4,$5,'active',$6,$7)
        returning id, organization_id, name, primary_email, vendor_role, status,
                  primary_property_id, notes
        """,
        id, organization_id, name, primary_email, vendor_role, primary_property_id, notes,
    )
    return VendorRow(**dict(row))


async def upsert_vendor_coverage_requirement(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    vendor_id: UUID,
    coverage_type: str,
    min_each_occurrence: int | None,
    min_aggregate: int | None,
    requires_additional_insured: bool,
    requires_waiver_of_subrogation: bool,
    requires_primary_noncontributory: bool,
    source_compliance_requirement_id: UUID | None,
    confirmed_by_pm: bool,
) -> VendorCoverageRequirementRow:
    """Materializes one coverage-type line into the vendor's ONE effective
    requirement set (ADR 0001 locked one-set-per-vendor decision). Idempotent
    by construction via the `unique(vendor_id, coverage_type)` constraint —
    re-running SetRequirements for the same vendor/coverage_type updates the
    existing line rather than duplicating it."""
    row = await conn.fetchrow(
        """
        insert into vendor_coverage_requirements (
            id, organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
            requires_additional_insured, requires_waiver_of_subrogation, requires_primary_noncontributory,
            source_compliance_requirement_id, confirmed_by_pm
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        on conflict (vendor_id, coverage_type) do update set
            min_each_occurrence = excluded.min_each_occurrence,
            min_aggregate = excluded.min_aggregate,
            requires_additional_insured = excluded.requires_additional_insured,
            requires_waiver_of_subrogation = excluded.requires_waiver_of_subrogation,
            requires_primary_noncontributory = excluded.requires_primary_noncontributory,
            source_compliance_requirement_id = excluded.source_compliance_requirement_id,
            confirmed_by_pm = excluded.confirmed_by_pm,
            updated_at = now()
        returning id, organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
                  requires_additional_insured, requires_waiver_of_subrogation,
                  requires_primary_noncontributory, source_compliance_requirement_id, confirmed_by_pm
        """,
        id, organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
        requires_additional_insured, requires_waiver_of_subrogation, requires_primary_noncontributory,
        source_compliance_requirement_id, confirmed_by_pm,
    )
    return VendorCoverageRequirementRow(**dict(row))


async def insert_coi_document(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    vendor_id: UUID,
    run_id: UUID | None,
    storage_path: str,
    original_filename: str,
    content_type: str,
    byte_size: int,
    sha256: str,
    source: str,
    version_number: int,
) -> CoiDocumentRow:
    row = await conn.fetchrow(
        """
        insert into coi_documents (
            id, organization_id, vendor_id, run_id, storage_path, original_filename,
            content_type, byte_size, sha256, source, version_number, status
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'received')
        returning id, organization_id, vendor_id, run_id, storage_path, original_filename,
                  content_type, byte_size, sha256, source, version_number,
                  supersedes_document_id, status, valid_from, valid_to, is_current, received_at
        """,
        id, organization_id, vendor_id, run_id, storage_path, original_filename,
        content_type, byte_size, sha256, source, version_number,
    )
    return CoiDocumentRow(**dict(row))


async def next_document_version(conn: asyncpg.Connection, vendor_id: UUID) -> int:
    row = await conn.fetchrow(
        "select coalesce(max(version_number), 0) + 1 as v from coi_documents where vendor_id = $1",
        vendor_id,
    )
    return int(row["v"])


async def file_coi_document(
    conn: asyncpg.Connection,
    *,
    coi_document_id: UUID,
    valid_from: date,
    valid_to: date,
) -> tuple[CoiDocumentRow, UUID | None]:
    """Marks a document `is_current`, supersedes the prior current doc.

    Idempotent by construction: the partial-unique index
    `coi_documents(vendor_id) where is_current` means a second attempt after
    a crash either (a) finds the document already `is_current` (no-op,
    returns current state) or (b) would violate the unique index, which the
    caller (app/tools/file_document.py) treats as an idempotent replay.
    """
    doc = await get_coi_document(conn, coi_document_id)
    if doc is None:
        raise ValueError(f"coi_document {coi_document_id} not found")

    if doc.is_current:
        # Already filed — idempotent replay, no further write.
        return doc, doc.supersedes_document_id

    superseded_id: UUID | None = None
    prior = await conn.fetchrow(
        "select id from coi_documents where vendor_id = $1 and is_current for update",
        doc.vendor_id,
    )
    if prior is not None:
        superseded_id = prior["id"]
        await conn.execute(
            "update coi_documents set is_current = false, status = 'superseded' where id = $1",
            superseded_id,
        )

    row = await conn.fetchrow(
        """
        update coi_documents
        set is_current = true, status = 'filed', valid_from = $2, valid_to = $3,
            supersedes_document_id = $4
        where id = $1
        returning id, organization_id, vendor_id, run_id, storage_path, original_filename,
                  content_type, byte_size, sha256, source, version_number,
                  supersedes_document_id, status, valid_from, valid_to, is_current, received_at
        """,
        coi_document_id, valid_from, valid_to, superseded_id,
    )
    return CoiDocumentRow(**dict(row)), superseded_id


async def insert_coi_extraction(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    run_id: UUID | None,
    coi_document_id: UUID,
    extracted: dict[str, Any],
    field_confidence: dict[str, Any],
    overall_confidence: float,
    model: str,
    prompt_hash: str,
    input_tokens: int,
    output_tokens: int,
    cost_cents: int,
) -> CoiExtractionRow:
    await conn.execute(
        "update coi_extractions set is_current = false where coi_document_id = $1", coi_document_id
    )
    row = await conn.fetchrow(
        """
        insert into coi_extractions (
            id, organization_id, run_id, coi_document_id, extracted, field_confidence,
            overall_confidence, model, prompt_hash, input_tokens, output_tokens, cost_cents,
            is_current
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,true)
        returning id, organization_id, run_id, coi_document_id, extracted, field_confidence,
                  overall_confidence, model, prompt_hash, input_tokens, output_tokens, cost_cents,
                  is_current, created_at
        """,
        id, organization_id, run_id, coi_document_id, json.dumps(extracted),
        json.dumps(field_confidence), overall_confidence, model, prompt_hash,
        input_tokens, output_tokens, cost_cents,
    )
    d = dict(row)
    d["extracted"] = _loads(d["extracted"])
    d["field_confidence"] = _loads(d["field_confidence"])
    d["overall_confidence"] = float(d["overall_confidence"])
    return CoiExtractionRow(**d)


async def insert_coi_validation(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    run_id: UUID | None,
    coi_extraction_id: UUID,
    result: str,
    line_results: list[dict[str, Any]],
    flags: list[dict[str, Any]],
    faithfulness_ok: bool,
) -> CoiValidationRow:
    row = await conn.fetchrow(
        """
        insert into coi_validations (
            id, organization_id, run_id, coi_extraction_id, result, line_results, flags,
            faithfulness_ok
        ) values ($1,$2,$3,$4,$5,$6,$7,$8)
        returning id, organization_id, run_id, coi_extraction_id, result, line_results, flags,
                  faithfulness_ok, created_at
        """,
        id, organization_id, run_id, coi_extraction_id, result,
        json.dumps(line_results), json.dumps(flags), faithfulness_ok,
    )
    d = dict(row)
    d["line_results"] = _loads(d["line_results"])
    d["flags"] = _loads(d["flags"])
    return CoiValidationRow(**d)


async def insert_escalation(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    run_id: UUID,
    vendor_id: UUID,
    kind: str,
    reason_code: str,
    severity: str,
    summary: str,
    details: dict[str, Any],
) -> EscalationRow:
    row = await conn.fetchrow(
        """
        insert into escalations (
            id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary, details
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        returning id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
                  details, status, resolution, created_at, resolved_at
        """,
        id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
        json.dumps(details),
    )
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


async def update_escalation_details(
    conn: asyncpg.Connection, escalation_id: UUID, *, summary: str, details: dict[str, Any]
) -> EscalationRow:
    """Re-entry path for `escalate_to_pm` (ADR 0004: "one open escalation
    per (run, reason, state); re-entry updates rather than duplicates")."""
    row = await conn.fetchrow(
        """
        update escalations set summary = $2, details = $3
        where id = $1
        returning id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
                  details, status, resolution, created_at, resolved_at
        """,
        escalation_id, summary, json.dumps(details),
    )
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


async def resolve_escalation(
    conn: asyncpg.Connection, *, escalation_id: UUID, resolution: str, resolved_by: UUID | None
) -> EscalationRow:
    row = await conn.fetchrow(
        """
        update escalations
        set status = 'resolved', resolution = $2, resolved_by = $3, resolved_at = now()
        where id = $1
        returning id, organization_id, run_id, vendor_id, kind, reason_code, severity, summary,
                  details, status, resolution, created_at, resolved_at
        """,
        escalation_id, resolution, resolved_by,
    )
    d = dict(row)
    d["details"] = _loads(d["details"])
    return EscalationRow(**d)


async def insert_email_message(
    conn: asyncpg.Connection,
    *,
    id: UUID,
    organization_id: UUID,
    run_id: UUID | None,
    vendor_id: UUID | None,
    direction: str,
    provider_message_id: str | None,
    reply_token: str | None,
    subject: str,
    body_snapshot: str,
    to_email: str,
    from_email: str,
    status: str,
    attachments_count: int = 0,
) -> EmailMessageRow:
    row = await conn.fetchrow(
        """
        insert into email_messages (
            id, organization_id, run_id, vendor_id, direction, provider_message_id,
            reply_token, subject, body_snapshot, to_email, from_email, status, attachments_count
        ) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
        returning id, organization_id, run_id, vendor_id, direction, provider_message_id,
                  reply_token, subject, body_snapshot, to_email, from_email, status,
                  attachments_count, created_at
        """,
        id, organization_id, run_id, vendor_id, direction, provider_message_id,
        reply_token, subject, body_snapshot, to_email, from_email, status, attachments_count,
    )
    return EmailMessageRow(**dict(row))


_AGENT_EVENT_COLUMNS = """
    id, organization_id, run_id, vendor_id, event_type, name, severity, from_state, to_state,
    tool_name, idempotency_key, llm_model, prompt_hash, input_tokens, output_tokens, cost_cents,
    latency_ms, payload, created_at
"""


async def list_agent_events_for_run(
    conn: asyncpg.Connection, run_id: UUID, *, limit: int = 500
) -> list[AgentEventRow]:
    rows = await conn.fetch(
        f"select {_AGENT_EVENT_COLUMNS} from agent_events where run_id = $1 order by created_at asc limit $2",
        run_id, limit,
    )
    return [AgentEventRow(**_with_json(r, "payload")) for r in rows]


async def list_recent_agent_events_for_org(
    conn: asyncpg.Connection, *, limit: int = 100
) -> list[AgentEventRow]:
    """Activity-feed source (ADR 0003 `ActivityFeedItemDTO`). RLS-scoped by
    the enclosing org_scoped_tx; no explicit organization_id filter needed."""
    rows = await conn.fetch(
        f"select {_AGENT_EVENT_COLUMNS} from agent_events order by created_at desc limit $1",
        limit,
    )
    return [AgentEventRow(**_with_json(r, "payload")) for r in rows]


async def find_email_by_provider_message_id(
    conn: asyncpg.Connection, provider_message_id: str
) -> EmailMessageRow | None:
    row = await conn.fetchrow(
        """
        select id, organization_id, run_id, vendor_id, direction, provider_message_id,
               reply_token, subject, body_snapshot, to_email, from_email, status,
               attachments_count, created_at
        from email_messages where provider_message_id = $1
        """,
        provider_message_id,
    )
    return EmailMessageRow(**dict(row)) if row else None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _loads(value: Any) -> Any:
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def _with_json(row: asyncpg.Record, *json_fields: str) -> dict[str, Any]:
    d = dict(row)
    for f in json_fields:
        d[f] = _loads(d[f])
    return d
