"""Tests for V1DeterministicRetriever (ADR 0005): specificity ranking,
fallback (found=False, never proceed on empty), one row per coverage_type.
"""

from __future__ import annotations

import pytest

from app.db import org_scoped_tx
from app.ids import uuid7
from app.models.enums import PropertyType, VendorRole
from app.retrieval.requirements_retriever import RequirementsQuery, V1DeterministicRetriever

pytestmark = pytest.mark.asyncio


async def test_fallback_fires_for_unknown_jurisdiction(org_and_vendor):
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        retriever = V1DeterministicRetriever(conn)
        result = await retriever.retrieve(
            RequirementsQuery(
                organization_id=org_and_vendor["org_id"],
                jurisdiction_state="CA",  # no KB rows for CA in the fixture
                jurisdiction_city=None,
                jurisdiction_hoa=None,
                property_type=None,
                vendor_role=VendorRole.plumber,
            )
        )
    assert result.found is False
    assert result.requirements == []


async def test_finds_seeded_requirement(org_and_vendor):
    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        retriever = V1DeterministicRetriever(conn)
        result = await retriever.retrieve(
            RequirementsQuery(
                organization_id=org_and_vendor["org_id"],
                jurisdiction_state="MA",
                jurisdiction_city="Boston",
                jurisdiction_hoa=None,
                property_type=PropertyType.multi_family,
                vendor_role=VendorRole.plumber,
            )
        )
    assert result.found is True
    assert len(result.requirements) == 1
    assert result.requirements[0].source_citation == "test citation"


async def test_more_specific_row_wins_over_any_jurisdiction_row(org_and_vendor, admin_conn):
    # Add a second, more general (state-only) GL requirement for the same org.
    general_id = uuid7()
    await admin_conn.execute(
        """
        insert into compliance_requirements (
            id, organization_id, jurisdiction_state, vendor_role, coverage_type,
            min_each_occurrence, min_aggregate, source_citation, last_verified_at, active
        ) values ($1,$2,'MA',$3,'general_liability',500000,1000000,'general MA rule',now(),true)
        """,
        general_id, org_and_vendor["org_id"], VendorRole.plumber.value,
    )

    async with org_scoped_tx(org_and_vendor["org_id"]) as conn:
        retriever = V1DeterministicRetriever(conn)
        result = await retriever.retrieve(
            RequirementsQuery(
                organization_id=org_and_vendor["org_id"],
                jurisdiction_state="MA",
                jurisdiction_city="Boston",
                jurisdiction_hoa=None,
                property_type=None,
                vendor_role=VendorRole.plumber,
            )
        )
    assert len(result.requirements) == 1  # one row per coverage_type
    # The Boston-specific fixture row (min_each_occurrence=1_000_000) wins
    # over the state-wide "any city" row (500_000).
    assert result.requirements[0].min_each_occurrence == 1_000_000
    assert result.requirements[0].id == org_and_vendor["requirement_id"]
