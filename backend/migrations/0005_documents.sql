-- 0005_documents: coi_documents, coi_extractions, coi_validations.
-- run_id FKs to runs() are added in 0006 (runs is created after this file;
-- see the deferred FK block at the bottom of 0006_runs.sql) to keep this
-- migration's tables creatable in the documented dependency order without a
-- forward reference.

create table coi_documents (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    vendor_id uuid not null references vendors(id),
    run_id uuid,
    storage_path text not null,
    original_filename text not null,
    content_type text not null,
    byte_size bigint not null,
    sha256 text not null,
    source doc_source not null,
    version_number integer not null,
    supersedes_document_id uuid references coi_documents(id),
    status doc_status not null default 'received',
    valid_from date,
    valid_to date,
    is_current boolean not null default false,
    received_at timestamptz not null default now(),
    uploaded_by uuid references users(id),
    created_at timestamptz not null default now(),
    unique (vendor_id, version_number)
);

-- Partial unique: at most one current COI per vendor.
create unique index ux_coi_documents_vendor_current on coi_documents(vendor_id) where is_current;

create table coi_extractions (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid,
    coi_document_id uuid not null references coi_documents(id),
    extracted jsonb not null,
    field_confidence jsonb not null default '{}'::jsonb,
    overall_confidence numeric not null,
    model text not null,
    prompt_hash text not null,
    input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    cost_cents integer not null default 0,
    is_current boolean not null default true,
    created_at timestamptz not null default now()
);

create table coi_validations (
    id uuid primary key default uuid_generate_v7(),
    organization_id uuid not null references organizations(id),
    run_id uuid,
    coi_extraction_id uuid not null references coi_extractions(id),
    result validation_result not null,
    line_results jsonb not null default '[]'::jsonb,
    flags jsonb not null default '[]'::jsonb,
    faithfulness_ok boolean not null,
    created_at timestamptz not null default now()
);

create index ix_coi_documents_organization_id on coi_documents(organization_id);
create index ix_coi_documents_vendor_id on coi_documents(vendor_id);
create index ix_coi_documents_run_id on coi_documents(run_id);
create index ix_coi_documents_supersedes_document_id on coi_documents(supersedes_document_id);

create index ix_coi_extractions_organization_id on coi_extractions(organization_id);
create index ix_coi_extractions_run_id on coi_extractions(run_id);
create index ix_coi_extractions_coi_document_id on coi_extractions(coi_document_id);

create index ix_coi_validations_organization_id on coi_validations(organization_id);
create index ix_coi_validations_run_id on coi_validations(run_id);
create index ix_coi_validations_coi_extraction_id on coi_validations(coi_extraction_id);
