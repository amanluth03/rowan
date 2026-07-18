/**
 * Semantic color mapping for statuses/severities across the app. Kept
 * deliberately desaturated and small in vocabulary (green / amber / rose /
 * slate) so escalations read as a colleague flagging something -- not an
 * alarm system -- per CLAUDE.md's brand section.
 */

import type { ComplianceStatus, EventSeverity, RunState } from "./types";

export interface StatusStyle {
  label: string;
  badgeClass: string;
  dotClass: string;
}

export const complianceStatusStyles: Record<ComplianceStatus, StatusStyle> = {
  compliant: {
    label: "Compliant",
    badgeClass: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-900",
    dotClass: "bg-emerald-500",
  },
  expiring_soon: {
    label: "Expiring soon",
    badgeClass: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900",
    dotClass: "bg-amber-500",
  },
  pending: {
    label: "In progress",
    badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900",
    dotClass: "bg-sky-500",
  },
  needs_review: {
    label: "Needs your review",
    badgeClass: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900",
    dotClass: "bg-amber-500",
  },
  escalated: {
    label: "Escalated",
    badgeClass: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900",
    dotClass: "bg-rose-500",
  },
  no_requirements: {
    label: "Needs requirements",
    badgeClass: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900",
    dotClass: "bg-rose-500",
  },
};

export const severityStyles: Record<EventSeverity, StatusStyle> = {
  info: {
    label: "Info",
    badgeClass: "bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-900/60 dark:text-slate-300 dark:border-slate-800",
    dotClass: "bg-slate-400",
  },
  warn: {
    label: "Attention",
    badgeClass: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900",
    dotClass: "bg-amber-500",
  },
  error: {
    label: "Escalated",
    badgeClass: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900",
    dotClass: "bg-rose-500",
  },
};

export const runStateStyles: Record<RunState, StatusStyle> = {
  monitoring: { label: "Monitoring", badgeClass: "bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-900/60 dark:text-slate-300 dark:border-slate-800", dotClass: "bg-slate-400" },
  renewal_due_soon: { label: "Renewal due soon", badgeClass: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900", dotClass: "bg-amber-500" },
  first_outreach_sent: { label: "Outreach sent", badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900", dotClass: "bg-sky-500" },
  awaiting_vendor_response: { label: "Awaiting vendor", badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900", dotClass: "bg-sky-500" },
  document_received: { label: "Document received", badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900", dotClass: "bg-sky-500" },
  parsing: { label: "Reading document", badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900", dotClass: "bg-sky-500" },
  validating: { label: "Validating coverage", badgeClass: "bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-400 dark:border-sky-900", dotClass: "bg-sky-500" },
  filed: { label: "Filed", badgeClass: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-900", dotClass: "bg-emerald-500" },
  needs_human_review: { label: "Needs your review", badgeClass: "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900", dotClass: "bg-amber-500" },
  escalated_to_pm: { label: "Escalated to you", badgeClass: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900", dotClass: "bg-rose-500" },
  errored: { label: "Error", badgeClass: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-900", dotClass: "bg-rose-500" },
};
