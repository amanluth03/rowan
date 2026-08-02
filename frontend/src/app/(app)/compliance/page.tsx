import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { getComplianceObligations } from "@/lib/api/read-models";
import type { ComplianceObligationDTO, ObligationCategory } from "@/lib/types";
import { ExternalLink } from "lucide-react";

export const dynamic = "force-dynamic";

const CATEGORY_LABELS: Record<ObligationCategory, string> = {
  registration: "Registration",
  disclosure: "Disclosure",
  inspection: "Inspection",
  insurance: "Insurance",
  safety: "Safety",
  fee: "Fee",
};

const CATEGORY_COLORS: Record<ObligationCategory, string> = {
  registration: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  disclosure: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  inspection: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  insurance: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  safety: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  fee: "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
};

const LEVEL_ORDER = ["federal", "state", "county", "municipal"] as const;

function groupByJurisdiction(obligations: ComplianceObligationDTO[]) {
  const groups = new Map<string, { level: string; items: ComplianceObligationDTO[] }>();
  for (const o of obligations) {
    if (!groups.has(o.jurisdiction)) {
      groups.set(o.jurisdiction, { level: o.jurisdictionLevel, items: [] });
    }
    groups.get(o.jurisdiction)!.items.push(o);
  }
  return [...groups.entries()]
    .sort(([, a], [, b]) => LEVEL_ORDER.indexOf(a.level as typeof LEVEL_ORDER[number]) - LEVEL_ORDER.indexOf(b.level as typeof LEVEL_ORDER[number]))
    .map(([name, { level, items }]) => ({ name, level, items }));
}

function ApplicabilityNote({ o }: { o: ComplianceObligationDTO }) {
  const parts: string[] = [];
  if (o.buildYearBefore) parts.push(`pre-${o.buildYearBefore} buildings`);
  if (o.minUnits && o.maxUnits) parts.push(`${o.minUnits}–${o.maxUnits} units`);
  else if (o.minUnits) parts.push(`${o.minUnits}+ units`);
  else if (o.maxUnits) parts.push(`≤${o.maxUnits} units`);
  if (!parts.length) return null;
  return <span className="text-xs text-muted-foreground">({parts.join(", ")})</span>;
}

export default async function CompliancePage() {
  const obligations = await getComplianceObligations();
  const groups = groupByJurisdiction(obligations);

  return (
    <>
      <PageHeader
        title="Compliance requirements"
        description="Every landlord obligation Rowan knows about, by jurisdiction. Citations link to source text."
      />

      <div className="divide-y divide-border">
        {groups.map(({ name, level, items }) => (
          <section key={name} className="px-6 py-6">
            <div className="mb-4 flex items-center gap-3">
              <h2 className="text-base font-semibold">{name}</h2>
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs capitalize text-muted-foreground">
                {level}
              </span>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="pb-2 pr-4 font-medium">Category</th>
                    <th className="pb-2 pr-4 font-medium">Requirement</th>
                    <th className="pb-2 pr-4 font-medium">Due</th>
                    <th className="pb-2 pr-4 font-medium">Penalty</th>
                    <th className="pb-2 font-medium">Citation</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {items.map((o) => (
                    <tr key={o.id} className="group align-top">
                      <td className="py-3 pr-4">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${CATEGORY_COLORS[o.category as ObligationCategory] ?? ""}`}
                        >
                          {CATEGORY_LABELS[o.category as ObligationCategory] ?? o.category}
                        </span>
                      </td>
                      <td className="py-3 pr-4">
                        <div className="flex flex-col gap-0.5">
                          <span className="font-medium leading-snug">
                            {o.title} <ApplicabilityNote o={o} />
                          </span>
                          {o.summary && (
                            <span className="text-xs text-muted-foreground">{o.summary}</span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 pr-4 text-xs text-muted-foreground">
                        {o.dueDescription ?? "—"}
                      </td>
                      <td className="py-3 pr-4">
                        {o.penaltyAmountDisplay ? (
                          <span
                            className="text-xs text-destructive"
                            title={o.penaltyText ?? undefined}
                          >
                            {o.penaltyAmountDisplay}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-3 text-xs">
                        {o.citation ? (
                          o.sourceUrl ? (
                            <a
                              href={o.sourceUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-primary underline underline-offset-2 hover:opacity-80"
                            >
                              {o.citation}
                              <ExternalLink className="size-3 shrink-0" />
                            </a>
                          ) : (
                            <span className="text-muted-foreground">{o.citation}</span>
                          )
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
