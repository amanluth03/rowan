-- 0006_runs: runs (state-machine instance, tier-a), tool_invocations
-- (idempotency ledger), email_messages. Also adds the deferred FKs from
-- 0005's document tables to runs(id), now that runs exists.

create table runs (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    vendor_id uuid not null references vendors(id),
    coi_document_id uuid references coi_documents(id),
    state run_state not null default 'monitoring',
    status run_status not null default 'active',
    trigger text not null,
    due_date date,
    next_action_at timestamptz,
    outreach_email_count integer not null default 0,
    llm_call_count integer not null default 0,
    cost_cents_spent integer not null default 0,
    budget_cost_cap_cents integer not null default 200,
    reply_token text unique,
    reply_token_expires_at timestamptz,
    paused_by uuid references users(id),
    started_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz
);

-- At most one live (active) run per vendor.
create unique index ux_runs_vendor_active on runs(vendor_id) where status = 'active';

-- Now that runs exists, wire the deferred FKs from 0005.
alter table coi_documents add constraint fk_coi_documents_run_id
    foreign key (run_id) references runs(id);
alter table coi_extractions add constraint fk_coi_extractions_run_id
    foreign key (run_id) references runs(id);
alter table coi_validations add constraint fk_coi_validations_run_id
    foreign key (run_id) references runs(id);

-- tool_invocations: idempotency ledger backing every side-effecting tool
-- (ADR 0004). Shared INSERT ... ON CONFLICT DO NOTHING mechanism.
create table tool_invocations (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid references runs(id),
    tool_name text not null,
    idempotency_key text not null,
    request_hash text not null,
    status tool_invocation_status not null default 'pending',
    response jsonb,
    error jsonb,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    unique (tool_name, idempotency_key)
);

create table email_messages (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid references runs(id),
    vendor_id uuid references vendors(id),
    direction email_direction not null,
    provider_message_id text,
    reply_token text,
    subject text not null,
    body_snapshot text not null,
    to_email text not null,
    from_email text not null,
    status text not null default 'queued',
    attachments_count integer not null default 0,
    created_at timestamptz not null default now()
);

create index ix_runs_organization_id on runs(organization_id);
create index ix_runs_vendor_id on runs(vendor_id);
create index ix_runs_coi_document_id on runs(coi_document_id);
create index ix_runs_paused_by on runs(paused_by);
-- Scheduler & feed.
create index ix_runs_org_state_active on runs(organization_id, state) where status = 'active';
-- Scheduler wakeups.
create index ix_runs_next_action_at on runs(next_action_at) where status = 'active';
-- Webhook lookup (reply_token is already unique; index supports fast lookup).
create index ix_runs_reply_token on runs(reply_token);

create index ix_tool_invocations_organization_id on tool_invocations(organization_id);
create index ix_tool_invocations_run_id on tool_invocations(run_id);
-- Dedupe lookup (tool_name, idempotency_key) already covered by the unique
-- constraint's backing index; no separate index needed.

create index ix_email_messages_organization_id on email_messages(organization_id);
create index ix_email_messages_run_id on email_messages(run_id);
create index ix_email_messages_vendor_id on email_messages(vendor_id);
