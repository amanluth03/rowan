import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { CoiHistoryItemDTO } from "@/lib/types";
import { DocumentEvidenceChip } from "@/components/shared/evidence";
import { formatDate, formatDateTime } from "@/lib/format";

const sourceLabels: Record<string, string> = {
  email_inbound: "Vendor email",
  manual_upload: "Manual upload",
  onboarding_import: "Onboarding import",
};

const statusLabels: Record<string, string> = {
  received: "Received",
  parsing: "Reading",
  parsed: "Parsed",
  filed: "Filed",
  rejected: "Rejected",
  superseded: "Superseded",
};

export function CoiHistoryTable({ history }: { history: CoiHistoryItemDTO[] }) {
  if (history.length === 0) {
    return <p className="px-6 py-8 text-center text-sm text-muted-foreground">No certificates on file yet.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Version</TableHead>
            <TableHead>Valid</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Source</TableHead>
            <TableHead>Received</TableHead>
            <TableHead>Document</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {history.map((h) => (
            <TableRow key={h.document.documentId}>
              <TableCell className="font-medium">
                v{h.document.versionNumber}
                {h.isCurrent ? <Badge variant="outline" className="ml-2 text-[10px]">current</Badge> : null}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {h.validFrom && h.validTo ? `${formatDate(h.validFrom)} – ${formatDate(h.validTo)}` : "Not yet parsed"}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{statusLabels[h.status] ?? h.status}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{sourceLabels[h.source] ?? h.source}</TableCell>
              <TableCell className="text-sm text-muted-foreground">{formatDateTime(h.receivedAt)}</TableCell>
              <TableCell><DocumentEvidenceChip document={h.document} label="Certificate" /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
