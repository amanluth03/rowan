# Rowan — MVP Product Backlog

**Owner:** Aman · **Target:** W27 application, Sep 25 2026
**Priority key:** P0 = MVP blocker · P1 = MVP, cut only under duress · P2 = stretch
**Size:** S ≈ ½ day · M ≈ 1–2 days · L ≈ 3–5 days *(part-time days)*

---

## MVP definition

> A landlord adds their properties. Rowan tells them every compliance obligation across every jurisdiction those properties sit in — with citations and due dates — automatically executes the vendor-COI loop, and produces an audit-ready record on demand.

**Not in MVP:** regulatory change-monitoring agent, PM-software API integrations, lease generation, maintenance, tenant workflows, expense/tax.

---

# EPIC 1 — Compliance Knowledge Base
**Goal:** the moat exists as queryable, cited, versioned data.
**Done when:** two cities are seeded and a non-engineer can add a third without touching SQL.

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-101 | Jurisdiction table w/ hierarchy | P0 | M | — |
| ROW-102 | Requirement table (ADR 0006) | P0 | L | 101 |
| ROW-103 | Append-only requirement versioning | P0 | M | 102 |
| ROW-104 | GIN index + match benchmark | P1 | S | 102 |
| ROW-105 | Seed jurisdiction #1 (hand-curated) | P0 | L | 102 |
| ROW-106 | Internal requirement admin UI | P1 | M | 102 |
| ROW-107 | Seed jurisdiction #2 | P1 | M | 106 |

**ROW-101 — Jurisdiction table w/ hierarchy**
*As Rowan, I need to model federal → state → county → municipality so a property is subject to every level of its stack.*
- [ ] Self-referential `parent_id`; levels enum
- [ ] Seeding a municipality auto-resolves its full parent chain
- [ ] `source_portal_url` stored per jurisdiction (where filings happen)

**ROW-102 — Requirement table**
*As Rowan, I need requirements as first-class cited objects so obligations can be generated and defended.*
- [ ] Fields per ADR 0006: category, applicability (JSONB), trigger, cadence, deadline_rule, action, required_artifacts, penalty, citation, source_url, verification, effective_date, last_reviewed_at
- [ ] DB-level constraint: `citation` and `source_url` NOT NULL
- [ ] `verification.status` defaults to `unverified`

**ROW-103 — Append-only versioning**
*As a customer, I need to know what the rule was when I filed, not just what it is now.*
- [ ] Updating a requirement creates a new row; old row remains queryable
- [ ] `superseded_by` links versions
- [ ] Existing obligations retain their pinned version

**ROW-105 — Seed jurisdiction #1**
*The single highest-value non-code ticket in the backlog.*
- [ ] 20–50 requirements covering registration, inspection, disclosure, insurance, licensing
- [ ] Every requirement verified against the actual ordinance + filing portal
- [ ] A domain-naive reader can follow each citation to source text
- [ ] Includes at least one exemption case (e.g. owner-occupied ≤N units)

**ROW-107 — Seed jurisdiction #2**
- [ ] **No schema changes required.** If this ticket forces a migration, the model is wrong — stop and fix ROW-102.

---

# EPIC 2 — Obligation Engine
**Goal:** add a property → get its complete dated obligation set.
**Done when:** the demo works with zero manual obligation entry. *This is the demo that sells.*

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-201 | Property model + attributes | P0 | M | — |
| ROW-202 | Address → geocode → jurisdiction stack | P0 | M | 101, 201 |
| ROW-203 | Applicability predicate evaluator | P0 | M | 102 |
| ROW-204 | Obligation instantiation + due dates | P0 | L | 203 |
| ROW-205 | Re-match on requirement version change | P1 | M | 103, 204 |
| ROW-206 | Obligation → Task decomposition | P0 | M | 204 |

**ROW-203 — Applicability predicate evaluator**
- [ ] Supports `>=`, `<=`, `<`, `>`, `in`, equality
- [ ] Unit-tested against 20 fixture predicates including exemptions
- [ ] Unknown/missing property attribute → flag for human review, never silently skip

- **Partial renewals:** all-or-nothing validation. A COI is validated as one unit against every required coverage line. Any missing, stale, or failing line fails the whole validation and routes to `needs_human_review` — never partially filed.
- **Multi-property COIs:** one requirement set per vendor, org-wide (not per-property). A vendor has a single set of required coverage minimums regardless of how many properties they service.
- Both of these are v1 scoping calls made to keep the state machine and schema simple; if real-world usage proves them wrong, that's a v2 revisit, not a v1 blocker.
- **Accounts and roles (ROW-101):** real Supabase-backed accounts. One organization per signup, with the signing-up user as its owner. Two roles:
  - `owner` — everything.
  - `assistant` — reads everything in the org and operates the renewal loop (start/pause/resume a run, request a revision), but may NOT change the vendor roster or coverage requirements, approve or reject a COI, resolve an escalation, or manage the team.

  Approving a COI is the moment Rowan asserts "you're covered." Dana's licence is on the line, so that sign-off stays with her; the chasing does not. Assistants join by emailed invitation — single-use, expiring, email-bound.

  **This supersedes the earlier `multi-user orgs` non-goal.** Authorization is enforced as a default-deny data table (`app/policy/permissions.py::COMMAND_ROLES`), not scattered conditionals: a command with no entry raises rather than allows. See `docs/adr/0007-authentication-and-authorization.md`.

**ROW-206 — Obligation → Task decomposition**
- [ ] COI-category obligations route into the **existing shipped v1 loop**
- [ ] Non-COI obligations generate human tasks with persona assignment
- [ ] `agent_executable` flag set per task

---

# EPIC 3 — Portfolio Onboarding
**Goal:** 10-minute onboarding on any stack. Onboarding friction is how SMB SaaS dies at the front door.

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-301 | CSV import w/ column mapping | P0 | M | 201 |
| ROW-302 | Manual property add form | P0 | S | 201 |
| ROW-303 | Per-org email ingestion address | P1 | M | — |
| ROW-304 | Spike: Buildium API access terms | P2 | S | — |
| ROW-305 | Buildium read-only sync (flagged) | P2 | L | 304 |

**ROW-301 — CSV import**
- [ ] A Buildium property export imports without hand-editing
- [ ] Column-mapping UI with preview before commit
- [ ] Validation errors shown per-row, partial import allowed

**ROW-304 — Buildium API spike**
- [ ] **Timeboxed to 4 hours.** Verify current access terms, auth model, available endpoints
- [ ] Output: written go/no-go, not code

---

# EPIC 4 — Compliance Workspace
**Goal:** the single screen that sells the product.

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-401 | Portfolio compliance dashboard | P0 | L | 204 |
| ROW-402 | Property detail view | P0 | M | 204 |
| ROW-403 | Task assignment to persona | P1 | M | 206 |
| ROW-404 | Weekly digest email | P1 | M | 204 |

**ROW-401 — Portfolio dashboard**
- [ ] Every property, obligation counts by status, next-30-days due
- [ ] Overdue items visually dominant
- [ ] Loads in <2s for a 100-property portfolio

**ROW-402 — Property detail**
- [ ] Full obligation list: requirement title, citation link, due date, status, evidence
- [ ] Citation is clickable through to source_url

---

# EPIC 5 — Audit & Evidence
**Goal:** the artifact that proves compliance to an insurer, owner, or inspector. Elevated to critical path by product-context.md.

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-501 | Export data assembly | P0 | M | 204 |
| ROW-502 | PDF renderer | P0 | M | 501 |
| ROW-503 | Point-in-time reconstruction | P1 | M | 103, 501 |
| ROW-504 | Export UI + email delivery | P0 | S | 502 |

**ROW-502 — PDF renderer**
- [ ] Letterhead, generation timestamp, per-item citations, evidence references
- [ ] <10s for a 50-property portfolio

**ROW-503 — Point-in-time reconstruction**
- [ ] "What did we believe the rules were on 2026-03-01" uses pinned `requirement_version`, not current state

---

# EPIC 6 — Production Foundations
**Goal:** a real customer can actually use this. Currently blocked by a dev-org stub.

| ID | Title | Priority | Size | Depends |
|---|---|---|---|---|
| ROW-601 | Real auth + org model | **P0 — first ticket** | L | — |
| ROW-602 | Live Resend/Anthropic keys + secrets | P0 | S | — |
| ROW-603 | One real certificate through live loop | P0 | S | 602 |
| ROW-604 | Real cron scheduler | P0 | M | — |
| ROW-605 | Founder error alerting | P1 | S | — |
| ROW-606 | `vendor_role → insured_party` rename | P2 | M | 102 |

**ROW-601 — Real auth**
*Blocks every customer conversation that ends in "great, set it up." Do this first.*
- [ ] Replace dev-org stub with real org model
- [ ] Multi-org isolation verified by test
- [ ] Owner + assistant roles

**ROW-603 — One real certificate live**
- [ ] Observed end-to-end with real keys
- [ ] Written log of everything that broke

**ROW-606 — Rename**
- [ ] Do in the final sprint, not before. Abstraction only becomes load-bearing once the schema lands.

---

# EPIC 7 — Pilot Operations *(non-engineering — equal weight)*
**Goal:** paying customers. Track this on the same board as engineering or it will lose every time.

Payments, city portal integration, SMS, vendor portal logins, bulk import, OCR fallback, vector search, third-party observability/eval platforms.

**Superseded:** `multi-user orgs` was listed here until ROW-101 (Real login and accounts), which deliberately reversed it — see Locked product decisions below and `docs/adr/0007-authentication-and-authorization.md`.

**ROW-706 — ICP alignment**
*Aman says small-medium self-managers; Armaan wrote "midsize external PM company." Inconsistent cofounder answers is a commonly cited YC rejection reason. Resolve in writing before any interview.*

---

# Explicitly out of scope
Regulatory change-monitoring agent (EPIC 7 of the old plan — post-batch). AppFolio/Yardi integrations. Lease generation (UPL risk). Tenant acquisition, screening, payments. Maintenance ticketing. Expense/tax tracking. Mobile app. Permissions beyond owner/assistant.
