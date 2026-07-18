import { Circle } from "lucide-react";
import { SidebarNav } from "./sidebar-nav";
import { getReviewQueue } from "@/lib/api/read-models";

/**
 * # ASSUMPTION / GAP (flagged to tech lead / backend-engineer): there is no
 * `organizations` read model in the REST API -- ADR 0003's 4 DTOs don't
 * cover it, and there's no `GET /api/v1/organization` route either, so the
 * org name and the per-org `agent_enabled` kill-switch flag (CLAUDE.md's
 * per-org agent disable) have no live data source for the sidebar's "Agent
 * active/disabled" indicator. `agentEnabled` is hardcoded `true` here rather
 * than fabricating a fetch; the org name falls back to the same env var this
 * app already needs for the dev-auth stub. `/health`'s `kill_switch` field
 * is the GLOBAL env-flag kill switch (CLAUDE.md), a different, org-agnostic
 * concept from this per-org flag -- not substituted here to avoid
 * conflating the two.
 */
const ORG_DISPLAY_NAME = process.env.ROWAN_ORG_NAME ?? "Rowan Demo Property Management";
const AGENT_ENABLED = true;

export async function AppShell({ children }: { children: React.ReactNode }) {
  const reviewQueue = await getReviewQueue();

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1440px]">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between border-r border-sidebar-border bg-sidebar px-3 py-4 md:flex">
        <SidebarNav reviewCount={reviewQueue.length} />

        <div className="flex flex-col gap-3 px-2">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Circle className={AGENT_ENABLED ? "size-2 fill-emerald-500 text-emerald-500" : "size-2 fill-rose-500 text-rose-500"} />
            {AGENT_ENABLED ? "Agent active" : "Agent disabled"}
          </div>
          <div className="flex items-center gap-2 rounded-md border border-sidebar-border px-2 py-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold">
              DA
            </span>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium leading-tight">Dana Alvarez</p>
              <p className="truncate text-[11px] text-muted-foreground leading-tight">{ORG_DISPLAY_NAME}</p>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
