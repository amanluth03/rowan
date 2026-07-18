-- 0007_observability: agent_events (append-only trace), escalations
-- (human-review queue + PM escalations), daily_rollups.

-- # ASSUMPTION: agent_events is append-only and never UPDATEd; corrections
-- are new rows. Keeps the trace immutable for audit/trust (ADR 0001).
create table agent_events (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid references runs(id),
    vendor_id uuid references vendors(id),
    event_type event_type not null,
    name text not null,
    severity event_severity not null default 'info',
    from_state run_state,
    to_state run_state,
    tool_name text,
    idempotency_key text,
    llm_model text,
    prompt_hash text,
    input_tokens integer,
    output_tokens integer,
    cost_cents integer,
    latency_ms integer,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table escalations (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid not null references runs(id),
    vendor_id uuid not null references vendors(id),
    kind escalation_kind not null,
    reason_code text not null,
    severity event_severity not null,
    summary text not null,
    details jsonb not null default '{}'::jsonb,
    status escalation_status not null default 'open',
    assigned_user_id uuid references users(id),
    resolution text,
    resolved_by uuid references users(id),
    created_at timestamptz not null default now(),
    resolved_at timestamptz
);

-- # ASSUMPTION: rollup is a materialized nightly job, not live aggregation,
-- to keep the daily digest cheap. Live counts come from agent_events when
-- needed (ADR 0001).
create table daily_rollups (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    date date not null,
    runs_started integer not null default 0,
    runs_completed integer not null default 0,
    runs_escalated integer not null default 0,
    guardrail_trips integer not null default 0,
    llm_cost_cents integer not null default 0,
    created_at timestamptz not null default now(),
    unique (organization_id, date)
);

create index ix_agent_events_organization_id on agent_events(organization_id);
-- Trace timeline render.
create index ix_agent_events_run_id_created_at on agent_events(run_id, created_at);
-- Activity feed.
create index ix_agent_events_org_created_at on agent_events(organization_id, created_at desc);
create index ix_agent_events_vendor_id on agent_events(vendor_id);
-- Safety dashboards.
create index ix_agent_events_guardrail_trips on agent_events(event_type, created_at)
    where event_type = 'guardrail_trip';

create index ix_escalations_organization_id on escalations(organization_id);
create index ix_escalations_run_id on escalations(run_id);
create index ix_escalations_vendor_id on escalations(vendor_id);
create index ix_escalations_assigned_user_id on escalations(assigned_user_id);
-- Review queue.
create index ix_escalations_queue on escalations(organization_id, status, kind);

create index ix_daily_rollups_organization_id on daily_rollups(organization_id);
