/** Small formatting helpers shared across screens. Pure, no framework deps. */

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

// Coverage limits are whole dollars (ADR 0001 convention) -- no decimals.
export function formatDollars(amount: number | null): string {
  if (amount === null) return "—";
  return dollars.format(amount);
}

const centsAsDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

// LLM/run spend is tracked in integer cents (ADR 0001) and is often well
// under $1 -- always show cents so "$0.04" doesn't round away to "$0".
export function formatCents(cents: number | null): string {
  if (cents === null) return "—";
  return centsAsDollars.format(cents / 100);
}

const dateFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return dateFmt.format(new Date(iso));
}

export function formatShortDate(iso: string | null): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" }).format(new Date(iso));
}

const timeFmt = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return timeFmt.format(new Date(iso));
}

/** "now" for relative-time math -- fixed to the CLAUDE.md session date so the
 * demo data (dated around 2026-07-18) reads as current, not stale. */
export const MOCK_NOW = new Date("2026-07-18T16:00:00Z");

export function relativeTime(iso: string, now: Date = MOCK_NOW): string {
  const diffMs = new Date(iso).getTime() - now.getTime();
  const diffMinutes = Math.round(diffMs / 60_000);
  const abs = Math.abs(diffMinutes);

  if (abs < 60) {
    return diffMinutes <= 0 ? `${abs || 1}m ago` : `in ${abs}m`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  if (Math.abs(diffHours) < 24) {
    return diffHours <= 0 ? `${Math.abs(diffHours)}h ago` : `in ${diffHours}h`;
  }
  const diffDays = Math.round(diffHours / 24);
  if (Math.abs(diffDays) < 30) {
    return diffDays <= 0 ? `${Math.abs(diffDays)}d ago` : `in ${diffDays}d`;
  }
  const diffMonths = Math.round(diffDays / 30);
  return diffMonths <= 0 ? `${Math.abs(diffMonths)}mo ago` : `in ${diffMonths}mo`;
}

export function daysUntil(iso: string, now: Date = MOCK_NOW): number {
  const ms = new Date(iso).getTime() - now.getTime();
  return Math.ceil(ms / (24 * 60 * 60 * 1000));
}

const roleLabels: Record<string, string> = {
  plumber: "Plumber",
  electrician: "Electrician",
  hvac: "HVAC",
  general_contractor: "General Contractor",
  landscaper: "Landscaper",
  roofer: "Roofer",
  cleaner: "Cleaner",
  pest_control: "Pest Control",
  other: "Other",
};

export function formatVendorRole(role: string): string {
  return roleLabels[role] ?? role;
}

const coverageLabels: Record<string, string> = {
  general_liability: "General Liability",
  auto_liability: "Auto Liability",
  workers_comp: "Workers' Comp",
  umbrella_excess: "Umbrella / Excess",
  professional_liability: "Professional Liability",
  pollution: "Pollution Liability",
  employers_liability: "Employers Liability",
};

export function formatCoverageType(type: string): string {
  return coverageLabels[type] ?? type;
}

const stateLabels: Record<string, string> = {
  monitoring: "Monitoring",
  renewal_due_soon: "Renewal due soon",
  first_outreach_sent: "Outreach sent",
  awaiting_vendor_response: "Awaiting vendor",
  document_received: "Document received",
  parsing: "Reading document",
  validating: "Validating coverage",
  filed: "Filed",
  needs_human_review: "Needs your review",
  escalated_to_pm: "Escalated to you",
  errored: "Error",
};

export function formatRunState(state: string): string {
  return stateLabels[state] ?? state;
}
