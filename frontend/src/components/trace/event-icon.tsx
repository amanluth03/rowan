import {
  AlertTriangle,
  ArrowRightLeft,
  Bot,
  CircleDot,
  Hand,
  OctagonAlert,
  Wrench,
} from "lucide-react";
import type { EventSeverity, EventType } from "@/lib/types";
import { cn } from "@/lib/utils";

const byType: Record<EventType, React.ComponentType<{ className?: string }>> = {
  state_transition: ArrowRightLeft,
  tool_call: Wrench,
  llm_call: Bot,
  guardrail_trip: AlertTriangle,
  human_intervention: Hand,
  error: OctagonAlert,
  note: CircleDot,
};

const severityClass: Record<EventSeverity, string> = {
  info: "bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300",
  warn: "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400",
  error: "bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400",
};

export function EventIcon({ type, severity }: { type: EventType; severity: EventSeverity }) {
  const Icon = byType[type];
  return (
    <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full ring-4 ring-background", severityClass[severity])}>
      <Icon className="size-3.5" />
    </span>
  );
}
