import { FileText, ScrollText } from "lucide-react";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import type { DocumentRef } from "@/lib/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Every rendered claim (a status badge, a "compliant" label, a pass/fail on a
 * coverage line) must resolve to evidence -- the document, the parsed value,
 * or the KB citation behind it -- per CLAUDE.md's brand section. These two
 * small components are the reusable "evidence chip" used across all five
 * screens so that link is never just implied.
 *
 * # ASSUMPTION: Supabase Storage isn't wired up yet, so "open document"
 * surfaces the stored path/filename rather than an actual file preview.
 * Swapping in a real signed URL is a one-line change once storage exists.
 */

export function DocumentEvidenceChip({ document, label = "Source document" }: { document: DocumentRef; label?: string }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <FileText className="size-3.5" />
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <div className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-medium leading-tight">{document.filename}</p>
              <p className="text-xs text-muted-foreground">Version {document.versionNumber} · {document.contentType}</p>
            </div>
            <Badge variant="outline" className="shrink-0 text-[10px]">evidence</Badge>
          </div>
          <div className="rounded-md bg-muted/50 px-2 py-1.5 font-mono text-[11px] text-muted-foreground break-all">
            {document.url}
          </div>
          <p className="text-[11px] text-muted-foreground">
            This is the exact certificate Rowan read for the claims shown here. Storage preview isn&apos;t wired up in this build yet.
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}

export function CitationEvidenceChip({
  citation,
  url,
  lastVerifiedAt,
  unverified,
}: {
  citation: string | null;
  url?: string | null;
  lastVerifiedAt?: string | null;
  unverified?: boolean;
}) {
  if (unverified || !citation) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-xs font-medium text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-400">
        <ScrollText className="size-3.5" />
        No verified requirement on file
      </span>
    );
  }
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
          )}
        >
          <ScrollText className="size-3.5" />
          Requirement source
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-foreground">{citation}</p>
          {/* SECURITY: url is curated-KB-only today (fixtures.ts sourceUrl); add an http/https
              scheme allowlist before this can render a URL sourced from inbound documents/email. */}
          {url ? (
            <a href={url} target="_blank" rel="noreferrer" className="text-xs text-primary underline underline-offset-2">
              View source
            </a>
          ) : null}
          {lastVerifiedAt ? (
            <p className="text-[11px] text-muted-foreground">Last verified {formatDateTime(lastVerifiedAt)}</p>
          ) : null}
        </div>
      </PopoverContent>
    </Popover>
  );
}
