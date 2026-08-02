-- 0010_compliance_kb: jurisdiction + requirement tables (EPIC 1 — compliance
-- knowledge base). These are landlord-compliance obligations (registration,
-- disclosure, inspection, safety, fee) — separate from the vendor-COI
-- compliance_requirements table (0004) which tracks vendor insurance minimums.
--
-- DEMO schema: no versioning, no freshness monitoring, no obligation engine
-- yet. Shape of the data is the point. Seed data is Illinois / Chicago.
--
-- PENALTY FIELDS:
--   penalty_text            = source of truth. Full description exactly as
--                             the ordinance frames it. Never computed.
--   penalty_amount_display  = AI-drafted-at-ingest, human-verified short label
--                             for UI display. App only ever READS this column.

-- ------------------------------------------------------------
-- 1. jurisdiction
-- ------------------------------------------------------------
create table compliance_jurisdictions (
    id          serial primary key,
    name        text not null,
    level       text not null check (level in ('federal', 'state', 'county', 'municipal')),
    parent_id   integer references compliance_jurisdictions(id),
    portal_url  text
);

-- ------------------------------------------------------------
-- 2. requirement
-- ------------------------------------------------------------
create table compliance_obligations (
    id                      serial primary key,
    jurisdiction_id         integer not null references compliance_jurisdictions(id),

    category                text not null check (category in ('registration', 'disclosure', 'inspection', 'insurance', 'safety', 'fee')),
    title                   text not null,
    summary                 text,

    due_description         text,
    due_date                date,

    property_type           text,
    min_units               integer,
    max_units               integer,
    build_year_before       integer,

    penalty_text            text,
    penalty_amount_display  text,

    citation                text,
    source_url              text
);

create index ix_compliance_obligations_jurisdiction_id on compliance_obligations(jurisdiction_id);
create index ix_compliance_obligations_category on compliance_obligations(category);

-- ------------------------------------------------------------
-- 3. View: requirement with jurisdiction name (convenience read)
-- ------------------------------------------------------------
create view compliance_obligation_detail as
select
    o.id,
    j.name              as jurisdiction,
    j.level             as jurisdiction_level,
    o.category,
    o.title,
    o.summary,
    o.due_description,
    o.due_date,
    o.property_type,
    o.min_units,
    o.max_units,
    o.build_year_before,
    o.penalty_text,
    o.penalty_amount_display,
    o.citation,
    o.source_url
from compliance_obligations o
join compliance_jurisdictions j on j.id = o.jurisdiction_id;

-- ------------------------------------------------------------
-- SEED: Illinois / Chicago
-- ------------------------------------------------------------
insert into compliance_jurisdictions (name, level, parent_id, portal_url) values
    ('United States',     'federal',   null, null),                                 -- 1
    ('State of Illinois', 'state',     null, null),                                 -- 2
    ('City of Chicago',   'municipal', 2,    'https://www.chicago.gov/');           -- 3

insert into compliance_obligations
    (jurisdiction_id, category, title, summary, due_description, due_date,
     property_type, min_units, max_units, build_year_before,
     penalty_text, penalty_amount_display, citation, source_url)
values
    -- Federal: lead paint disclosure
    (1, 'disclosure', 'Lead-Based Paint Disclosure',
     'Provide EPA lead-paint pamphlet and known-hazard disclosure to tenants before lease signing.',
     'Before lease signing', null,
     'residential', null, null, 1978,
     'Civil penalties per violation plus potential treble damages in tenant suits and lease-level liability.',
     'Up to ~$21,000/violation',
     '24 CFR Part 35 / 42 U.S.C. 4852d', null),

    -- Illinois: security deposit itemized statement
    (2, 'disclosure', 'Security Deposit Itemized Statement',
     'If withholding from a deposit, provide the tenant an itemized statement of damages within 30 days of move-out.',
     'Within 30 days of tenant move-out', null,
     'residential', null, null, null,
     'Tenant may recover an amount equal to twice the deposit withheld, plus court costs and attorney fees.',
     '2× deposit withheld',
     '765 ILCS 710', null),

    -- Illinois: security deposit interest (25+ units)
    (2, 'fee', 'Security Deposit Interest',
     'Pay annual interest on security deposits held for buildings with 25 or more units.',
     'Annually', null,
     'residential', 25, null, null,
     'Liability to the tenant for unpaid interest; tenant remedies available for failure to pay.',
     'Unpaid interest owed',
     '765 ILCS 715', null),

    -- Chicago: annual rental registration
    (3, 'registration', 'Annual Rental Registration',
     'Register the rental property with the city each year.',
     'Annually by July 1', '2026-07-01',
     'residential', 1, null, null,
     'Loss of the right to raise rent or pursue eviction until registered; possible per-day fines for continued non-compliance.',
     'Rent/eviction rights frozen + fines',
     'Chicago Muni Code 5-12', null),

    -- Chicago: smoke detector requirement
    (3, 'safety', 'Smoke Detector Installation & Maintenance',
     'Install and maintain working smoke detectors on every floor and outside each sleeping area.',
     'Prior to occupancy; maintain continuously', null,
     'residential', null, null, null,
     'Landlord liable for actual damages, attorney fees, and court costs if detector is missing or non-functional and tenant is injured.',
     'Actual damages + attorney fees',
     'Chicago Muni Code 13-64-130', null),

    -- Chicago: carbon monoxide detector
    (3, 'safety', 'Carbon Monoxide Detector Installation',
     'Install CO detectors in units with fuel-burning appliances or attached garages.',
     'Prior to occupancy; maintain continuously', null,
     'residential', null, null, null,
     'Landlord liable for actual damages and potential criminal penalty under the Carbon Monoxide Alarm Detector Act.',
     'Actual damages + possible criminal penalty',
     '430 ILCS 135 / Chicago Muni Code 13-64-140', null),

    -- Chicago: RLTO move-in checklist
    (3, 'disclosure', 'Move-In Checklist (RLTO)',
     'Provide tenant with a written checklist of the condition of the unit at move-in.',
     'At or before move-in', null,
     'residential', null, null, null,
     'Failure may limit landlord ability to withhold security deposit for pre-existing damage; tenant can use lack of checklist as defense.',
     'Deposit withholding rights limited',
     'Chicago Muni Code 5-12-080', null);
