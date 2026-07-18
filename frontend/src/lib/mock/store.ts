/**
 * Mock command handlers -- stand in for the Orchestration layer's command
 * handling (ADR 0003: "Interface -> Orchestration: typed commands only").
 * Each function takes exactly the typed command from `lib/commands.ts`,
 * mutates the in-memory fixture "database", appends `agent_events` rows so
 * the trace timeline reflects what happened, and returns a `CommandResult`.
 *
 * # ASSUMPTION: this is a client-side/dev-process mock, not a real state
 * machine -- it does not re-run guards, budgets, or the action allowlist
 * (ADR 0002 owns that logic; it lives in the backend). It fast-forwards
 * straight to the transition a human action would deterministically cause,
 * so the UI can be built and clicked through end-to-end before that backend
 * exists. Swapping in the real API means replacing each function body with a
 * `POST /api/commands/...` call -- the exported signatures stay the same.
 */

import type {
  AddVendorCommand,
  ApproveReviewCommand,
  CommandResult,
  PauseRunCommand,
  RejectReviewCommand,
  RequestRevisionCommand,
  ResolveEscalationCommand,
  ResumeRunCommand,
  SetRequirementsCommand,
  StartRunCommand,
} from "../commands";
import {
  agentEvents,
  coiDocuments,
  complianceRequirements,
  escalations,
  ORG_ID,
  runs,
  vendorCoverageRequirements,
  vendors,
  type AgentEventRecord,
  type EscalationRecord,
  type VendorCoverageRequirementRecord,
  type VendorRecord,
} from "./fixtures";

let idSeq = 1000;
function nextId(prefix: string): string {
  idSeq += 1;
  return `${prefix}_${idSeq}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

function pushEvent(e: Omit<AgentEventRecord, "id">) {
  agentEvents.push({ id: nextId("evt"), ...e });
}

function findRunOrThrow(runId: string) {
  const run = runs.find((r) => r.id === runId);
  if (!run) throw new Error(`Unknown run: ${runId}`);
  return run;
}

function findEscalationOrThrow(escalationId: string) {
  const esc = escalations.find((e) => e.id === escalationId);
  if (!esc) throw new Error(`Unknown escalation: ${escalationId}`);
  return esc;
}

function vendorName(vendorId: string): string {
  return vendors.find((v) => v.id === vendorId)?.name ?? vendorId;
}

// ---------------------------------------------------------------------------
// Review-queue commands (needs_human_review escalations)
// ---------------------------------------------------------------------------

export function approveReview(cmd: ApproveReviewCommand): CommandResult {
  const esc = findEscalationOrThrow(cmd.escalationId);
  const run = findRunOrThrow(esc.runId);
  const fromState = run.state;

  esc.status = "resolved";
  esc.resolution = "approved";
  esc.resolvedAt = nowIso();

  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "human_intervention", name: "human.approve_review", severity: "info",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { escalation_id: esc.id, note: cmd.note ?? null, actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "state_transition", name: "state.transition", severity: "info",
    fromState, toState: "filed", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: "PM approve overrides validation fail with explicit sign-off" }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "tool_call", name: "tool.mark_task_complete", severity: "info",
    fromState: null, toState: null, toolName: "mark_task_complete", llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { completion_basis: "human_approved", escalation_id: esc.id }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "state_transition", name: "state.transition", severity: "info",
    fromState: "filed", toState: "monitoring", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: "filed + cycle reset (human-approved basis)" }, createdAt: nowIso(),
  });

  const doc = coiDocuments.find((d) => d.id === run.coiDocumentId);
  if (doc) {
    coiDocuments.filter((d) => d.vendorId === doc.vendorId && d.isCurrent).forEach((d) => (d.isCurrent = false));
    doc.isCurrent = true;
    doc.status = "filed";
  }

  run.state = "monitoring";
  run.status = "active";
  run.updatedAt = nowIso();
  run.completedAt = nowIso();

  return { ok: true, message: `Approved. ${vendorName(esc.vendorId)} filed on your sign-off; Rowan will monitor for the next renewal.` };
}

export function rejectReview(cmd: RejectReviewCommand): CommandResult {
  const esc = findEscalationOrThrow(cmd.escalationId);
  const run = findRunOrThrow(esc.runId);
  const fromState = run.state;

  esc.status = "resolved";
  esc.resolution = "rejected";
  esc.resolvedAt = nowIso();

  const newEsc: EscalationRecord = {
    id: nextId("esc"),
    organizationId: ORG_ID,
    runId: run.id,
    vendorId: esc.vendorId,
    kind: "escalated_to_pm",
    reasonCode: "rejected_by_pm",
    severity: "warn",
    summary: `You rejected this certificate: ${cmd.reason}`,
    details: { originalEscalationId: esc.id },
    status: "open",
    resolution: null,
    createdAt: nowIso(),
    resolvedAt: null,
  };
  escalations.push(newEsc);

  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "human_intervention", name: "human.reject_review", severity: "warn",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { escalation_id: esc.id, reason: cmd.reason, actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "state_transition", name: "state.transition", severity: "warn",
    fromState, toState: "escalated_to_pm", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: "PM reject without revision path", reason: "rejected_by_pm" }, createdAt: nowIso(),
  });

  run.state = "escalated_to_pm";
  run.updatedAt = nowIso();

  return { ok: true, message: "Rejected. This vendor is now parked in Escalated until you decide next steps." };
}

export function requestRevision(cmd: RequestRevisionCommand): CommandResult {
  const esc = findEscalationOrThrow(cmd.escalationId);
  const run = findRunOrThrow(esc.runId);
  const fromState = run.state;

  esc.status = "resolved";
  esc.resolution = "revision_requested";
  esc.resolvedAt = nowIso();

  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "human_intervention", name: "human.request_revision", severity: "info",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { escalation_id: esc.id, message: cmd.message, actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "tool_call", name: "tool.send_email", severity: "info",
    fromState: null, toState: null, toolName: "send_email", llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: 0, latencyMs: 640,
    payload: { template_id: "revision_request", message_preview: cmd.message.slice(0, 140) }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "state_transition", name: "state.transition", severity: "info",
    fromState, toState: "awaiting_vendor_response", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: "PM request_revision -- revision-request sent within outreach budget" }, createdAt: nowIso(),
  });

  run.state = "awaiting_vendor_response";
  run.outreachEmailCount += 1;
  run.nextActionAt = new Date(Date.now() + 4 * 86_400_000).toISOString();
  run.updatedAt = nowIso();

  return { ok: true, message: "Revision requested. Rowan emailed the vendor with your note and is waiting on a reply." };
}

// ---------------------------------------------------------------------------
// Escalation (PM-escalation) commands
// ---------------------------------------------------------------------------

export function resolveEscalation(cmd: ResolveEscalationCommand): CommandResult {
  const esc = findEscalationOrThrow(cmd.escalationId);
  const run = findRunOrThrow(esc.runId);
  const fromState = run.state;

  if (cmd.resolution === "resolved") {
    esc.status = "resolved";
    esc.resolution = "acknowledged";
    esc.resolvedAt = nowIso();

    pushEvent({
      organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
      eventType: "human_intervention", name: "human.resolve_escalation", severity: "info",
      fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
      inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
      payload: { escalation_id: esc.id, note: cmd.note ?? null, actor: "Dana Alvarez" }, createdAt: nowIso(),
    });
    pushEvent({
      organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
      eventType: "state_transition", name: "state.transition", severity: "info",
      fromState, toState: "monitoring", toolName: null, llmModel: null, promptHash: null,
      inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
      payload: { guard: "PM marked resolved -- handled out-of-band" }, createdAt: nowIso(),
    });

    run.state = "monitoring";
    run.updatedAt = nowIso();
    return { ok: true, message: "Marked resolved. Rowan has returned this vendor to normal monitoring." };
  }

  // keep_chasing
  esc.status = "resolved";
  esc.resolution = "acknowledged";
  esc.resolvedAt = nowIso();

  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "human_intervention", name: "human.resolve_escalation", severity: "info",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { escalation_id: esc.id, decision: "keep_chasing", note: cmd.note ?? null, actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: esc.vendorId,
    eventType: "state_transition", name: "state.transition", severity: "info",
    fromState, toState: "awaiting_vendor_response", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: "PM asked Rowan to keep chasing -- outreach budget reopened" }, createdAt: nowIso(),
  });

  run.state = "awaiting_vendor_response";
  run.outreachEmailCount = Math.max(0, run.outreachEmailCount - 1); // PM-authorized extension
  run.nextActionAt = new Date(Date.now() + 4 * 86_400_000).toISOString();
  run.updatedAt = nowIso();
  return { ok: true, message: "Got it -- Rowan will keep chasing this vendor for one more round." };
}

// ---------------------------------------------------------------------------
// Run lifecycle commands
// ---------------------------------------------------------------------------

export function pauseRun(cmd: PauseRunCommand): CommandResult {
  const run = findRunOrThrow(cmd.runId);
  run.status = "paused";
  run.updatedAt = nowIso();
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: run.vendorId,
    eventType: "human_intervention", name: "human.pause_run", severity: "info",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { reason: cmd.reason ?? null, actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  return { ok: true, message: "Paused. Rowan will take no further automated action on this run until you resume it." };
}

export function resumeRun(cmd: ResumeRunCommand): CommandResult {
  const run = findRunOrThrow(cmd.runId);
  run.status = "active";
  run.updatedAt = nowIso();
  pushEvent({
    organizationId: ORG_ID, runId: run.id, vendorId: run.vendorId,
    eventType: "human_intervention", name: "human.resume_run", severity: "info",
    fromState: null, toState: null, toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { actor: "Dana Alvarez" }, createdAt: nowIso(),
  });
  return { ok: true, message: "Resumed. Rowan will pick this run back up on its next scheduled action." };
}

export function startRun(cmd: StartRunCommand): CommandResult<{ runId: string }> {
  const vendor = vendors.find((v) => v.id === cmd.vendorId);
  if (!vendor) return { ok: false, message: "Unknown vendor." };
  const existing = runs.find((r) => r.vendorId === cmd.vendorId && r.status === "active");
  if (existing) return { ok: false, message: "This vendor already has an active run.", data: { runId: existing.id } };

  const runId = nextId("run");
  const dueDate = new Date(Date.now() + 45 * 86_400_000).toISOString().slice(0, 10);
  runs.push({
    id: runId,
    organizationId: ORG_ID,
    vendorId: vendor.id,
    coiDocumentId: null,
    state: "renewal_due_soon",
    status: "active",
    trigger: cmd.trigger,
    dueDate,
    nextActionAt: nowIso(),
    outreachEmailCount: 0,
    llmCallCount: 0,
    costCentsSpent: 0,
    budgetCostCapCents: 200,
    startedAt: nowIso(),
    updatedAt: nowIso(),
    completedAt: null,
  });
  pushEvent({
    organizationId: ORG_ID, runId, vendorId: vendor.id,
    eventType: "state_transition", name: "state.transition", severity: "info",
    fromState: "monitoring", toState: "renewal_due_soon", toolName: null, llmModel: null, promptHash: null,
    inputTokens: null, outputTokens: null, costCents: null, latencyMs: null,
    payload: { guard: cmd.trigger === "manual" ? "PM manually started renewal" : "now >= due_date - RENEWAL_LEAD_DAYS", trigger: cmd.trigger === "manual" ? "human" : "scheduler" }, createdAt: nowIso(),
  });
  return { ok: true, message: `Started a renewal run for ${vendor.name}.`, data: { runId } };
}

// ---------------------------------------------------------------------------
// Onboarding commands
// ---------------------------------------------------------------------------

export function addVendor(cmd: AddVendorCommand): CommandResult<{ vendorId: string }> {
  const vendorId = nextId("ven");
  const record: VendorRecord = {
    id: vendorId,
    organizationId: ORG_ID,
    name: cmd.name,
    primaryEmail: cmd.primaryEmail || null,
    vendorRole: cmd.vendorRole,
    status: "active",
    primaryPropertyId: cmd.primaryPropertyId,
    notes: cmd.notes ?? null,
  };
  vendors.push(record);
  return { ok: true, message: `${cmd.name} added. Set coverage requirements next so Rowan knows what to validate against.`, data: { vendorId } };
}

export function setRequirements(cmd: SetRequirementsCommand): CommandResult {
  // Remove prior lines for this vendor (unique(vendor_id, coverage_type) in
  // the real schema -- a full replace is the simplest correct mock behavior).
  for (let i = vendorCoverageRequirements.length - 1; i >= 0; i -= 1) {
    if (vendorCoverageRequirements[i].vendorId === cmd.vendorId) vendorCoverageRequirements.splice(i, 1);
  }
  cmd.lines.forEach((line) => {
    const cr = line.sourceComplianceRequirementId
      ? complianceRequirements.find((c) => c.id === line.sourceComplianceRequirementId)
      : undefined;
    const record: VendorCoverageRequirementRecord = {
      id: nextId("vcr"),
      organizationId: ORG_ID,
      vendorId: cmd.vendorId,
      coverageType: line.coverageType,
      minEachOccurrence: line.minEachOccurrence,
      minAggregate: line.minAggregate,
      requiresAdditionalInsured: line.requiresAdditionalInsured,
      requiresWaiverOfSubrogation: line.requiresWaiverOfSubrogation,
      requiresPrimaryNoncontributory: line.requiresPrimaryNoncontributory,
      sourceComplianceRequirementId: cr?.id ?? null,
      confirmedByPm: true,
    };
    vendorCoverageRequirements.push(record);
  });
  return { ok: true, message: `Saved ${cmd.lines.length} coverage requirement${cmd.lines.length === 1 ? "" : "s"}.` };
}
