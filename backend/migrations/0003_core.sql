-- 0003_core: organizations, users, properties, vendors, vendor_properties.

create table organizations (
    id uuid primary key default uuid_generate_v7(),
    name text not null,
    agent_enabled boolean not null default true,
    settings jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- Users belong to exactly one organization. Two roles: `owner` (full access)
-- and `assistant` (reads everything, operates the renewal loop, but cannot
-- change requirements, approve/reject a COI, or manage the team).
--
-- This comment previously read "# ASSUMPTION: single user per org in v1
-- (multi-user orgs are a non-goal per CLAUDE.md)". Epic 1 (Accounts &
-- Running Live) deliberately reversed that non-goal — see
-- docs/adr/0007-authentication-and-authorization.md. `auth_user_id` maps to
-- the Supabase `auth.users` id and is UNIQUE, which is also what makes
-- double-signup a 409 rather than requiring an RLS-defeating prior SELECT.
--
-- NOTE: the `role` column's enum was renamed pm -> assistant in migration
-- 0010. This file is applied history and is not rewritten; only this comment
-- changed.
create table users (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    auth_user_id uuid not null unique,
    email text not null,
    full_name text,
    role user_role not null default 'owner',
    created_at timestamptz not null default now()
);

create table properties (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    name text not null,
    line1 text not null,
    city text not null,
    state text not null,
    county text,
    postal_code text not null,
    country text not null default 'US',
    hoa_name text,
    property_type property_type not null,
    attributes jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table vendors (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    name text not null,
    primary_email text,
    vendor_role vendor_role not null,
    status vendor_status not null default 'active',
    primary_property_id uuid references properties(id),
    notes text,
    created_at timestamptz not null default now()
);

create table vendor_properties (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    vendor_id uuid not null references vendors(id),
    property_id uuid not null references properties(id),
    created_at timestamptz not null default now(),
    unique (vendor_id, property_id)
);

-- FK indexes (Postgres does not auto-index FKs).
create index ix_users_organization_id on users(organization_id);
create index ix_properties_organization_id on properties(organization_id);
create index ix_vendors_organization_id on vendors(organization_id);
create index ix_vendors_primary_property_id on vendors(primary_property_id);
create index ix_vendor_properties_organization_id on vendor_properties(organization_id);
create index ix_vendor_properties_vendor_id on vendor_properties(vendor_id);
create index ix_vendor_properties_property_id on vendor_properties(property_id);
