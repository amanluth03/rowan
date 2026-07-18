-- 0009_seed: one demo org, demo properties/vendors, starter
-- compliance_requirements for the demo jurisdiction (feeds evals/demo).
--
-- Runs with an elevated (superuser / Supabase service-role-equivalent)
-- connection per ADR 0001 ("Supabase service_role key is never used from
-- request-path code — only in migrations/seed"), so it is not subject to
-- RLS and needs no app.current_org GUC set.
--
-- # ASSUMPTION: demo jurisdiction is Massachusetts / City of Boston, a
-- high-regulation state consistent with the "Dana" persona in CLAUDE.md.
-- Fixture values (limits, citations) are illustrative for the demo/eval
-- harness, not verified legal advice.

insert into organizations (id, name, agent_enabled, settings)
values ('00000000-0000-7000-8000-000000000001', 'Rowan Demo Property Management', true, '{}'::jsonb);

insert into properties (id, organization_id, name, line1, city, state, county, postal_code, property_type)
values (
    '00000000-0000-7000-8000-000000000010',
    '00000000-0000-7000-8000-000000000001',
    'Beacon Hill Triplex',
    '12 Beacon St',
    'Boston',
    'MA',
    'Suffolk',
    '02108',
    'multi_family'
);

insert into vendors (id, organization_id, name, primary_email, vendor_role, status, primary_property_id, notes)
values (
    '00000000-0000-7000-8000-000000000020',
    '00000000-0000-7000-8000-000000000001',
    'Hernandez Plumbing',
    'billing@hernandezplumbing.example.com',
    'plumber',
    'active',
    '00000000-0000-7000-8000-000000000010',
    'Demo vendor for eval harness / walkthrough.'
);

insert into compliance_requirements (
    id, organization_id, jurisdiction_state, jurisdiction_city, property_type, vendor_role,
    coverage_type, min_each_occurrence, min_aggregate,
    requires_additional_insured, requires_waiver_of_subrogation, requires_primary_noncontributory,
    source_citation, source_url, last_verified_at, verified_by, active
) values
(
    '00000000-0000-7000-8000-000000000030',
    '00000000-0000-7000-8000-000000000001',
    'MA', 'Boston', null, 'plumber',
    'general_liability', 1000000, 2000000,
    true, true, true,
    'Rowan compliance desk: standard MA residential PM vendor GL minimum for licensed trades.',
    null, now(), 'seed', true
),
(
    '00000000-0000-7000-8000-000000000031',
    '00000000-0000-7000-8000-000000000001',
    'MA', 'Boston', null, 'plumber',
    'workers_comp', null, null,
    false, false, false,
    'Massachusetts General Laws c. 152 — mandatory workers'' compensation for employers with employees.',
    null, now(), 'seed', true
);

insert into vendor_coverage_requirements (
    organization_id, vendor_id, coverage_type, min_each_occurrence, min_aggregate,
    requires_additional_insured, requires_waiver_of_subrogation, requires_primary_noncontributory,
    source_compliance_requirement_id, confirmed_by_pm
) values
(
    '00000000-0000-7000-8000-000000000001',
    '00000000-0000-7000-8000-000000000020',
    'general_liability', 1000000, 2000000,
    true, true, true,
    '00000000-0000-7000-8000-000000000030', true
),
(
    '00000000-0000-7000-8000-000000000001',
    '00000000-0000-7000-8000-000000000020',
    'workers_comp', null, null,
    false, false, false,
    '00000000-0000-7000-8000-000000000031', true
);
