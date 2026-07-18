-- 0008_rls: roles, RLS enable/force, tenant_isolation policies, grants.
--
-- Per ADR 0001 "RLS shape":
--   - rowan_app: the FastAPI backend's normal request-path role. No
--     BYPASSRLS. Every request sets `SET LOCAL app.current_org = '<uuid>'`
--     before issuing any query; the tenant_isolation policy scopes every
--     read/write to that org.
--   - rowan_system: narrow role for (a) the scheduler's org-enumeration
--     query (reads organizations.id where agent_enabled) and (b) the
--     inbound-email webhook's reply_token -> run -> organization_id
--     resolution (see below). Nothing else is granted to it.
--
-- # ASSUMPTION: role passwords are supplied via migration-time environment
-- variables (see scripts/migrate.py) rather than hardcoded here, so this
-- file never contains a secret. Local/dev defaults live only in
-- backend/.env.example, never committed with a real value.
--
-- RESOLVED (ADR 0001's 2026-07-18 amendment, companion to ADR 0002 item 4):
-- rowan_system's extended grant below (a SECOND narrow, single-purpose
-- SELECT on exactly the columns needed to resolve a reply_token — id,
-- organization_id, reply_token, reply_token_expires_at, status — nothing
-- else on `runs`) was confirmed as the correct, smallest mechanism for the
-- webhook's reply_token -> run -> organization_id resolution, which is
-- inherently a cross-org lookup and impossible via rowan_app before the GUC
-- is set. No further change needed; ADR 0001 has been updated to describe
-- this second grant explicitly rather than only the org-enumeration one.

do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'rowan_app') then
        execute format('create role rowan_app login password %L', current_setting('rowan.migrate_app_password', true));
    end if;
    if not exists (select 1 from pg_roles where rolname = 'rowan_system') then
        execute format('create role rowan_system login password %L', current_setting('rowan.migrate_system_password', true));
    end if;
end
$$;

grant usage on schema public to rowan_app, rowan_system;

-- rowan_app: full CRUD on every tenant table. RLS (below) still scopes rows.
grant select, insert, update, delete on
    organizations, users, properties, vendors, vendor_properties,
    compliance_requirements, vendor_coverage_requirements,
    coi_documents, coi_extractions, coi_validations,
    runs, tool_invocations, email_messages,
    agent_events, escalations, daily_rollups
to rowan_app;

-- rowan_system: SELECT on organizations (org-enumeration for the scheduler)
-- plus a column-restricted SELECT on runs (webhook reply_token resolution
-- only — see the gap note above). No other table is granted to this role.
grant select on organizations to rowan_system;
grant select (id, organization_id, reply_token, reply_token_expires_at, status) on runs to rowan_system;

-- Enable + force RLS on every tenant table (organizations included, keyed
-- on its own id per ADR 0001).
do $$
declare
    t text;
begin
    foreach t in array array[
        'organizations', 'users', 'properties', 'vendors', 'vendor_properties',
        'compliance_requirements', 'vendor_coverage_requirements',
        'coi_documents', 'coi_extractions', 'coi_validations',
        'runs', 'tool_invocations', 'email_messages',
        'agent_events', 'escalations', 'daily_rollups'
    ]
    loop
        execute format('alter table %I enable row level security', t);
        execute format('alter table %I force row level security', t);
    end loop;
end
$$;

-- organizations: keyed on its own id (there is no organization_id column).
create policy tenant_isolation on organizations
    using (id = current_setting('app.current_org', true)::uuid)
    with check (id = current_setting('app.current_org', true)::uuid);

-- Narrow, role-scoped policy letting rowan_system enumerate orgs without
-- the app.current_org GUC set (this is the one legitimate cross-org read
-- path, explicitly limited to this table and this role by both RLS and the
-- table-level GRANT above). Permissive policies OR together, so this only
-- ever *adds* visibility for rowan_system; it grants nothing to rowan_app.
create policy system_enumerate_orgs on organizations
    for select
    to rowan_system
    using (true);

-- Mirror policy on runs for the webhook's reply_token resolution (see gap
-- note above). Column-level access is already restricted by the GRANT;
-- this only lifts the ROW filter for rowan_system, and only for SELECT.
create policy system_resolve_reply_token on runs
    for select
    to rowan_system
    using (true);

-- All other tenant tables: standard organization_id = GUC policy.
do $$
declare
    t text;
begin
    foreach t in array array[
        'users', 'properties', 'vendors', 'vendor_properties',
        'compliance_requirements', 'vendor_coverage_requirements',
        'coi_documents', 'coi_extractions', 'coi_validations',
        'runs', 'tool_invocations', 'email_messages',
        'agent_events', 'escalations', 'daily_rollups'
    ]
    loop
        execute format(
            'create policy tenant_isolation on %I ' ||
            'using (organization_id = current_setting(''app.current_org'', true)::uuid) ' ||
            'with check (organization_id = current_setting(''app.current_org'', true)::uuid)',
            t
        );
    end loop;
end
$$;
