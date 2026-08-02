-- 0011_compliance_kb_grants: grant SELECT on the compliance KB tables
-- (created in 0010) to rowan_app. These are global reference data with no
-- RLS — not tenant-scoped — so rowan_app can read them without setting
-- app.current_org. rowan_system doesn't need access (scheduler has no use
-- for jurisdiction/obligation data).
grant select on compliance_jurisdictions, compliance_obligations to rowan_app;
grant select on compliance_obligation_detail to rowan_app;
