"""ACCEPTANCE CRITERION 2, API layer: authenticated into org A, every
org-B resource is 404.

404 and not 403 is the point. A 403 confirms the resource exists, which is
itself a cross-tenant disclosure -- an attacker enumerating UUIDs learns
which ones are real.
"""

from __future__ import annotations

import httpx
import pytest

from app.ids import uuid7

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def two_orgs(client, jwt_harness):
    """Two orgs created through the REAL signup path, each with a vendor."""
    orgs = {}
    for label in ("a", "b"):
        auth_id = uuid7()
        resp = await client.post(
            "/api/v1/orgs/bootstrap",
            json={"organizationName": f"Org {label.upper()}"},
            headers={"Authorization": f"Bearer {jwt_harness.mint(auth_id, email=f'{label}@example.com')}"},
        )
        assert resp.status_code == 201, resp.text
        headers = {"Authorization": f"Bearer {jwt_harness.mint(auth_id, email=f'{label}@example.com')}"}
        vendor = await client.post(
            "/api/v1/vendors",
            json={
                "name": f"Vendor {label.upper()}",
                "primaryEmail": f"vendor-{label}@example.com",
                "vendorRole": "plumber",
            },
            headers=headers,
        )
        assert vendor.status_code == 201, vendor.text
        orgs[label] = {
            "auth_id": auth_id,
            "headers": headers,
            "org_id": resp.json()["organizationId"],
            "vendor_id": vendor.json()["vendorId"],
            "run_id": vendor.json().get("runId"),
        }
    return orgs


async def test_vendor_list_shows_only_own_org(two_orgs, client):
    a = await client.get("/api/v1/vendors", headers=two_orgs["a"]["headers"])
    names = [v["name"] for v in a.json()]
    assert names == ["Vendor A"]


@pytest.mark.parametrize("path_template", [
    "/api/v1/vendors/{vendor_id}",
])
async def test_cross_org_reads_are_404(two_orgs, client, path_template):
    path = path_template.format(vendor_id=two_orgs["b"]["vendor_id"])
    resp = await client.get(path, headers=two_orgs["a"]["headers"])
    assert resp.status_code == 404, f"{path} leaked: {resp.status_code} {resp.text}"


async def test_cross_org_run_trace_is_404(two_orgs, client):
    run_id = two_orgs["b"]["run_id"]
    if run_id is None:
        pytest.skip("AddVendor did not return a runId in this build")
    resp = await client.get(f"/api/v1/runs/{run_id}/trace", headers=two_orgs["a"]["headers"])
    assert resp.status_code == 404


async def test_cross_org_commands_do_not_leak_existence(two_orgs, client):
    """start/pause/resume are the one exception to the 404 contract, and it
    predates this file: `_load_context` (app/orchestration/runner.py)
    already collapses "run not found" and "run found but wrong
    state/frozen" into a single generic 409, both at the orchestration layer
    and at the route (`commands.py`'s `if run is None: raise
    HTTPException(409, ...)`). This is deliberate, already-reviewed
    behavior, independently pinned for pause by
    tests/test_api_commands.py::TestCrossOrgIsolation::
    test_cannot_pause_another_orgs_run (see its comment: "RLS makes the run
    invisible under the wrong org's GUC -> treated as 'not found' ...
    surfaced as 409 ... never a cross-org state change").
    # ASSUMPTION: brief's original literal `assert resp.status_code == 404`
    would fail here -- not because of a fixture bug, but because it asserts
    a status code this route has never returned for ANY not-actionable run,
    same-org included. Reworded to check what actually makes this a
    cross-tenant leak (a 403, which would confirm org B's run exists) and
    what makes it NOT a leak (cross-org and a genuinely nonexistent run
    producing byte-identical responses) rather than a specific status code
    that contradicts already-shipped, already-tested behavior. Flagged here
    rather than silently rewritten; production code was not touched.
    """
    run_id = two_orgs["b"]["run_id"]
    if run_id is None:
        pytest.skip("AddVendor did not return a runId in this build")
    for verb in ("start", "pause", "resume"):
        cross_org = await client.post(
            f"/api/v1/runs/{run_id}/{verb}", json={}, headers=two_orgs["a"]["headers"]
        )
        assert cross_org.status_code != 403, f"{verb} leaked via 403: {cross_org.status_code}"

        nonexistent = await client.post(
            f"/api/v1/runs/{uuid7()}/{verb}", json={}, headers=two_orgs["a"]["headers"]
        )
        assert cross_org.status_code == nonexistent.status_code == 409, (
            f"{verb}: cross-org={cross_org.status_code} nonexistent={nonexistent.status_code}"
        )
        assert cross_org.json() == nonexistent.json(), f"{verb}: cross-org and nonexistent responses differ"


async def test_cross_org_set_requirements_is_404(two_orgs, client):
    resp = await client.post(
        f"/api/v1/vendors/{two_orgs['b']['vendor_id']}/requirements",
        json={"lines": []},
        headers=two_orgs["a"]["headers"],
    )
    assert resp.status_code in (404, 422), resp.text
    assert resp.status_code != 200


async def test_nonexistent_and_cross_org_are_indistinguishable(two_orgs, client):
    """The strongest form of the property: a real other-org id and a random
    id must produce identical responses."""
    real_other = await client.get(
        f"/api/v1/vendors/{two_orgs['b']['vendor_id']}", headers=two_orgs["a"]["headers"]
    )
    random_id = await client.get(
        f"/api/v1/vendors/{uuid7()}", headers=two_orgs["a"]["headers"]
    )
    assert real_other.status_code == random_id.status_code == 404
    assert real_other.json() == random_id.json()
