-- 0013_rls_predicate_nullif: fix tenant_isolation's GUC-unset predicate to
-- treat '' the same as NULL.
--
-- Postgres behavior (verified against the live DB, not assumed): custom
-- ("placeholder") GUCs like app.current_org have no registered default.
-- current_setting(name, true) returns NULL only if the session has NEVER
-- touched that name. The moment any code runs
-- `SELECT set_config('app.current_org', <org>, true)` inside a transaction
-- -- exactly what org_scoped_tx() does on every request -- the value
-- reverts to '' (empty string), not NULL, once that transaction ends. This
-- is permanent for the life of that physical connection: even an explicit
-- `RESET app.current_org` brings it back to '', never to NULL again. On a
-- pooled connection this means any later query issued without going
-- through org_scoped_tx (i.e. without re-setting the GUC) sees '', not
-- NULL, once that connection has been used for any org at all.
--
-- The tenant_isolation predicate as written in 0008_rls.sql,
-- `organization_id = current_setting('app.current_org', true)::uuid`,
-- casts '' to uuid, which RAISES (invalid input syntax for type uuid)
-- instead of comparing against NULL (which evaluates to unknown/false and
-- silently matches zero rows). That contradicts app/db.py's own module
-- docstring, which claims the failure mode is always "sees zero rows", and
-- surfaces as a real, reproducible defect on any pooled connection that
-- has already run org_scoped_tx once. It is fail-closed (an exception,
-- never another org's rows -- force row level security still holds), but
-- it is not the documented, provable "zero rows" semantics Epic 1's
-- tenant-isolation acceptance criterion requires.
--
-- Fix: wrap current_setting(...) in nullif(..., '') so '' collapses to
-- NULL before the cast, exactly like the "never set" case. This restores
-- the fail-to-zero-rows semantics app/db.py's docstring already claims, on
-- every physical connection regardless of prior org_scoped_tx use.
--
-- Scope: every tenant_isolation policy, on every tenant table (17: the 16
-- from 0008_rls.sql's original loop, plus invitations from 0011). Both
-- using (...) and with check (...) get the same fix. system_resolve_*
-- policies (0008_rls.sql, 0012_auth_grants.sql) are untouched -- they use
-- `using (true)` and have no cast to fix. 0008_rls.sql itself is applied
-- history and is not edited; this migration only drops and recreates the
-- affected policies.

do $$
declare
    t text;
begin
    foreach t in array array[
        'users', 'properties', 'vendors', 'vendor_properties',
        'compliance_requirements', 'vendor_coverage_requirements',
        'coi_documents', 'coi_extractions', 'coi_validations',
        'runs', 'tool_invocations', 'email_messages',
        'agent_events', 'escalations', 'daily_rollups', 'invitations'
    ]
    loop
        execute format('drop policy tenant_isolation on %I', t);
        execute format(
            'create policy tenant_isolation on %I ' ||
            'using (organization_id = nullif(current_setting(''app.current_org'', true), '''')::uuid) ' ||
            'with check (organization_id = nullif(current_setting(''app.current_org'', true), '''')::uuid)',
            t
        );
    end loop;
end
$$;

-- organizations: keyed on its own id, handled separately (no organization_id column).
drop policy tenant_isolation on organizations;
create policy tenant_isolation on organizations
    using (id = nullif(current_setting('app.current_org', true), '')::uuid)
    with check (id = nullif(current_setting('app.current_org', true), '')::uuid);
