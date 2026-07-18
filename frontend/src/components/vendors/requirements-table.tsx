import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Check, X } from "lucide-react";
import type { RequirementLineDTO } from "@/lib/types";
import { CitationEvidenceChip } from "@/components/shared/evidence";
import { formatCoverageType, formatDollars } from "@/lib/format";
import { cn } from "@/lib/utils";

function FlagCell({ on }: { on: boolean }) {
  return on ? (
    <Check className="size-4 text-emerald-600 dark:text-emerald-400" />
  ) : (
    <X className="size-4 text-muted-foreground/40" />
  );
}

export function RequirementsTable({ requirements }: { requirements: RequirementLineDTO[] }) {
  if (requirements.length === 0) {
    return (
      <p className="px-6 py-8 text-center text-sm text-muted-foreground">
        No coverage requirements set for this vendor yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Coverage</TableHead>
            <TableHead>Min. each occurrence</TableHead>
            <TableHead>Min. aggregate</TableHead>
            <TableHead className="text-center">Add&apos;l insured</TableHead>
            <TableHead className="text-center">Waiver of subro.</TableHead>
            <TableHead className="text-center">Primary / non-contrib.</TableHead>
            <TableHead>Source</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {requirements.map((r) => (
            <TableRow key={r.vendorCoverageRequirementId} className={cn(!r.sourceComplianceRequirementId && "bg-rose-50/40 dark:bg-rose-950/10")}>
              <TableCell className="font-medium">{formatCoverageType(r.coverageType)}</TableCell>
              <TableCell className="tabular-nums">{formatDollars(r.minEachOccurrence)}</TableCell>
              <TableCell className="tabular-nums">{formatDollars(r.minAggregate)}</TableCell>
              <TableCell className="text-center"><FlagCell on={r.requiresAdditionalInsured} /></TableCell>
              <TableCell className="text-center"><FlagCell on={r.requiresWaiverOfSubrogation} /></TableCell>
              <TableCell className="text-center"><FlagCell on={r.requiresPrimaryNoncontributory} /></TableCell>
              <TableCell>
                <CitationEvidenceChip
                  citation={r.sourceCitation}
                  url={r.sourceUrl}
                  lastVerifiedAt={r.lastVerifiedAt}
                  unverified={!r.sourceComplianceRequirementId}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
