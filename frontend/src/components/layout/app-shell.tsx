import { Circle } from "lucide-react";
import { SidebarNav } from "./sidebar-nav";
import { organization } from "@/lib/mock/fixtures";
import { getReviewQueue } from "@/lib/mock/read-models";

export async function AppShell({ children }: { children: React.ReactNode }) {
  const reviewQueue = await getReviewQueue();

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1440px]">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between border-r border-sidebar-border bg-sidebar px-3 py-4 md:flex">
        <SidebarNav reviewCount={reviewQueue.length} />

        <div className="flex flex-col gap-3 px-2">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Circle className={organization.agentEnabled ? "size-2 fill-emerald-500 text-emerald-500" : "size-2 fill-rose-500 text-rose-500"} />
            {organization.agentEnabled ? "Agent active" : "Agent disabled"}
          </div>
          <div className="flex items-center gap-2 rounded-md border border-sidebar-border px-2 py-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-sidebar-accent text-xs font-semibold">
              DA
            </span>
            <div className="min-w-0">
              <p className="truncate text-xs font-medium leading-tight">Dana Alvarez</p>
              <p className="truncate text-[11px] text-muted-foreground leading-tight">{organization.name}</p>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
