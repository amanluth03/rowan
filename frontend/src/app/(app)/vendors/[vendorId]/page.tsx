import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, Mail, MapPin } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ComplianceStatusBadge, RunStateBadge } from "@/components/shared/status-badge";
import { DocumentEvidenceChip } from "@/components/shared/evidence";
import { RequirementsTable } from "@/components/vendors/requirements-table";
import { CoiHistoryTable } from "@/components/vendors/coi-history-table";
import { RunControls } from "@/components/vendors/run-controls";
import { getVendorStatus } from "@/lib/api/read-models";
import { formatDate, formatVendorRole, relativeTime } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function VendorDetailPage({
  params,
}: {
  params: Promise<{ vendorId: string }>;
}) {
  const { vendorId } = await params;
  const vendor = await getVendorStatus(vendorId);
  if (!vendor) notFound();

  return (
    <>
      <PageHeader
        title={vendor.name}
        description={
          vendor.primaryPropertyName
            ? `${formatVendorRole(vendor.role)} · ${vendor.primaryPropertyName}`
            : formatVendorRole(vendor.role)
        }
        actions={<ComplianceStatusBadge status={vendor.complianceStatus} className="text-sm" />}
      />

      <div className="flex flex-col gap-6 p-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-muted-foreground">
          {vendor.primaryEmail ? (
            <span className="inline-flex items-center gap-1.5"><Mail className="size-3.5" />{vendor.primaryEmail}</span>
          ) : null}
          {vendor.primaryPropertyJurisdiction ? (
            <span className="inline-flex items-center gap-1.5"><MapPin className="size-3.5" />{vendor.primaryPropertyJurisdiction}</span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-muted-foreground/70"><MapPin className="size-3.5" />No property on file</span>
          )}
        </div>

        {vendor.activeRun ? (
          <Card className="border-primary/20">
            <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
              <div className="flex items-center gap-3">
                <RunStateBadge state={vendor.activeRun.state} />
                <div className="text-sm">
                  <p className="font-medium text-foreground">
                    Renewal due {formatDate(vendor.activeRun.dueDate)}
                    {vendor.activeRun.status === "paused" ? " · paused" : ""}
                  </p>
                  <p className="text-muted-foreground">
                    {vendor.activeRun.outreachEmailCount}/{vendor.activeRun.maxOutreach} outreach emails sent
                    {vendor.activeRun.nextActionAt ? ` · next action ${relativeTime(vendor.activeRun.nextActionAt)}` : ""}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <RunControls runId={vendor.activeRun.runId} status={vendor.activeRun.status} />
                <Button asChild size="sm">
                  <Link href={`/runs/${vendor.activeRun.runId}`}>
                    View trace <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </div>
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Current certificate</CardTitle>
          </CardHeader>
          <CardContent>
            {vendor.currentCoi ? (
              <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Valid</p>
                  <p className="text-sm font-medium">{formatDate(vendor.currentCoi.validFrom)} – {formatDate(vendor.currentCoi.validTo)}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">Filed</p>
                  <p className="text-sm font-medium">{formatDate(vendor.currentCoi.filedAt)}</p>
                </div>
                <DocumentEvidenceChip document={vendor.currentCoi.document} label="View certificate" />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No certificate on file yet — Rowan hasn&apos;t received one for this vendor.</p>
            )}
          </CardContent>
        </Card>

        <Card className="py-0 overflow-hidden gap-0">
          <CardHeader className="border-b border-border py-4 [.border-b]:pb-4">
            <CardTitle className="text-base">Coverage requirements</CardTitle>
          </CardHeader>
          <RequirementsTable requirements={vendor.requirements} />
        </Card>

        <Card className="py-0 overflow-hidden gap-0">
          <CardHeader className="border-b border-border py-4 [.border-b]:pb-4">
            <CardTitle className="text-base">Certificate history</CardTitle>
          </CardHeader>
          <CoiHistoryTable history={vendor.history} />
        </Card>
      </div>
    </>
  );
}
