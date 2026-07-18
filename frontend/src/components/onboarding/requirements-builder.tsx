"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
import { Plus, Sparkles, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { setRequirementsAction, getRequirementSuggestionsAction } from "@/app/actions";
import type { CoverageType, RequirementLineDTO } from "@/lib/types";
import { formatCoverageType } from "@/lib/format";
import { CitationEvidenceChip } from "@/components/shared/evidence";

const COVERAGE_TYPES: CoverageType[] = [
  "general_liability",
  "auto_liability",
  "workers_comp",
  "umbrella_excess",
  "professional_liability",
  "pollution",
  "employers_liability",
];

interface DraftLine {
  key: string;
  coverageType: CoverageType;
  minEachOccurrence: string;
  minAggregate: string;
  requiresAdditionalInsured: boolean;
  requiresWaiverOfSubrogation: boolean;
  requiresPrimaryNoncontributory: boolean;
  sourceComplianceRequirementId: string | null;
  sourceCitation: string | null;
  sourceUrl: string | null;
  lastVerifiedAt: string | null;
}

let keySeq = 0;
function blankLine(): DraftLine {
  keySeq += 1;
  return {
    key: `draft_${keySeq}`,
    coverageType: "general_liability",
    minEachOccurrence: "",
    minAggregate: "",
    requiresAdditionalInsured: false,
    requiresWaiverOfSubrogation: false,
    requiresPrimaryNoncontributory: false,
    sourceComplianceRequirementId: null,
    sourceCitation: null,
    sourceUrl: null,
    lastVerifiedAt: null,
  };
}

function fromSuggestion(line: RequirementLineDTO): DraftLine {
  keySeq += 1;
  return {
    key: `draft_${keySeq}`,
    coverageType: line.coverageType,
    minEachOccurrence: line.minEachOccurrence?.toString() ?? "",
    minAggregate: line.minAggregate?.toString() ?? "",
    requiresAdditionalInsured: line.requiresAdditionalInsured,
    requiresWaiverOfSubrogation: line.requiresWaiverOfSubrogation,
    requiresPrimaryNoncontributory: line.requiresPrimaryNoncontributory,
    sourceComplianceRequirementId: line.sourceComplianceRequirementId,
    sourceCitation: line.sourceCitation,
    sourceUrl: line.sourceUrl,
    lastVerifiedAt: line.lastVerifiedAt,
  };
}

export function RequirementsBuilder({
  vendorId,
  vendorName,
}: {
  vendorId: string;
  vendorName: string;
}) {
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [isPending, startTransition] = useTransition();
  const [isSuggesting, startSuggesting] = useTransition();

  function updateLine(key: string, patch: Partial<DraftLine>) {
    setLines((prev) => prev.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          Setting requirements for <span className="font-medium text-foreground">{vendorName}</span>.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isSuggesting}
          onClick={() =>
            startSuggesting(async () => {
              const { found, lines: suggested } = await getRequirementSuggestionsAction(vendorId);
              if (!found) {
                toast("No verified requirements on file for this vendor's jurisdiction and trade yet — add lines manually below.");
                return;
              }
              setLines(suggested.map(fromSuggestion));
              toast(`Suggested ${suggested.length} requirement${suggested.length === 1 ? "" : "s"} from your compliance library — review before saving.`);
            })
          }
        >
          <Sparkles className="size-4" />
          Suggest from compliance library
        </Button>
      </div>

      {lines.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
          No requirement lines yet. Use &quot;Suggest from compliance library&quot; to pre-fill from Rowan&apos;s verified requirements, or add a line manually.
        </div>
      ) : (
        <ul className="space-y-3">
          {lines.map((line) => (
            <li key={line.key} className="rounded-lg border border-border p-3">
              <div className="mb-3 flex items-start justify-between gap-2">
                <div className="w-56">
                  <Select value={line.coverageType} onValueChange={(v) => updateLine(line.key, { coverageType: v as CoverageType, sourceComplianceRequirementId: null, sourceCitation: null })}>
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {COVERAGE_TYPES.map((c) => (
                        <SelectItem key={c} value={c}>{formatCoverageType(c)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-2">
                  <CitationEvidenceChip
                    citation={line.sourceCitation}
                    url={line.sourceUrl}
                    lastVerifiedAt={line.lastVerifiedAt}
                    unverified={!line.sourceComplianceRequirementId}
                  />
                  <Button type="button" variant="ghost" size="icon" className="size-8 text-muted-foreground hover:text-rose-600" onClick={() => setLines((prev) => prev.filter((l) => l.key !== line.key))}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                <div className="col-span-1 space-y-1">
                  <Label className="text-xs text-muted-foreground">Each occurrence ($)</Label>
                  <Input
                    type="number"
                    min={0}
                    value={line.minEachOccurrence}
                    onChange={(e) => updateLine(line.key, { minEachOccurrence: e.target.value })}
                    placeholder="1000000"
                  />
                </div>
                <div className="col-span-1 space-y-1">
                  <Label className="text-xs text-muted-foreground">Aggregate ($)</Label>
                  <Input
                    type="number"
                    min={0}
                    value={line.minAggregate}
                    onChange={(e) => updateLine(line.key, { minAggregate: e.target.value })}
                    placeholder="2000000"
                  />
                </div>
                <label className="col-span-1 flex items-center gap-2 self-end pb-1.5 text-xs text-muted-foreground">
                  <Checkbox checked={line.requiresAdditionalInsured} onCheckedChange={(v) => updateLine(line.key, { requiresAdditionalInsured: v === true })} />
                  Add&apos;l insured
                </label>
                <label className="col-span-1 flex items-center gap-2 self-end pb-1.5 text-xs text-muted-foreground">
                  <Checkbox checked={line.requiresWaiverOfSubrogation} onCheckedChange={(v) => updateLine(line.key, { requiresWaiverOfSubrogation: v === true })} />
                  Waiver of subro.
                </label>
                <label className="col-span-1 flex items-center gap-2 self-end pb-1.5 text-xs text-muted-foreground">
                  <Checkbox checked={line.requiresPrimaryNoncontributory} onCheckedChange={(v) => updateLine(line.key, { requiresPrimaryNoncontributory: v === true })} />
                  Primary/non-contrib.
                </label>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" size="sm" onClick={() => setLines((prev) => [...prev, blankLine()])}>
          <Plus className="size-4" />
          Add line manually
        </Button>
        <Button
          type="button"
          disabled={lines.length === 0 || isPending}
          onClick={() =>
            startTransition(async () => {
              const result = await setRequirementsAction({
                vendorId,
                lines: lines.map((l) => ({
                  coverageType: l.coverageType,
                  minEachOccurrence: l.minEachOccurrence === "" ? null : Number(l.minEachOccurrence),
                  minAggregate: l.minAggregate === "" ? null : Number(l.minAggregate),
                  requiresAdditionalInsured: l.requiresAdditionalInsured,
                  requiresWaiverOfSubrogation: l.requiresWaiverOfSubrogation,
                  requiresPrimaryNoncontributory: l.requiresPrimaryNoncontributory,
                  sourceComplianceRequirementId: l.sourceComplianceRequirementId ?? undefined,
                })),
              });
              toast(result.message);
            })
          }
        >
          Save requirements
        </Button>
      </div>
    </div>
  );
}
