"""Config loading. All values are env-overridable; defaults match the ADR's
`# ASSUMPTION` placeholder defaults (pending real Dana calibration) and are
themselves overridable per-org via `organizations.settings` at the
orchestration layer (see app/orchestration/constants.py).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    # Request-path DSN: connects as the least-privilege `rowan_app` role.
    # Never the admin/service-role DSN (that's ADMIN_DATABASE_URL, used only
    # by scripts/migrate.py per ADR 0001).
    database_url: str = "postgresql://rowan_app:rowan_app_dev_password@localhost:55432/rowan"
    # System-path DSN for the scheduler's org-enumeration query, connects as
    # the narrow `rowan_system` role (ADR 0001 RLS shape).
    system_database_url: str = (
        "postgresql://rowan_system:rowan_system_dev_password@localhost:55432/rowan"
    )

    # --- Kill switches (CLAUDE.md guardrails, ADR 0002 global rules) ---
    # Global env-flag kill switch: halts ALL outbound tool actions while
    # leaving reads intact. Highest-priority guardrail, checked before every
    # side-effecting tool call.
    rowan_kill_switch: bool = False

    # --- Resend (send-only credential, least privilege) ---
    resend_api_key: str = ""
    resend_from_email: str = "rowan@example.com"
    resend_webhook_secret: str = ""

    # --- Claude API (agent-engineer's ExtractionEngine / explanation drafting) ---
    # Empty by default -> ClaudeExtractionEngine refuses to construct (fails
    # closed with a clear error) rather than silently making unauthenticated
    # calls. Never a real key in a committed file (CLAUDE.md secrets policy).
    anthropic_api_key: str = ""
    # # ASSUMPTION: model choice per pass is a cost/accuracy tradeoff pending
    # real Dana calibration, not an ADR-specified value. Classify is a cheap
    # binary-ish judgment (is this a COI at all?) -> Haiku. Extract is the
    # accuracy-critical structured pull the deterministic validator trusts
    # -> Sonnet. Explanation drafting is descriptive-only prose (never gates
    # routing, ADR 0004) -> Haiku. All overridable per org in a later
    # iteration; hardcoded here for v1 per CLAUDE.md's "$2/run" budget cap
    # making cost-awareness a first-class constraint, not an afterthought.
    claude_classify_model: str = "claude-haiku-4-5"
    claude_extract_model: str = "claude-sonnet-5"
    claude_explain_model: str = "claude-haiku-4-5"
    claude_timeout_seconds: float = 60.0

    # --- Supabase Auth (Epic 1) ---
    # Base project URL, e.g. https://abcdefgh.supabase.co. Empty by default
    # -> verify_supabase_jwt refuses to run (fails closed) rather than
    # accepting unverifiable tokens.
    supabase_url: str = ""
    # Overridable so tests can point at an in-process fake JWKS; in
    # production it is derived from supabase_url.
    supabase_jwks_url: str = ""
    supabase_jwt_audience: str = "authenticated"
    # # ASSUMPTION: asymmetric (RS256/ES256) signing keys, NOT the legacy
    # shared HS256 secret. A symmetric secret sits in backend env and can
    # forge a token for ANY user in ANY org if it leaks; an asymmetric
    # public key cannot. Confirm the provisioned project's signing mode
    # before go-live.
    supabase_jwks_cache_seconds: int = 300

    @property
    def resolved_jwks_url(self) -> str:
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def resolved_jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    # --- Internal routes (scheduler trigger) ---
    # # ASSUMPTION: static bearer token placeholder auth for /internal/*
    # routes pending real cron-caller integration (e.g. Vercel Cron secret
    # header). Empty by default -> route refuses to serve (503), never
    # silently open.
    internal_token: str = ""

    # --- Budgets / state-machine constants (ADR 0002 config constants) ---
    # These are the system-wide defaults; org-level overrides live in
    # organizations.settings and are applied on top of these in
    # app/orchestration/constants.py.
    renewal_lead_days: int = 30
    followup_interval_days: int = 4
    max_outreach: int = 3
    max_llm_per_doc: int = 5
    confidence_threshold: float = 0.80
    budget_cost_cap_cents: int = 200
    response_deadline_days: int = 14
    max_file_bytes: int = 10 * 1024 * 1024

    # --- App ---
    env: str = "development"


settings = Settings()
