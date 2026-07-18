/**
 * Turns a raw `AgentEventDTO` (the append-only agent_events trace, ADR 0001 §
 * observability) into a human-readable timeline entry. This is the core of
 * the run-detail trust surface -- CLAUDE.md: "every step, email, parse,
 * validation, cost; human-readable." One switch, keyed on the OTel-style
 * event `name`, each returning plain-language title + detail strings built
 * from the structured payload -- never guessing, only formatting what's there.
 */

import type { AgentEventDTO } from "./types";
import { formatDollars, formatRunState } from "./format";

export interface DescribedEvent {
  title: string;
  detail: string | null;
}

function money(n: unknown): string {
  return typeof n === "number" ? formatDollars(n) : "—";
}

function state(s: unknown): string {
  return typeof s === "string" ? formatRunState(s) : String(s);
}

export function describeEvent(e: AgentEventDTO): DescribedEvent {
  const p = e.payload ?? {};

  switch (e.name) {
    case "state.transition":
      return {
        title: `Moved from ${state(e.fromState)} to ${state(e.toState)}`,
        detail: typeof p.guard === "string" ? `Guard: ${p.guard}` : null,
      };

    case "tool.send_email": {
      const template = String(p.template_id ?? "email");
      const labels: Record<string, string> = {
        first_outreach: "Sent the first renewal request",
        follow_up: "Sent a follow-up reminder",
        revision_request: "Emailed the vendor asking for a revised certificate",
        handled_notice: "Notified you that this renewal is handled",
      };
      const to = typeof p.to === "string" ? ` to ${p.to}` : "";
      return {
        title: `${labels[template] ?? "Sent an email"}${template !== "handled_notice" && template !== "revision_request" ? to : ""}`,
        detail: [
          p.provider_message_id ? `Delivered (provider id ${p.provider_message_id}).` : null,
          typeof p.note === "string" ? p.note : null,
        ].filter(Boolean).join(" ") || null,
      };
    }

    case "tool.receive_inbound_email":
      return {
        title: "Received a reply from the vendor",
        detail: `${p.attachments ?? 0} attachment(s)${p.filename ? ` — ${p.filename}` : ""}.`,
      };

    case "tool.classify_document":
      return {
        title: "Classified the attachment as a certificate of insurance",
        detail: typeof p.confidence === "number" ? `Confidence ${(p.confidence * 100).toFixed(0)}%.` : null,
      };

    case "guardrail.pre_llm_file_check":
      return {
        title: "Checked file type and size before doing anything with it",
        detail: `Allowed types: ${Array.isArray(p.allowed_types) ? (p.allowed_types as string[]).join(", ") : "pdf/png/jpg/tiff"}. Result: ${p.result ?? "pass"}.`,
      };

    case "guardrail.pre_llm_neutralize":
      return {
        title: "Neutralized the document before showing it to the model",
        detail: "Wrapped in data delimiters with an explicit instruction to ignore anything inside it — the document is data, never instructions.",
      };

    case "tool.parse_document":
      return {
        title: "Read the certificate and extracted the coverage figures",
        detail: [
          typeof p.overall_confidence === "number" ? `Overall confidence ${(p.overall_confidence * 100).toFixed(0)}%.` : null,
          typeof p.attempt_no === "number" ? `Attempt ${p.attempt_no}.` : null,
          e.llmModel ? `Model: ${e.llmModel}.` : null,
        ].filter(Boolean).join(" ") || null,
      };

    case "tool.update_coi_record.validate":
      return {
        title: p.result === "pass" ? "Validated coverage — every required line passed" : "Validated coverage — at least one required line failed",
        detail: [
          typeof p.faithfulness_ok === "boolean" ? `Faithfulness check: ${p.faithfulness_ok ? "passed" : "FAILED"}.` : null,
          Array.isArray(p.failing_lines) && p.failing_lines.length ? `Failing: ${(p.failing_lines as string[]).join(", ")}.` : null,
          typeof p.lines_checked === "number" ? `${p.lines_checked} line(s) checked.` : null,
        ].filter(Boolean).join(" ") || null,
      };

    case "tool.draft_gap_explanation":
      return {
        title: "Drafted a plain-language explanation of the coverage gap",
        detail: "Prose only — attached to the escalation for your review; it does not change the routing decision.",
      };

    case "tool.file_document":
      return {
        title: "Filed the certificate as the current record of coverage",
        detail: [
          typeof p.valid_from === "string" && typeof p.valid_to === "string" ? `Valid ${p.valid_from} through ${p.valid_to}.` : null,
          p.superseded_document_id ? "Superseded the prior certificate." : null,
        ].filter(Boolean).join(" ") || null,
      };

    case "tool.mark_task_complete":
      return {
        title: "Marked the renewal complete",
        detail: `Basis: ${p.completion_basis === "human_approved" ? "your approval" : "passing validation"}${typeof p.next_due_date === "string" ? ` — next due ${p.next_due_date}.` : "."}`,
      };

    case "tool.escalate_to_pm":
      return {
        title: p.kind === "needs_human_review" ? "Flagged this for your review" : "Escalated this to you",
        detail: typeof p.reason_code === "string" ? `Reason: ${p.reason_code.replaceAll("_", " ")}.` : null,
      };

    case "guardrail.post_llm_confidence":
      return {
        title: "Extraction confidence came in below the review threshold",
        detail: typeof p.overall_confidence === "number" && typeof p.threshold === "number"
          ? `${(p.overall_confidence * 100).toFixed(0)}% vs. an ${(p.threshold * 100).toFixed(0)}% threshold — routed to human review rather than guessed.`
          : null,
      };

    case "guardrail.budget_exhausted":
      return {
        title: "Outreach budget reached for this renewal cycle",
        detail: typeof p.outreach_email_count === "number" && typeof p.max_outreach === "number"
          ? `${p.outreach_email_count}/${p.max_outreach} emails sent — Rowan stopped rather than over-contact the vendor.`
          : null,
      };

    case "guardrail.requirements_retrieval_fallback":
      return {
        title: "No verified requirement found for this coverage line",
        detail: "Rowan will not validate against a guessed minimum — escalated for a human decision instead of proceeding.",
      };

    case "guardrail.out_of_allowlist_action":
      return {
        title: "Blocked an action outside this state's allowlist",
        detail: typeof p.attempted_action === "string" && typeof p.current_state === "string"
          ? `Attempted "${p.attempted_action}" while in ${formatRunState(p.current_state)} — not permitted, so the run stopped rather than risk an unsafe action.`
          : null,
      };

    case "webhook.reply_token_conflict":
      return {
        title: "Inbound webhook hit a conflict",
        detail: typeof p.detail === "string" ? p.detail : null,
      };

    case "human.approve_review":
      return { title: "You approved this certificate", detail: typeof p.note === "string" ? p.note : "Overrides the failed validation with your explicit sign-off." };
    case "human.reject_review":
      return { title: "You rejected this certificate", detail: typeof p.reason === "string" ? p.reason : null };
    case "human.request_revision":
      return { title: "You requested a revised certificate", detail: typeof p.message === "string" ? p.message : null };
    case "human.resolve_escalation":
      return {
        title: p.decision === "keep_chasing" ? "You asked Rowan to keep chasing this vendor" : "You marked this escalation resolved",
        detail: typeof p.note === "string" ? p.note : null,
      };
    case "human.pause_run":
      return { title: "You paused this run", detail: typeof p.reason === "string" ? p.reason : "Rowan will take no further automated action until resumed." };
    case "human.resume_run":
      return { title: "You resumed this run", detail: "Rowan will pick this back up on its next scheduled action." };

    case "scheduler.next_tick":
      return { title: "Waiting for the next scheduled action", detail: typeof p.note === "string" ? p.note : null };

    default:
      return {
        title: e.name.replaceAll(/[._]/g, " "),
        detail: Object.keys(p).length ? JSON.stringify(p) : null,
      };
  }
}

export { money };
