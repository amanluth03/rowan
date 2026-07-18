"""State machine config constants (ADR 0002). System defaults come from
app.config.settings; each is overridable per-org via `organizations.settings`
(a jsonb blob) — this module resolves the effective value for a given org.

# ASSUMPTION (inherited from ADR 0002): CONFIDENCE_THRESHOLD 0.80,
BUDGET_COST_CAP_CENTS $2, FOLLOWUP_INTERVAL_DAYS 4, RESPONSE_DEADLINE_DAYS 14
are placeholder defaults pending real Dana calibration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class RunConstants:
    renewal_lead_days: int
    followup_interval_days: int
    max_outreach: int
    max_llm_per_doc: int
    confidence_threshold: float
    budget_cost_cap_cents: int
    response_deadline_days: int


def resolve_constants(org_settings: dict[str, Any] | None) -> RunConstants:
    org_settings = org_settings or {}
    return RunConstants(
        renewal_lead_days=int(org_settings.get("renewal_lead_days", settings.renewal_lead_days)),
        followup_interval_days=int(
            org_settings.get("followup_interval_days", settings.followup_interval_days)
        ),
        max_outreach=int(org_settings.get("max_outreach", settings.max_outreach)),
        max_llm_per_doc=int(org_settings.get("max_llm_per_doc", settings.max_llm_per_doc)),
        confidence_threshold=float(
            org_settings.get("confidence_threshold", settings.confidence_threshold)
        ),
        budget_cost_cap_cents=int(
            org_settings.get("budget_cost_cap_cents", settings.budget_cost_cap_cents)
        ),
        response_deadline_days=int(
            org_settings.get("response_deadline_days", settings.response_deadline_days)
        ),
    )
