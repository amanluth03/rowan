-- 0002_enums: all native Postgres enum types per ADR 0001.

create type coverage_type as enum (
    'general_liability', 'auto_liability', 'workers_comp',
    'umbrella_excess', 'professional_liability', 'pollution',
    'employers_liability'
);

create type vendor_role as enum (
    'plumber', 'electrician', 'hvac', 'general_contractor',
    'landscaper', 'roofer', 'cleaner', 'pest_control', 'other'
);

create type property_type as enum (
    'single_family', 'multi_family', 'condo', 'commercial', 'mixed_use'
);

create type run_state as enum (
    'monitoring', 'renewal_due_soon', 'first_outreach_sent',
    'awaiting_vendor_response', 'document_received', 'parsing',
    'validating', 'filed', 'needs_human_review', 'escalated_to_pm',
    'errored'
);

create type run_status as enum (
    'active', 'paused', 'completed', 'errored'
);

create type event_type as enum (
    'state_transition', 'tool_call', 'llm_call', 'guardrail_trip',
    'human_intervention', 'error', 'note'
);

create type event_severity as enum ('info', 'warn', 'error');

create type doc_status as enum (
    'received', 'parsing', 'parsed', 'filed', 'rejected', 'superseded'
);

create type doc_source as enum (
    'email_inbound', 'manual_upload', 'onboarding_import'
);

create type email_direction as enum ('outbound', 'inbound');

create type escalation_kind as enum ('needs_human_review', 'escalated_to_pm');

create type escalation_status as enum ('open', 'acknowledged', 'resolved');

create type validation_result as enum ('pass', 'fail');

-- # ASSUMPTION: ADR 0001's enum block did not explicitly list these three
-- (they appear inline as parenthetical value sets on tool_invocations.status,
-- users.role, vendors.status). Per the ADR's own convention ("native Postgres
-- enum types for closed sets"), they are implemented as enums here rather
-- than free text, for consistency with every other closed-set column.
create type tool_invocation_status as enum ('pending', 'succeeded', 'failed');

create type user_role as enum ('owner', 'pm');

create type vendor_status as enum ('active', 'inactive');
