import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunStateBadge } from "@/components/shared/status-badge";
import { Badge } from "@/components/ui/badge";
import { BudgetBar } from "@/components/trace/budget-bar";
import { TraceTimeline } from "@/components/trace/trace-timeline";
import { CoverageComparisonList } from "@/components/shared/coverage-comparison";
import { DocumentEvidenceChip } from "@/components/shared/evidence";
import {
  getRunComparison,
  getRunDocument,
  getRunTrace,
} from "@/lib/mock/read-models";
import { formatDate, formatDateTime, formatVendorRole } from "@/lib/format";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const run = await getRunTrace(runId);
  if (!run) notFound();

  const [comparison, document] = await Promise.all([
    getRunComparison(run.runId, run.vendorId),
    getRunDocument(run.runId),
  ]);

  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            <Link href={`/vendors/${run.vendorId}`} className="hover:underline underline-offset-2">{run.vendorName}</Link>
            <span className="font-mono text-xs font-normal text-muted-foreground">{run.runId}</span>
          </span>
        }
        description={`${formatVendorRole(run.vendorRole)} · renewal due ${formatDate(run.dueDate)} · started ${formatDateTime(run.startedAt)}`}
        actions={
          <div className="flex items-center gap-2">
            {run.status === "paused" ? <Badge variant="outline">paused</Badge> : null}
            <RunStateBadge state={run.state} className="text-sm" />
          </div>
        }
      />

      <div className="flex flex-col gap-6 p-6">
        <BudgetBar budget={run.budget} />

        {document ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>Source certificate for this cycle:</span>
            <DocumentEvidenceChip document={document} />
          </div>
        ) : null}

        {comparison.length > 0 ? (
          <Card className="overflow-hidden gap-0 py-0">
            <CardHeader className="border-b border-border py-4 [.border-b]:pb-4">
              <CardTitle className="text-base">Coverage validation</CardTitle>
            </CardHeader>
            <CoverageComparisonList comparison={comparison} />
          </Card>
        ) : null}

        <Card className="overflow-hidden gap-0 py-0">
          <CardHeader className="border-b border-border py-4 [.border-b]:pb-4">
            <CardTitle className="text-base">Trace</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <TraceTimeline events={run.events} />
          </CardContent>
        </Card>
      </div>
    </>
  );
}
