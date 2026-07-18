"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutList, ListChecks, ShieldCheck, UserPlus, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  match: (path: string) => boolean;
}

const items: NavItem[] = [
  { href: "/", label: "Activity", icon: LayoutList, match: (p) => p === "/" },
  { href: "/vendors", label: "Vendors", icon: Users, match: (p) => p.startsWith("/vendors") },
  { href: "/review", label: "Review queue", icon: ListChecks, match: (p) => p.startsWith("/review") },
  { href: "/onboarding", label: "Onboarding", icon: UserPlus, match: (p) => p.startsWith("/onboarding") },
];

export function SidebarNav({ reviewCount }: { reviewCount: number }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-6">
      <Link href="/" className="flex items-center gap-2 px-2">
        <span className="flex size-7 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <ShieldCheck className="size-4" />
        </span>
        <span className="text-[15px] font-semibold tracking-tight">Rowan</span>
      </Link>

      <div className="flex flex-col gap-0.5">
        {items.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex items-center justify-between rounded-md px-2.5 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              )}
            >
              <span className="flex items-center gap-2.5">
                <Icon className="size-4" />
                {item.label}
              </span>
              {item.href === "/review" && reviewCount > 0 ? (
                <Badge variant="secondary" className="h-5 min-w-5 justify-center rounded-full px-1.5 text-[11px] tabular-nums">
                  {reviewCount}
                </Badge>
              ) : null}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
