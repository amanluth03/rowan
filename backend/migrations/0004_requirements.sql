-- 0004_requirements: compliance_requirements (tier-c KB) + vendor_coverage_requirements
-- (the vendor's one effective required set, locked one-set-per-vendor decision).

create table compliance_requirements (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    jurisdiction_state text not null,
    jurisdiction_city text,
    jurisdiction_hoa text,
    property_type property_type,
    vendor_role vendor_role,
    coverage_type coverage_type not null,
    min_each_occurrence integer,
    min_aggregate integer,
    requires_additional_insured boolean not null default false,
    requires_waiver_of_subrogation boolean not null default false,
    requires_primary_noncontributory boolean not null default false,
    min_policy_notes text,
    source_citation text not null,
    source_url text,
    last_verified_at timestamptz not null,
    verified_by text,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- # ASSUMPTION: a null source_compliance_requirement_id means a PM-entered
-- override with no KB backing; validation flags any such line as
-- "unverified requirement" so faithfulness isn't silently bypassed (ADR 0001).
create table vendor_coverage_requirements (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    vendor_id uuid not null references vendors(id),
    coverage_type coverage_type not null,
    min_each_occurrence integer,
    min_aggregate integer,
    requires_additional_insured boolean not null default false,
    requires_waiver_of_subrogation boolean not null default false,
    requires_primary_noncontributory boolean not null default false,
    source_compliance_requirement_id uuid references compliance_requirements(id),
    confirmed_by_pm boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (vendor_id, coverage_type)
);

create index ix_compliance_requirements_organization_id on compliance_requirements(organization_id);
-- Tier-c predicate index (ADR 0001 Indexes section).
create index ix_compliance_requirements_predicate
    on compliance_requirements(organization_id, jurisdiction_state, vendor_role, coverage_type)
    where active;

create index ix_vendor_coverage_requirements_organization_id on vendor_coverage_requirements(organization_id);
create index ix_vendor_coverage_requirements_vendor_id on vendor_coverage_requirements(vendor_id);
create index ix_vendor_coverage_requirements_source_compliance_requirement_id
    on vendor_coverage_requirements(source_compliance_requirement_id);
