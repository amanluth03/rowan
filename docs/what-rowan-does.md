# What Rowan does — and what it doesn't (yet)

*Vendor Certificate of Insurance (COI) Renewal Agent — v1*

## The problem this solves

Every vendor you work with — plumbers, electricians, landscapers, roofers — is supposed to carry insurance that meets your requirements, and that insurance expires every year. Tracking who's covered, chasing renewals, and checking that a new certificate actually meets your coverage minimums is the kind of work that's easy to let slip until a claim gets denied or an owner asks a question you can't answer. Rowan takes this off your plate.

## What Rowan does today

**Watches every vendor's insurance expiration date automatically.** No spreadsheet, no calendar reminders you have to set yourself.

**Reaches out to the vendor when a renewal is coming due**, by email, asking for an updated certificate. If they don't respond, Rowan follows up automatically — a capped number of times, so vendors aren't spammed — before flagging it to you.

**Reads the certificate the vendor sends back** and checks it against the coverage you require for that vendor: liability limits, whether you're listed as an additional insured, waiver of subrogation, and so on.

**Makes a clean call, every time:**
- If the certificate fully meets your requirements → Rowan files it, marks the vendor covered, and tells you it's handled.
- If anything is missing, expired, or below your minimums → Rowan **never guesses or lets it slide**. It stops and puts it in front of you with exactly what's wrong, so you decide.

**Shows its work.** Every email sent, every document read, every check performed is logged in a visible timeline — the certificate, the values Rowan pulled from it, and where each requirement came from. You can always see *why* Rowan says a vendor is covered, not just that it says so.

**Stays under your control.** You can pause any single vendor and take over by hand, or flip one switch to pause Rowan across your entire account. Nothing runs while you've paused it.

## What Rowan does not do (yet)

This is v1, scoped deliberately narrow so the core loop is solid before it grows. Known, honest limits:

- **Vendor COI renewals only.** Rental registrations, inspection deadlines, lead paint and habitability disclosures, and smoke/CO certification tracking are not part of this build.
- **One coverage requirement set per vendor**, account-wide — not different requirements per property. If a vendor works across multiple properties with genuinely different insurance requirements, that's not supported yet.
- **All-or-nothing certificate review.** If a vendor renews some coverage but not all of it, the whole certificate goes to you for review rather than partially filing what's clean. Keeps the logic simple and honest; may get more granular later.
- **One account, one user.** Team accounts with multiple staff logins aren't built yet.
- **No payments, no city/county portal filing, no text messages, no vendor self-service login, no bulk spreadsheet import.** These are explicitly out of scope for v1.
- **This is a working demo build, not yet live with real customer data.** The system currently uses a placeholder for account login (not real authentication) — this must be replaced before any real account or real vendor data touches it. It has been tested thoroughly against realistic synthetic test documents, including attempts to trick it with fake instructions embedded in a document, but has not yet processed real-world document volume at scale.

## Where things stand right now

The full loop — add a vendor, set requirements, Rowan reaches out, reads what comes back, validates it, and either files it or flags it for you — works end-to-end and has been tested against 18 realistic scenarios (clean renewals, expired policies, coverage below your minimums, unreadable scans, and documents deliberately crafted to try to trick the system into approving something it shouldn't). All 18 pass. Every step of the process — including the parts that touch real vendor data — has been through a dedicated security review before being added, catching and fixing real issues (a file-handling bug, a webhook without a size limit, a document-serving bug) before they shipped, not after.
