"""
One synthetic demo org shared by every golden-document fixture, modeled on
ADR 0001's `0009_seed` migration ("one demo org, demo properties/vendors, and
a starter compliance_requirements set for the demo jurisdiction"). Four
properties give the requirement-specificity ranking (ADR 0005) something
real to differentiate:

  - Oakland Terrace   (CA / Oakland, multi_family)   -> city-specific KB row
  - Fresno Gardens    (CA / Fresno, multi_family)     -> only CA-generic KB rows apply
  - Lakeview Commons   (CA / Oakland, condo, HOA)      -> HOA-specific KB row (most specific)
  - Mile High Flats    (CO / Denver, multi_family)     -> ZERO KB rows (fallback case)

# ASSUMPTION: dollar amounts, citations, and jurisdictions below are
# synthetic and NOT real Oakland/Denver ordinances — they exist only to
# exercise the specificity-ranking and fallback logic. Do not use as real
# compliance content.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from tests.evals.contracts.retrieval import RetrievedRequirement
from tests.evals.contracts.validation import CoverageType, PropertyType, VendorRole
from tests.evals.fixtures.ids import stable_id

ORG_ID: UUID = stable_id("org:rowan-demo")
PM_EMAIL = "dana@demo-pm.rowan.test"


@dataclass
class PropertyFixture:
    id: UUID
    name: str
    city: Optional[str]
    state: str
    hoa_name: Optional[str]
    property_type: PropertyType


@dataclass
class VendorFixture:
    id: UUID
    name: str
    primary_email: str
    vendor_role: VendorRole
    primary_property: PropertyFixture


OAKLAND_TERRACE = PropertyFixture(
    id=stable_id("property:oakland-terrace"),
    name="Oakland Terrace Apartments",
    city="Oakland",
    state="CA",
    hoa_name=None,
    property_type=PropertyType.MULTI_FAMILY,
)
FRESNO_GARDENS = PropertyFixture(
    id=stable_id("property:fresno-gardens"),
    name="Fresno Gardens",
    city="Fresno",
    state="CA",
    hoa_name=None,
    property_type=PropertyType.MULTI_FAMILY,
)
LAKEVIEW_COMMONS = PropertyFixture(
    id=stable_id("property:lakeview-commons"),
    name="Lakeview Commons Condominiums",
    city="Oakland",
    state="CA",
    hoa_name="Lakeview HOA",
    property_type=PropertyType.CONDO,
)
MILE_HIGH_FLATS = PropertyFixture(
    id=stable_id("property:mile-high-flats"),
    name="Mile High Flats",
    city="Denver",
    state="CO",
    hoa_name=None,
    property_type=PropertyType.MULTI_FAMILY,
)

PROPERTIES = [OAKLAND_TERRACE, FRESNO_GARDENS, LAKEVIEW_COMMONS, MILE_HIGH_FLATS]


def _vendor(name: str, email: str, role: VendorRole, prop: PropertyFixture) -> VendorFixture:
    return VendorFixture(
        id=stable_id(f"vendor:{name}"),
        name=name,
        primary_email=email,
        vendor_role=role,
        primary_property=prop,
    )


VENDOR_HERNANDEZ_PLUMBING = _vendor(
    "Hernandez Plumbing & Rooter, Inc.", "billing@hernandezplumbing.test", VendorRole.PLUMBER, OAKLAND_TERRACE
)
VENDOR_BAYAREA_ELECTRIC = _vendor(
    "Bay Area Electric Co.", "accounts@bayareaelectric.test", VendorRole.ELECTRICIAN, OAKLAND_TERRACE
)
VENDOR_OAKLAND_HVAC = _vendor(
    "Oakland HVAC Solutions", "office@oaklandhvac.test", VendorRole.HVAC, FRESNO_GARDENS
)
VENDOR_GREENSCAPE = _vendor(
    "Greenscape Landscaping LLC", "hello@greenscapellc.test", VendorRole.LANDSCAPER, LAKEVIEW_COMMONS
)
VENDOR_QUICKFIX_PLUMBING = _vendor(
    "QuickFix Plumbing", "ar@quickfixplumbing.test", VendorRole.PLUMBER, OAKLAND_TERRACE
)
VENDOR_SPARKY_ELECTRIC = _vendor(
    "Sparky Electric", "info@sparkyelectric.test", VendorRole.ELECTRICIAN, FRESNO_GARDENS
)
VENDOR_SOLIDBUILD_GC = _vendor(
    "SolidBuild Construction", "contracts@solidbuildgc.test", VendorRole.GENERAL_CONTRACTOR, OAKLAND_TERRACE
)
VENDOR_TOPLINE_ROOFING = _vendor(
    "Topline Roofing Co.", "billing@toplineroofing.test", VendorRole.ROOFER, LAKEVIEW_COMMONS
)
VENDOR_PESTAWAY = _vendor(
    "PestAway Solutions", "service@pestaway.test", VendorRole.PEST_CONTROL, OAKLAND_TERRACE
)
VENDOR_METRO_PLUMBING = _vendor(
    "Metro Plumbing Services", "office@metroplumbing.test", VendorRole.PLUMBER, OAKLAND_TERRACE
)
VENDOR_DENVER_PLUMBING = _vendor(
    "Rocky Mountain Plumbing", "dispatch@rockymtnplumbing.test", VendorRole.PLUMBER, MILE_HIGH_FLATS
)

_VERIFIED = datetime(2026, 1, 1, tzinfo=timezone.utc)

# --- compliance_requirements KB rows (tier-c curated knowledge base) -------

CR_CA_GENERIC_GL = RetrievedRequirement(
    id=stable_id("cr:ca-generic-gl"),
    coverage_type=CoverageType.GENERAL_LIABILITY,
    min_each_occurrence=1_000_000,
    min_aggregate=2_000_000,
    requires_additional_insured=True,
    requires_waiver_of_subrogation=False,
    requires_primary_noncontributory=False,
    source_citation="CA vendor general liability baseline (Rowan curated, synthetic)",
    source_url=None,
    last_verified_at=_VERIFIED,
)
CR_OAKLAND_GL = RetrievedRequirement(
    id=stable_id("cr:oakland-gl"),
    coverage_type=CoverageType.GENERAL_LIABILITY,
    min_each_occurrence=1_000_000,
    min_aggregate=2_000_000,
    requires_additional_insured=True,
    requires_waiver_of_subrogation=True,
    requires_primary_noncontributory=True,
    source_citation="Oakland Municipal Code Ch. 8.22 vendor insurance rule (synthetic, Rowan curated)",
    source_url=None,
    last_verified_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
)
CR_LAKEVIEW_HOA_GL = RetrievedRequirement(
    id=stable_id("cr:lakeview-hoa-gl"),
    coverage_type=CoverageType.GENERAL_LIABILITY,
    min_each_occurrence=2_000_000,
    min_aggregate=4_000_000,
    requires_additional_insured=True,
    requires_waiver_of_subrogation=True,
    requires_primary_noncontributory=True,
    source_citation="Lakeview HOA CC&R Section 12 vendor insurance rider (synthetic)",
    source_url=None,
    last_verified_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
)
CR_CA_GENERIC_AUTO = RetrievedRequirement(
    id=stable_id("cr:ca-generic-auto"),
    coverage_type=CoverageType.AUTO_LIABILITY,
    min_each_occurrence=1_000_000,
    min_aggregate=None,
    requires_additional_insured=False,
    requires_waiver_of_subrogation=False,
    requires_primary_noncontributory=False,
    source_citation="CA vendor auto liability standard (Rowan curated, synthetic)",
    source_url=None,
    last_verified_at=_VERIFIED,
)
CR_CA_GENERIC_WC = RetrievedRequirement(
    id=stable_id("cr:ca-generic-wc"),
    coverage_type=CoverageType.WORKERS_COMP,
    min_each_occurrence=1_000_000,
    min_aggregate=None,
    requires_additional_insured=False,
    requires_waiver_of_subrogation=False,
    requires_primary_noncontributory=False,
    source_citation="CA Labor Code §3700 statutory workers' comp requirement (synthetic)",
    source_url=None,
    last_verified_at=_VERIFIED,
)
CR_CA_GC_UMBRELLA = RetrievedRequirement(
    id=stable_id("cr:ca-gc-umbrella"),
    coverage_type=CoverageType.UMBRELLA_EXCESS,
    min_each_occurrence=1_000_000,
    min_aggregate=1_000_000,
    requires_additional_insured=False,
    requires_waiver_of_subrogation=False,
    requires_primary_noncontributory=False,
    source_citation="Rowan-curated GC umbrella requirement for CA multi-family portfolios (synthetic)",
    source_url=None,
    last_verified_at=_VERIFIED,
)

# Full KB, as it would sit in `compliance_requirements`. Note: NO row exists
# for jurisdiction_state='CO' anywhere — that absence is the fallback fixture.
COMPLIANCE_REQUIREMENTS_KB: list[RetrievedRequirement] = [
    CR_CA_GENERIC_GL,
    CR_OAKLAND_GL,
    CR_LAKEVIEW_HOA_GL,
    CR_CA_GENERIC_AUTO,
    CR_CA_GENERIC_WC,
    CR_CA_GC_UMBRELLA,
]
# vendor_role scoping for the KB rows above (None = applies to any role, per
# ADR 0005). Kept as a side table here rather than on RetrievedRequirement
# because the contract's RetrievedRequirement (what a *query result* returns)
# intentionally doesn't carry jurisdiction/role predicate columns — those are
# the KB row's own filter criteria, matched by V1DeterministicRetriever, not
# something a query result needs to echo back.
KB_ROW_VENDOR_ROLE: dict[UUID, Optional[VendorRole]] = {
    CR_CA_GENERIC_GL.id: None,
    CR_OAKLAND_GL.id: None,
    CR_LAKEVIEW_HOA_GL.id: None,
    CR_CA_GENERIC_AUTO.id: None,
    CR_CA_GENERIC_WC.id: None,
    CR_CA_GC_UMBRELLA.id: VendorRole.GENERAL_CONTRACTOR,
}
KB_ROW_JURISDICTION: dict[UUID, dict] = {
    CR_CA_GENERIC_GL.id: {"state": "CA", "city": None, "hoa": None},
    CR_OAKLAND_GL.id: {"state": "CA", "city": "Oakland", "hoa": None},
    CR_LAKEVIEW_HOA_GL.id: {"state": "CA", "city": "Oakland", "hoa": "Lakeview HOA"},
    CR_CA_GENERIC_AUTO.id: {"state": "CA", "city": None, "hoa": None},
    CR_CA_GENERIC_WC.id: {"state": "CA", "city": None, "hoa": None},
    CR_CA_GC_UMBRELLA.id: {"state": "CA", "city": None, "hoa": None},
}


def effective_requirements_for(prop: PropertyFixture, role: VendorRole) -> list[RetrievedRequirement]:
    """Hand-computed reference implementation of ADR 0005's specificity
    ranking, used ONLY to compute fixtures' expected values — this is not
    production code and the real V1DeterministicRetriever must NOT import
    this. Reduces to one row per coverage_type, preferring the most specific
    jurisdiction match, and drops rows whose vendor_role predicate doesn't
    match (None = any)."""
    candidates = [
        r
        for r in COMPLIANCE_REQUIREMENTS_KB
        if KB_ROW_JURISDICTION[r.id]["state"] == prop.state
        and (KB_ROW_JURISDICTION[r.id]["city"] in (None, prop.city))
        and (KB_ROW_JURISDICTION[r.id]["hoa"] in (None, prop.hoa_name))
        and (KB_ROW_VENDOR_ROLE[r.id] in (None, role))
    ]

    def specificity(r: RetrievedRequirement) -> int:
        j = KB_ROW_JURISDICTION[r.id]
        return int(j["city"] is not None) + int(j["hoa"] is not None) + int(KB_ROW_VENDOR_ROLE[r.id] is not None)

    by_coverage: dict[CoverageType, RetrievedRequirement] = {}
    for r in sorted(candidates, key=specificity, reverse=True):
        by_coverage.setdefault(r.coverage_type, r)
    return list(by_coverage.values())
