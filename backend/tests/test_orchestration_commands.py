"""TDD for the 9 ADR 0003 commands' orchestration-layer implementations
(app/orchestration/runner.py): AddVendor, SetRequirements, StartRun,
PauseRun, ResumeRun, ApproveReview, RejectReview, RequestRevision,
ResolveEscalation. These are the functions app/api/commands.py's HTTP
handlers call — see tests/test_api_commands.py for the HTTP-layer wiring
tests.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.enums import RunState, RunStatus, VendorRole
from app.orchestration import runner
from app.orchestration.runner import NoRequirementsOnFileError
from app.retrieval import entity_repo

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# AddVendor
# ---------------------------------------------------------------------------


class TestAddVendor:
    async def test_creates_vendor_and_initial_run(self, org_and_vendor):
        vendor, run = await runner.add_vendor(
            org_and_vendor["org_id"],
            name="New Vendor Co",
            primary_email="new@vendor.example.com",
            vendor_role=VendorRole.electrician.value,
            primary_property_id=org_and_vendor["property_id"],
            notes="onboarded via test",
            due_date=date(2027, 1, 1),
        )
        assert vendor.name == "New Vendor Co"
        assert run.vendor_id == vendor.id
        assert run.state == RunState.monitoring
        assert run.status == RunStatus.active
        assert run.due_date == date(2027, 1, 1)
        assert run.trigger == "renewal_due"

    async def test_reply_token_is_csprng_generated_and_unique(self, org_and_vendor):
        """security-reviewer's binding condition (flagged in two prior
        reviews): reply_token must be CSPRNG-generated with a real
        expiry — never predictable, never null."""
        _, run1 = await runner.add_vendor(
            org_and_vendor["org_id"], name="Vendor A", primary_email="a@x.example.com",
            vendor_role=VendorRole.plumber.value, primary_property_id=None, notes=None, due_date=None,
        )
        _, run2 = await runner.add_vendor(
            org_and_vendor["org_id"], name="Vendor B", primary_email="b@x.example.com",
            vendor_role=VendorRole.plumber.value, primary_property_id=None, notes=None, due_date=None,
        )
        assert run1.reply_token is not None
        assert run2.reply_token is not None
        assert run1.reply_token != run2.reply_token
        # secrets.token_urlsafe(32) -> 43 base64url chars (256 bits, no padding).
        assert len(run1.reply_token) >= 32
        assert re.fullmatch(r"[A-Za-z0-9_\-]+", run1.reply_token)
        assert run1.reply_token_expires_at is not None
        assert run1.reply_token_expires_at > run1.started_at

    async def test_without_due_date_trigger_is_manual_and_due_date_null(self, org_and_vendor):
        vendor, run = await runner.add_vendor(
            org_and_vendor["org_id"], name="No Date Co", primary_email="nd@x.example.com",
            vendor_role=VendorRole.roofer.value, primary_property_id=None, notes=None, due_date=None,
        )
        assert run.due_date is None
        assert run.trigger == "manual"
        # evaluate_expiry is a documented no-op with due_date=None (see
        # app/orchestration/runner.py) — confirm that holds for a freshly
        # onboarded vendor too, not just pre-existing fixtures.
        result = await runner.evaluate_expiry(org_and_vendor["org_id"], run.id)
        assert result is None

    async def test_rejects_unknown_property(self, org_and_vendor):
        with pytest.raises(ValueError):
            await runner.add_vendor(
                org_and_vendor["org_id"], name="Bad Prop Co", primary_email="bp@x.example.com",
                vendor_role=VendorRole.hvac.value, primary_property_id=uuid7(), notes=None, due_date=None,
            )

    async def test_writes_agent_event(self, org_and_vendor):
        vendor, run = await runner.add_vendor(
            org_and_vendor["org_id"], name="Evented Co", primary_email="e@x.example.com",
            vendor_role=VendorRole.cleaner.value, primary_property_id=None, notes=None, due_date=None,
        )
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            events = await entity_repo.list_agent_events_for_run(conn, run.id)
        names = [e.name for e in events]
        assert "vendor.added" in names


# ---------------------------------------------------------------------------
# SetRequirements
# ---------------------------------------------------------------------------


class TestSetRequirements:
    async def test_auto_retrieves_from_compliance_requirements_kb(self, org_and_vendor):
        # org_and_vendor's fixture vendor is a plumber at a Boston, MA
        # property, and the fixture already seeds a matching
        # compliance_requirements row (see tests/conftest.py) — but with a
        # DIFFERENT vendor_coverage_requirements id than what SetRequirements
        # will materialize, so this proves the retrieval + materialize path,
        # not just that the fixture row already existed.
        vcrs = await runner.set_requirements(org_and_vendor["org_id"], org_and_vendor["vendor_id"])
        assert len(vcrs) == 1
        assert vcrs[0].coverage_type.value == "general_liability"
        assert vcrs[0].source_compliance_requirement_id == org_and_vendor["requirement_id"]
        assert vcrs[0].confirmed_by_pm is True

    async def test_raises_when_no_kb_match(self, org_and_vendor, admin_conn):
        # Move the vendor's property to a jurisdiction with no KB coverage.
        other_property_id = uuid7()
        await admin_conn.execute(
            """
            insert into properties (id, organization_id, name, line1, city, state, postal_code, property_type)
            values ($1,$2,'Other Property','9 Nowhere Ave','Omaha','NE','68101','single_family')
            """,
            other_property_id, org_and_vendor["org_id"],
        )
        await admin_conn.execute(
            "update vendors set primary_property_id = $2 where id = $1",
            org_and_vendor["vendor_id"], other_property_id,
        )
        with pytest.raises(NoRequirementsOnFileError):
            await runner.set_requirements(org_and_vendor["org_id"], org_and_vendor["vendor_id"])

    async def test_raises_when_vendor_has_no_primary_property(self, org_and_vendor, admin_conn):
        await admin_conn.execute(
            "update vendors set primary_property_id = null where id = $1", org_and_vendor["vendor_id"]
        )
        with pytest.raises(NoRequirementsOnFileError):
            await runner.set_requirements(org_and_vendor["org_id"], org_and_vendor["vendor_id"])

    async def test_manual_override_line_with_no_kb_backing(self, org_and_vendor):
        vcrs = await runner.set_requirements(
            org_and_vendor["org_id"],
            org_and_vendor["vendor_id"],
            lines=[
                {
                    "coverage_type": "umbrella_excess",
                    "min_each_occurrence": 5_000_000,
                    "min_aggregate": None,
                    "requires_additional_insured": False,
                    "requires_waiver_of_subrogation": False,
                    "requires_primary_noncontributory": False,
                    "source_compliance_requirement_id": None,
                }
            ],
        )
        assert len(vcrs) == 1
        assert vcrs[0].source_compliance_requirement_id is None
        assert vcrs[0].confirmed_by_pm is True

    async def test_manual_line_with_invalid_source_id_raises(self, org_and_vendor):
        with pytest.raises(ValueError):
            await runner.set_requirements(
                org_and_vendor["org_id"],
                org_and_vendor["vendor_id"],
                lines=[
                    {
                        "coverage_type": "pollution",
                        "min_each_occurrence": None,
                        "min_aggregate": None,
                        "requires_additional_insured": False,
                        "requires_waiver_of_subrogation": False,
                        "requires_primary_noncontributory": False,
                        "source_compliance_requirement_id": uuid7(),
                    }
                ],
            )

    async def test_upsert_is_idempotent_per_coverage_type(self, org_and_vendor):
        await runner.set_requirements(org_and_vendor["org_id"], org_and_vendor["vendor_id"])
        await runner.set_requirements(org_and_vendor["org_id"], org_and_vendor["vendor_id"])
        # unique(vendor_id, coverage_type) means re-running for the same
        # vendor/coverage_type UPDATES the existing line, never duplicates.
        async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
            rows = await entity_repo.get_vendor_coverage_requirements(conn, org_and_vendor["vendor_id"])
        assert len([r for r in rows if r.coverage_type.value == "general_liability"]) == 1


# ---------------------------------------------------------------------------
# StartRun
# ---------------------------------------------------------------------------


class TestStartRun:
    async def test_from_monitoring_forces_outreach_immediately(self, org_and_vendor, make_run):
        # Deliberately far-future due_date -- the scheduler-driven guard
        # would NOT fire for years; StartRun bypasses that entirely.
        run_id = await make_run(state="monitoring", due_date=date.today() + timedelta(days=300))
        result = await runner.start_run_now(org_and_vendor["org_id"], run_id)
        assert result is not None
        assert result.state == RunState.awaiting_vendor_response
        assert result.outreach_email_count == 1

    async def test_noop_when_already_in_flight(self, org_and_vendor, make_run):
        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        result = await runner.start_run_now(org_and_vendor["org_id"], run_id)
        assert result is None

    async def test_noop_when_paused(self, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring", due_date=date.today(), status="paused")
        result = await runner.start_run_now(org_and_vendor["org_id"], run_id)
        assert result is None


# ---------------------------------------------------------------------------
# PauseRun / ResumeRun
# ---------------------------------------------------------------------------


class TestPauseResumeRun:
    async def test_pause_freezes_run(self, org_and_vendor, make_run):
        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today())
        result = await runner.pause_run(org_and_vendor["org_id"], run_id, paused_by=None)
        assert result is not None
        assert result.status == RunStatus.paused

        # A frozen run takes no automated action (ADR 0002 global rule).
        followup = await runner.check_followup_or_deadline(org_and_vendor["org_id"], run_id)
        assert followup is None

    async def test_pause_is_idempotent_noop_if_already_paused(self, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring", status="paused")
        result = await runner.pause_run(org_and_vendor["org_id"], run_id, paused_by=None)
        assert result is None

    async def test_resume_unfreezes_run(self, org_and_vendor, make_run):
        run_id = await make_run(state="awaiting_vendor_response", due_date=date.today(), status="paused")
        result = await runner.resume_run(org_and_vendor["org_id"], run_id)
        assert result is not None
        assert result.status == RunStatus.active

    async def test_resume_is_idempotent_noop_if_not_paused(self, org_and_vendor, make_run):
        run_id = await make_run(state="monitoring")
        result = await runner.resume_run(org_and_vendor["org_id"], run_id)
        assert result is None


# ---------------------------------------------------------------------------
# ApproveReview / RejectReview / RequestRevision / ResolveEscalation
# ---------------------------------------------------------------------------


async def _insert_escalation(org_and_vendor, run_id, *, kind: str, run_state_in_details: str, status: str = "open"):
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        esc = await entity_repo.insert_escalation(
            conn, id=uuid7(), organization_id=org_and_vendor["org_id"], run_id=run_id,
            vendor_id=org_and_vendor["vendor_id"], kind=kind, reason_code="test_reason",
            severity="warn", summary="test summary", details={"run_state": run_state_in_details},
        )
        if status != "open":
            await entity_repo.resolve_escalation(conn, escalation_id=esc.id, resolution="approved", resolved_by=None)
    return esc.id


class TestApproveRejectRequestRevision:
    async def test_approve_review_dispatches_by_escalation_id_alone(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="needs_human_review"
        )
        result = await runner.approve_review(org_and_vendor["org_id"], esc_id, resolved_by=None)
        assert result is not None
        assert result.state == RunState.filed

    async def test_reject_review(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="needs_human_review"
        )
        result = await runner.reject_review(org_and_vendor["org_id"], esc_id, resolved_by=None)
        assert result is not None
        assert result.state == RunState.escalated_to_pm

    async def test_request_revision(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="needs_human_review"
        )
        result = await runner.request_revision(
            org_and_vendor["org_id"], esc_id, resolved_by=None, revision_reason="please resend"
        )
        assert result is not None
        assert result.state == RunState.awaiting_vendor_response

    async def test_approve_review_wrong_kind_is_noop(self, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="escalated_to_pm", run_state_in_details="escalated_to_pm"
        )
        result = await runner.approve_review(org_and_vendor["org_id"], esc_id, resolved_by=None)
        assert result is None

    async def test_approve_review_already_resolved_is_noop(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="needs_human_review",
            status="resolved",
        )
        result = await runner.approve_review(org_and_vendor["org_id"], esc_id, resolved_by=None)
        assert result is None

    async def test_approve_review_unknown_escalation_id_is_noop(self, org_and_vendor):
        result = await runner.approve_review(org_and_vendor["org_id"], uuid7(), resolved_by=None)
        assert result is None

    async def test_dispatch_finds_escalation_even_when_run_state_has_moved_on(self, org_and_vendor, make_run):
        """The exact regression the security review flagged: escalations are
        created keyed on run_state AT CREATION TIME (details.run_state), but
        dispatch (and the review-queue read path) must find/act on an open
        escalation by kind+status alone -- never by re-matching the run's
        CURRENT state, which may have moved on since. Here the escalation's
        stamped `details.run_state` ('needs_human_review') deliberately does
        NOT match anything about how the run got looked up -- only kind +
        status='open' do the finding.
        """
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="a_totally_different_state"
        )
        result = await runner.approve_review(org_and_vendor["org_id"], esc_id, resolved_by=None)
        assert result is not None
        assert result.state == RunState.filed


class TestResolveEscalation:
    async def test_resolved_routes_to_monitoring(self, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="escalated_to_pm", run_state_in_details="escalated_to_pm"
        )
        result = await runner.resolve_escalation(
            org_and_vendor["org_id"], esc_id, decision="resolved", resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.monitoring

    async def test_keep_chasing_routes_to_awaiting_vendor_response(self, org_and_vendor, make_run):
        run_id = await make_run(state="escalated_to_pm", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="escalated_to_pm", run_state_in_details="escalated_to_pm"
        )
        result = await runner.resolve_escalation(
            org_and_vendor["org_id"], esc_id, decision="keep_chasing", resolved_by=None
        )
        assert result is not None
        assert result.state == RunState.awaiting_vendor_response

    async def test_wrong_kind_is_noop(self, org_and_vendor, make_run):
        run_id = await make_run(state="needs_human_review", due_date=date.today())
        esc_id = await _insert_escalation(
            org_and_vendor, run_id, kind="needs_human_review", run_state_in_details="needs_human_review"
        )
        result = await runner.resolve_escalation(
            org_and_vendor["org_id"], esc_id, decision="resolved", resolved_by=None
        )
        assert result is None
