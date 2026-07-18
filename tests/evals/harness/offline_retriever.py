"""Offline, in-memory mirror of `app.retrieval.requirements_retriever.
V1DeterministicRetriever` (ADR 0005's production implementation, backend/
app/retrieval/requirements_retriever.py), built to close the seam
`harness/retriever_adapter.py` left open (`ROWAN_RETRIEVER_ENTRYPOINT`).

WHY THIS FILE EXISTS RATHER THAN POINTING THE EVAL HARNESS AT THE REAL CLASS
DIRECTLY: the production `V1DeterministicRetriever` takes an `asyncpg.
Connection` and issues real SQL against `compliance_requirements` — correct
for the live system, but `tests/evals/test_retrieval.py` is written to run
fully offline against `RETRIEVAL_CASES` fixture data
(`tests/evals/fixtures/retrieval_cases.py`) with NO Postgres dependency, via
a SYNCHRONOUS `retriever.retrieve(query)` call and a `kb_rows=` constructor
kwarg (see that test's own `# ASSUMPTION` note — the constructor shape was
explicitly left for whoever lands the real retriever to confirm). This class
is that confirmation: it implements the IDENTICAL algorithm as the
production class —

  - predicate match: state MUST match; city/hoa/vendor_role NULL-on-the-KB-
    row means "applies to any" (ADR 0005's rule, verbatim)
  - specificity ranking: prefer city/hoa/role-specific rows over "any" ones
  - reduce to exactly one row per coverage_type

— evaluated in plain Python over an in-memory KB list instead of via SQL,
so the eval suite can assert retrieval correctness (specificity ranking,
role-scoping, the empty-retrieval fallback) without a live database, exactly
mirroring the SQL in app/retrieval/requirements_retriever.py's docstring
line for line. This is NOT a second production implementation — ADR 0005 has
exactly one retriever backing the live agent (`V1DeterministicRetriever`
over Postgres); this file is test-fixture-only code that never ships.

# ASSUMPTION: coupled to `tests.evals.fixtures.org_context.base_org`'s
# `KB_ROW_JURISDICTION` / `KB_ROW_VENDOR_ROLE` side tables for predicate
# data, because the eval CONTRACT's `RetrievedRequirement`
# (tests/evals/contracts/retrieval.py) deliberately does NOT carry
# jurisdiction/vendor_role columns on the row itself (see that fixture
# module's own docstring — those columns describe a KB row's own filter
# criteria, not something a query RESULT needs to echo back), and
# `tests/evals/test_retrieval.py` calls `retriever_class(kb_rows=...)` with
# only the flat list. A from-scratch KB fixture set that wants this offline
# retriever to work must register its jurisdiction/role predicates in those
# same two dicts. `property_type` is deliberately not filtered here because
# no row in the current fixture KB is property_type-scoped (mirrors
# `base_org.py::effective_requirements_for`'s reference implementation,
# which also skips it) — add it if a future fixture needs it.
"""

from __future__ import annotations

from tests.evals.contracts.retrieval import RequirementsQuery, RetrievalResult, RetrievedRequirement
from tests.evals.fixtures.org_context.base_org import KB_ROW_JURISDICTION, KB_ROW_VENDOR_ROLE


class V1DeterministicRetriever:
    def __init__(self, *, kb_rows: list[RetrievedRequirement]) -> None:
        self._kb_rows = kb_rows

    def retrieve(self, q: RequirementsQuery) -> RetrievalResult:
        candidates: list[tuple[RetrievedRequirement, dict, object]] = []
        for row in self._kb_rows:
            jurisdiction = KB_ROW_JURISDICTION.get(row.id)
            role = KB_ROW_VENDOR_ROLE.get(row.id)
            if jurisdiction is None:
                # Row not registered in the fixture's predicate side-table —
                # cannot be matched; skip rather than guess its scope.
                continue
            if jurisdiction["state"] != q.jurisdiction_state:
                continue
            if jurisdiction["city"] is not None and jurisdiction["city"] != q.jurisdiction_city:
                continue
            if jurisdiction["hoa"] is not None and jurisdiction["hoa"] != q.jurisdiction_hoa:
                continue
            if role is not None and role != q.vendor_role:
                continue
            candidates.append((row, jurisdiction, role))

        if not candidates:
            return RetrievalResult(requirements=[], found=False, query=q)

        def specificity(item: tuple[RetrievedRequirement, dict, object]) -> int:
            _row, jurisdiction, role = item
            return (
                int(jurisdiction["city"] is not None)
                + int(jurisdiction["hoa"] is not None)
                + int(role is not None)
            )

        # Reduce to one row per coverage_type: most-specific wins (ADR 0005),
        # matching the production SQL's
        # `ORDER BY coverage_type, specificity DESC` + "first row per group".
        best_by_coverage: dict[object, RetrievedRequirement] = {}
        for row, jurisdiction, role in sorted(candidates, key=specificity, reverse=True):
            best_by_coverage.setdefault(row.coverage_type, row)

        return RetrievalResult(requirements=list(best_by_coverage.values()), found=True, query=q)
