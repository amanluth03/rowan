# Rowan — Timeline to W27 (Jul 27 → Sep 25, 2026)

**Constraint:** 8.5 weeks, both founders part-time (~15 focused hrs/wk each).
**Definition of success:** 1–3 paying customers · 2 seeded jurisdictions · audit export shipped · a demo that shows a compliance *ledger*, not a COI tracker.

---

## Operating principle

Every sprint runs a **sell track** and a **build track** in parallel. A sprint with zero customer conversations failed, regardless of what shipped.

You have a security-audited v1 with 209 passing tests and zero revenue. The bottleneck has never been engineering. Both founders are engineers, and a board full of build tickets is the most comfortable way to avoid the hard thing.

**Rule: the board must always have at least as many open EPIC-7 tickets as engineering tickets.**

---

## Sprint 1 — Jul 27 → Aug 9 · *Foundations + Seed*

**Build:** ROW-601 (real auth), ROW-602/603 (live keys, one real cert), ROW-101/102/103 (schema), ROW-105 (seed jurisdiction #1)
**Sell:** ROW-701 — 10 interviews using the liability script. Pick the beachhead metro from jurisdiction counts.

**Exit criteria**
- A real user can log in
- One real certificate ran through the live loop
- Jurisdiction #1 exists as verified, cited data
- ≥1 verbal pilot commitment

---

## Sprint 2 — Aug 10 → Aug 23 · *The Ledger Becomes Real*

**Build:** ROW-201/202/203/204 (obligation engine), ROW-206, ROW-301 (CSV import), ROW-302
**Sell:** ROW-702 (pricing + Stripe), ROW-703 — convert verbal → **paid**. Keep pipeline at 5+.

**Exit criteria**
- Add a property → full obligation list auto-generates with citations and due dates
- CSV import works on a real Buildium export
- **First invoice sent**

> This sprint produces the demo that sells. If you are behind, protect this above everything else.

---

## Sprint 3 — Aug 24 → Sep 6 · *Proof + Friction*

**Build:** ROW-501/502/504 (audit export), ROW-604 (cron), ROW-401/402 (dashboard + detail)
**Sell:** ROW-704 — customer #2. Onboard #1 for real and watch where they get stuck.

**Exit criteria**
- One-click audit export of a customer's compliance record
- Recurring checks run on a real schedule
- Customer #1 using it weekly, unprompted
- Customer #2 closed

---

## Sprint 4 — Sep 7 → Sep 20 · *Harden + Write*

**Build:** ROW-107 (jurisdiction #2), ROW-503, ROW-404, ROW-605, ROW-606 (rename)
**Sell:** ROW-705 (testimonial + quantified before/after), ROW-706 (ICP alignment), ROW-707 (YC app + both founder profiles)

**Freeze: no new features after Sep 15.** Bug-fix only.

**Exit criteria**
- Jurisdiction #2 added with no schema changes
- YC application drafted, both founder profiles fully complete
- Demo video recorded

---

## Cutover — Sep 21 → 25 · *Submit*

**Submit by Sep 22**, not the 25th. The remaining days are buffer for the demo video and a final read.

---

## Milestone dates

| Date | Milestone |
|---|---|
| Aug 2 | Real auth live |
| Aug 9 | Jurisdiction #1 seeded · 10 interviews done |
| Aug 16 | Obligation engine generating dated obligations |
| **Aug 23** | **First paying customer** |
| Sep 6 | Audit export shipped · customer #2 |
| Sep 15 | Feature freeze |
| Sep 20 | YC app drafted |
| **Sep 22** | **Submit** |

---

## Risk register & cut order

If you fall behind, cut in **this order**:

1. **ROW-305** Buildium sync — CSV covers onboarding
2. **ROW-107** Jurisdiction #2 — one well-seeded city beats two half-seeded ones
3. **ROW-606** Rename — documented debt, no customer value
4. **ROW-404** Weekly digest — nice, not load-bearing
5. **ROW-403** Task assignment — one persona is fine for a pilot

**Never cut:** the sell track (EPIC 7), the obligation engine (EPIC 2), or the audit export (EPIC 5). Those three are the product.

**Top risks**
- *No paying customer by Aug 23* → the schedule is not the problem; the pitch or the ICP is. Stop building and run 10 more interviews.
- *Jurisdiction seeding takes longer than estimated* → likely. It's research, not code. Start it Sprint 1, not Sprint 2.
- *Part-time capacity slips under work pressure* → the single largest schedule risk. Build the buffer in now; don't discover it in September.

---

## Weekly cadence

- **Monday 30 min:** what shipped, what sold, what's blocked
- **Friday 15 min:** sprint-exit check against the criteria above
- **Every week:** at least one customer conversation each. No exceptions.
