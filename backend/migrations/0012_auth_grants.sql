-- 0012_auth_grants: two further narrow rowan_system grants, for the two
-- lookups that are inherently cross-org and happen BEFORE app.current_org
-- can be set.
--
-- This is the SAME mechanism 0008_rls.sql already established for the
-- inbound webhook's reply_token -> run -> organization_id resolution
-- (system_resolve_reply_token), not a new privilege concept:
--
--   1. Principal resolution. A verified JWT carries a Supabase `sub`. To
--      learn which org that user belongs to we must read `users` -- but we
--      cannot set the GUC until we know the org. Chicken-and-egg, resolved
--      by a column-restricted SELECT on exactly the columns needed.
--
--   2. Invitation acceptance. The invitee has no org yet, so resolving
--      token_hash -> organization_id is likewise pre-GUC.
--
-- Both are SELECT-only, column-restricted, and role-restricted. rowan_app
-- gains nothing here; permissive policies OR together, so these only ever
-- ADD visibility for rowan_system.
--
-- Deliberately NOT granted: any write. Every write that follows these
-- lookups is performed by rowan_app inside org_scoped_tx(resolved_org),
-- under the normal tenant_isolation policy.

grant select (id, organization_id, auth_user_id, role, email) on users to rowan_system;
grant select (id, organization_id, role, token_hash, expires_at, accepted_at, email)
    on invitations to rowan_system;

create policy system_resolve_principal on users
    for select
    to rowan_system
    using (true);

create policy system_resolve_invitation on invitations
    for select
    to rowan_system
    using (true);
