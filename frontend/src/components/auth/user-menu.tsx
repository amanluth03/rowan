"use client";

/**
 * The signed-in user's identity, role badge, and sign-out control -- lives
 * in the app shell's sidebar footer (see `components/layout/app-shell.tsx`).
 *
 * The "Team" link is shown only for `role === "owner"` -- COSMETIC ONLY.
 * The real gate is `(app)/settings/team/page.tsx`'s server-side redirect
 * plus the backend's `require_role(Command.invite_user | ...)` (403 for an
 * assistant regardless of what this component renders). An assistant typing
 * `/settings/team` directly still gets redirected by the page itself, not by
 * this link being absent.
 */

import { useRouter } from "next/navigation";
import Link from "next/link";
import { LogOut } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { createBrowserClient } from "@/lib/supabase/browser";
import type { MeDTO } from "@/lib/api/read-models";

export function UserMenu({ email, role }: { email: string; role: MeDTO["role"] }) {
  const router = useRouter();

  async function signOut() {
    await createBrowserClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="flex items-center gap-2 rounded-md border border-sidebar-border px-2 py-2" data-testid="user-menu">
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium leading-tight" data-testid="user-menu-email">
          {email}
        </p>
        <Badge variant="secondary" className="mt-1 text-[10px] uppercase tracking-wide" data-testid="user-menu-role">
          {role}
        </Badge>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {role === "owner" ? (
          <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" asChild>
            <Link href="/settings/team" data-testid="user-menu-team-link">
              Team
            </Link>
          </Button>
        ) : null}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={signOut}
          aria-label="Sign out"
          title="Sign out"
          data-testid="user-menu-sign-out"
        >
          <LogOut className="size-3.5" />
        </Button>
      </div>
    </div>
  );
}
