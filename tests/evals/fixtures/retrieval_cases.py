"""
Retrieval-specific fixtures per ADR 0005: correct requirements retrieved for
a given jurisdiction/property/vendor-role query, INDEPENDENT of any document
or the full pipeline. `expected_requirement_ids` is hand-computed from the
ADR's specificity-ranking rule ("most-specific wins, NULL = applies to any"),
not derived from `base_org.effective_requirements_for` at fixture-eval time —
each case restates *why* by name so a reviewer can check the fixture without
reading the reference-implementation code.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from tests.evals.contracts.retrieval import RequirementsQuery
from tests.evals.contracts.validation import PropertyType, VendorRole
from tests.evals.fixtures.org_context import base_org as org


@dataclass
class RetrievalQueryCase:
    id: str
    description: str
    query: RequirementsQuery
    expected_found: bool
    # coverage_type -> the ONE compliance_requirements.id that should win for
    # that coverage type, per specificity ranking. Empty dict when expected_found=False.
    expected_winning_ids_by_coverage: dict[str, UUID]
    reasoning: str


RETRIEVAL_CASES: list[RetrievalQueryCase] = [
    RetrievalQueryCase(
        id="q1_city_specific_beats_state_generic",
        description="Oakland/multi_family/plumber: a city-specific GL row exists alongside a "
                     "CA-generic GL row for the same coverage_type — the city-specific one must win.",
        query=RequirementsQuery(
            organization_id=org.ORG_ID,
            jurisdiction_state="CA",
            jurisdiction_city="Oakland",
            jurisdiction_hoa=None,
            property_type=PropertyType.MULTI_FAMILY,
            vendor_role=VendorRole.PLUMBER,
        ),
        expected_found=True,
        expected_winning_ids_by_coverage={
            "general_liability": org.CR_OAKLAND_GL.id,
            "auto_liability": org.CR_CA_GENERIC_AUTO.id,
            "workers_comp": org.CR_CA_GENERIC_WC.id,
        },
        reasoning="CR_OAKLAND_GL (jurisdiction_city='Oakland') outranks CR_CA_GENERIC_GL "
                  "(jurisdiction_city=NULL) on specificity for coverage_type=general_liability. "
                  "Auto/WC have only one candidate each (role-and-city-agnostic), so those pass "
                  "through unchanged.",
    ),
    RetrievalQueryCase(
        id="q2_no_city_row_falls_through_to_generic",
        description="Fresno/multi_family/hvac: no Fresno-specific KB row exists, so the CA-generic "
                     "GL row applies — this is `found=True` with the generic row, NOT the "
                     "empty-retrieval fallback (that's a different failure mode, see q4).",
        query=RequirementsQuery(
            organization_id=org.ORG_ID,
            jurisdiction_state="CA",
            jurisdiction_city="Fresno",
            jurisdiction_hoa=None,
            property_type=PropertyType.MULTI_FAMILY,
            vendor_role=VendorRole.HVAC,
        ),
        expected_found=True,
        expected_winning_ids_by_coverage={
            "general_liability": org.CR_CA_GENERIC_GL.id,
            "auto_liability": org.CR_CA_GENERIC_AUTO.id,
            "workers_comp": org.CR_CA_GENERIC_WC.id,
        },
        reasoning="CR_CA_GENERIC_GL has jurisdiction_city=NULL ('applies to any'), matching Fresno "
                  "by the NULL-means-any rule since no more specific Fresno row exists.",
    ),
    RetrievalQueryCase(
        id="q3_hoa_specific_beats_city_specific",
        description="Oakland/condo/roofer at Lakeview HOA: the HOA-specific GL row must win over "
                     "both the city-specific and state-generic GL rows (three-way specificity test).",
        query=RequirementsQuery(
            organization_id=org.ORG_ID,
            jurisdiction_state="CA",
            jurisdiction_city="Oakland",
            jurisdiction_hoa="Lakeview HOA",
            property_type=PropertyType.CONDO,
            vendor_role=VendorRole.ROOFER,
        ),
        expected_found=True,
        expected_winning_ids_by_coverage={
            "general_liability": org.CR_LAKEVIEW_HOA_GL.id,
            "auto_liability": org.CR_CA_GENERIC_AUTO.id,
            "workers_comp": org.CR_CA_GENERIC_WC.id,
        },
        reasoning="CR_LAKEVIEW_HOA_GL (city='Oakland' AND hoa='Lakeview HOA') has specificity "
                  "score 2, beating CR_OAKLAND_GL (score 1) and CR_CA_GENERIC_GL (score 0) for "
                  "the same coverage_type.",
    ),
    RetrievalQueryCase(
        id="q4_no_kb_rows_for_jurisdiction_is_fallback_not_generic",
        description="Denver/CO/multi_family/plumber: ZERO KB rows exist for state='CO' anywhere. "
                     "This must return found=False, not an empty-but-'found' result — the fallback "
                     "path (escalate, never guess) depends on that boolean, not on list emptiness "
                     "being interpreted contextually.",
        query=RequirementsQuery(
            organization_id=org.ORG_ID,
            jurisdiction_state="CO",
            jurisdiction_city="Denver",
            jurisdiction_hoa=None,
            property_type=PropertyType.MULTI_FAMILY,
            vendor_role=VendorRole.PLUMBER,
        ),
        expected_found=False,
        expected_winning_ids_by_coverage={},
        reasoning="No compliance_requirements row in the fixture KB has jurisdiction_state='CO'. "
                  "Per ADR 0005, retrieve() must set found=False here, not return an empty list "
                  "under found=True (those are different signals to the state machine).",
    ),
    RetrievalQueryCase(
        id="q5_role_specific_row_excluded_for_nonmatching_role",
        description="Oakland/multi_family/landscaper: the general_contractor-only umbrella_excess "
                     "row must NOT be returned for a landscaper query.",
        query=RequirementsQuery(
            organization_id=org.ORG_ID,
            jurisdiction_state="CA",
            jurisdiction_city="Oakland",
            jurisdiction_hoa=None,
            property_type=PropertyType.MULTI_FAMILY,
            vendor_role=VendorRole.LANDSCAPER,
        ),
        expected_found=True,
        expected_winning_ids_by_coverage={
            "general_liability": org.CR_OAKLAND_GL.id,
            "auto_liability": org.CR_CA_GENERIC_AUTO.id,
            "workers_comp": org.CR_CA_GENERIC_WC.id,
            # deliberately NO "umbrella_excess" key — CR_CA_GC_UMBRELLA is
            # vendor_role='general_contractor'-scoped and must be excluded.
        },
        reasoning="CR_CA_GC_UMBRELLA's vendor_role predicate is general_contractor (not NULL), so "
                  "it fails the role match for vendor_role=landscaper and must not appear in the "
                  "result at all — contrast with q1-q3 where every candidate had vendor_role=NULL "
                  "('any').",
    ),
]
