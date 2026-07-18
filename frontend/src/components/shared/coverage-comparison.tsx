import { Check, Minus, X } from "lucide-react";
import type { LineComparisonDTO } from "@/lib/types";
import { CitationEvidenceChip } from "@/components/shared/evidence";
import { SeverityBadge } from "@/components/shared/status-badge";
import { formatCoverageType, formatDollars } from "@/lib/format";
import { cn } from "@/lib/utils";

function BoolCell({ value }: { value: boolean | null }) {
  if (value === null) return <Minus className="size-3.5 text-muted-foreground/50" />;
  return value ? <Check className="size-3.5 text-emerald-600 dark:text-emerald-400" /> : <X className="size-3.5 text-rose-500" />;
}

function mismatch(required: number | null, parsed: number | null | undefined): boolean {
  if (required === null) return false;
  if (parsed === undefined || parsed === null) return true;
  return parsed < required;
}

export function CoverageComparisonList({ comparison }: { comparison: LineComparisonDTO[] }) {
  if (comparison.length === 0) {
    return <p className="px-6 py-8 text-center text-sm text-muted-foreground">No coverage lines to compare.</p>;
  }

  return (
    <ul className="divide-y divide-border">
      {comparison.map((line) => {
        const eachMismatch = mismatch(line.required.minEachOccurrence, line.parsed?.eachOccurrence);
        const aggMismatch = mismatch(line.required.minAggregate, line.parsed?.aggregate);
        return (
          <li key={line.coverageType} className={cn("px-6 py-4", !line.pass && "bg-rose-50/30 dark:bg-rose-950/10")}>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h4 className="text-sm font-semibold text-foreground">{formatCoverageType(line.coverageType)}</h4>
                <SeverityBadge severity={line.pass ? "info" : line.severity} />
              </div>
              <CitationEvidenceChip
                citation={line.required.sourceCitation}
                url={line.required.sourceUrl}
                lastVerifiedAt={line.required.lastVerifiedAt}
                unverified={!line.required.sourceComplianceRequirementId}
              />
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="rounded-md border border-border bg-muted/30 p-3">
                <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Required</p>
                <dl className="space-y-1 text-sm">
                  <div className="flex justify-between"><dt className="text-muted-foreground">Each occurrence</dt><dd className="tabular-nums">{formatDollars(line.required.minEachOccurrence)}</dd></div>
                  <div className="flex justify-between"><dt className="text-muted-foreground">Aggregate</dt><dd className="tabular-nums">{formatDollars(line.required.minAggregate)}</dd></div>
                  <div className="flex justify-between items-center"><dt className="text-muted-foreground">Additional insured</dt><dd><BoolCell value={line.required.requiresAdditionalInsured} /></dd></div>
                  <div className="flex justify-between items-center"><dt className="text-muted-foreground">Waiver of subrogation</dt><dd><BoolCell value={line.required.requiresWaiverOfSubrogation} /></dd></div>
                  <div className="flex justify-between items-center"><dt className="text-muted-foreground">Primary / non-contributory</dt><dd><BoolCell value={line.required.requiresPrimaryNoncontributory} /></dd></div>
                </dl>
              </div>

              <div className={cn("rounded-md border p-3", !line.pass ? "border-rose-200 bg-rose-50/50 dark:border-rose-900 dark:bg-rose-950/20" : "border-border bg-muted/30")}>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Parsed from certificate</p>
                  {line.parsed?.confidence !== null && line.parsed?.confidence !== undefined ? (
                    <span className="text-[11px] text-muted-foreground">{(line.parsed.confidence * 100).toFixed(0)}% confidence</span>
                  ) : null}
                </div>
                {line.parsed ? (
                  <dl className="space-y-1 text-sm">
                    <div className="flex justify-between"><dt className="text-muted-foreground">Each occurrence</dt><dd className={cn("tabular-nums", eachMismatch && "font-medium text-rose-600 dark:text-rose-400")}>{formatDollars(line.parsed.eachOccurrence)}</dd></div>
                    <div className="flex justify-between"><dt className="text-muted-foreground">Aggregate</dt><dd className={cn("tabular-nums", aggMismatch && "font-medium text-rose-600 dark:text-rose-400")}>{formatDollars(line.parsed.aggregate)}</dd></div>
                    <div className="flex justify-between items-center"><dt className="text-muted-foreground">Additional insured</dt><dd><BoolCell value={line.parsed.additionalInsured} /></dd></div>
                    <div className="flex justify-between items-center"><dt className="text-muted-foreground">Waiver of subrogation</dt><dd><BoolCell value={line.parsed.waiverOfSubrogation} /></dd></div>
                    <div className="flex justify-between items-center"><dt className="text-muted-foreground">Primary / non-contributory</dt><dd><BoolCell value={line.parsed.primaryNoncontributory} /></dd></div>
                  </dl>
                ) : (
                  <p className="text-sm text-muted-foreground">Not yet parsed.</p>
                )}
              </div>
            </div>
            {line.note ? <p className="mt-2 text-sm text-muted-foreground">{line.note}</p> : null}
          </li>
        );
      })}
    </ul>
  );
}
