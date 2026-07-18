import type { AgentEventDTO } from "@/lib/types";
import { EventIcon } from "./event-icon";
import { describeEvent } from "@/lib/trace-format";
import { formatCents, formatDateTime } from "@/lib/format";
import { Badge } from "@/components/ui/badge";

const typeLabel: Record<string, string> = {
  state_transition: "State change",
  tool_call: "Tool call",
  llm_call: "Model call",
  guardrail_trip: "Guardrail",
  human_intervention: "You",
  error: "Error",
  note: "Note",
};

function EventRow({ event, isLast }: { event: AgentEventDTO; isLast: boolean }) {
  const { title, detail } = describeEvent(event);
  const hasLlmMeta = event.type === "llm_call" && (event.inputTokens || event.outputTokens || event.costCents !== null);

  return (
    <li className="relative flex gap-3 pb-6">
      {!isLast ? <span className="absolute left-3.5 top-7 h-[calc(100%-1.75rem)] w-px bg-border" aria-hidden /> : null}
      <EventIcon type={event.type} severity={event.severity} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="outline" className="text-[10px] font-normal text-muted-foreground">{typeLabel[event.type]}</Badge>
            <p className="text-sm font-medium leading-snug text-foreground">{title}</p>
          </div>
          <time className="shrink-0 text-xs text-muted-foreground" dateTime={event.createdAt}>{formatDateTime(event.createdAt)}</time>
        </div>
        {detail ? <p className="mt-0.5 text-sm leading-snug text-muted-foreground">{detail}</p> : null}
        {hasLlmMeta ? (
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground">
            {event.llmModel ? <span>{event.llmModel}</span> : null}
            {event.inputTokens ? <span>{event.inputTokens.toLocaleString()} in</span> : null}
            {event.outputTokens ? <span>{event.outputTokens.toLocaleString()} out</span> : null}
            {event.costCents !== null ? <span>{formatCents(event.costCents)}</span> : null}
            {event.latencyMs ? <span>{(event.latencyMs / 1000).toFixed(1)}s</span> : null}
            {event.promptHash ? <span title="Prompt hash">{event.promptHash}</span> : null}
          </div>
        ) : null}
      </div>
    </li>
  );
}

export function TraceTimeline({ events }: { events: AgentEventDTO[] }) {
  if (events.length === 0) {
    return <p className="px-6 py-8 text-center text-sm text-muted-foreground">No events recorded yet.</p>;
  }
  return (
    <ol className="px-6 py-5">
      {events.map((event, i) => (
        <EventRow key={event.id} event={event} isLast={i === events.length - 1} />
      ))}
    </ol>
  );
}
