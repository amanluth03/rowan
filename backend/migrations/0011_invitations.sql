-- 0011_invitations: pending invitations for the owner -> assistant flow.
--
-- The raw token is NEVER stored. We keep sha256(token) only; the plaintext
-- exists exactly once, in the invite email. A database leak therefore
-- yields no usable invite links.
--
-- # ASSUMPTION: 7-day expiry and one-invite-per-pending-email are v1
-- placeholders pending real Dana input.
--
-- NOTE (deliberate, out of scope here): runs.reply_token is stored in
-- plaintext while this table stores a hash. The inconsistency is recorded
-- in docs/adr/0007 rather than fixed in this epic.

create table invitations (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    email text not null,
    role user_role not null default 'assistant',
    token_hash text not null unique,
    invited_by_user_id uuid references users(id),
    expires_at timestamptz not null,
    accepted_at timestamptz,
    created_at timestamptz not null default now()
);

create index ix_invitations_organization_id on invitations(organization_id);
create index ix_invitations_invited_by_user_id on invitations(invited_by_user_id);

-- At most one OUTSTANDING invite per email per org. Accepted rows are
-- retained as an audit trail, so the constraint is partial.
create unique index ux_invitations_pending_email
    on invitations(organization_id, lower(email))
    where accepted_at is null;

alter table invitations enable row level security;
alter table invitations force row level security;

grant select, insert, update, delete on invitations to rowan_app;

create policy tenant_isolation on invitations
    using (organization_id = current_setting('app.current_org', true)::uuid)
    with check (organization_id = current_setting('app.current_org', true)::uuid);
