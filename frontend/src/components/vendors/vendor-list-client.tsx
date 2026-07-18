"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ComplianceStatus, VendorStatusDTO } from "@/lib/types";
import { ComplianceStatusBadge, RunStateBadge } from "@/components/shared/status-badge";
import { formatDate, formatVendorRole } from "@/lib/format";
import { complianceStatusStyles } from "@/lib/status-styles";

const STATUS_ORDER: ComplianceStatus[] = ["escalated", "no_requirements", "needs_review", "expiring_soon", "pending", "compliant"];

export function VendorListClient({
  vendors,
  initialStatus,
}: {
  vendors: VendorStatusDTO[];
  initialStatus?: string;
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<string>(initialStatus && initialStatus in complianceStatusStyles ? initialStatus : "all");

  const filtered = useMemo(() => {
    return vendors
      .filter((v) => (status === "all" ? true : v.complianceStatus === status))
      .filter((v) => v.name.toLowerCase().includes(query.toLowerCase()) || formatVendorRole(v.role).toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => STATUS_ORDER.indexOf(a.complianceStatus) - STATUS_ORDER.indexOf(b.complianceStatus) || a.name.localeCompare(b.name));
  }, [vendors, query, status]);

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex flex-col gap-3 border-b border-border px-6 py-4 sm:flex-row sm:items-center">
        <div className="relative flex-1 sm:max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search vendors or trades…"
            className="pl-8"
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-full sm:w-56">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {STATUS_ORDER.map((s) => (
              <SelectItem key={s} value={s}>{complianceStatusStyles[s].label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-sm text-muted-foreground sm:ml-auto">{filtered.length} of {vendors.length} vendors</p>
      </div>

      <div className="flex-1 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Vendor</TableHead>
              <TableHead>Trade</TableHead>
              <TableHead>Property / jurisdiction</TableHead>
              <TableHead>Compliance</TableHead>
              <TableHead>Current COI</TableHead>
              <TableHead>Run state</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((v) => (
              <TableRow key={v.id} className="cursor-pointer">
                <TableCell className="font-medium">
                  <Link href={`/vendors/${v.id}`} className="hover:underline underline-offset-2">
                    {v.name}
                  </Link>
                  {v.primaryEmail ? <p className="text-xs font-normal text-muted-foreground">{v.primaryEmail}</p> : null}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">{formatVendorRole(v.role)}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {v.primaryPropertyName}
                  <p className="text-xs">{v.primaryPropertyJurisdiction}</p>
                </TableCell>
                <TableCell>
                  <ComplianceStatusBadge status={v.complianceStatus} />
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {v.currentCoi ? `Through ${formatDate(v.currentCoi.validTo)}` : "None on file"}
                </TableCell>
                <TableCell>
                  {v.activeRun ? <RunStateBadge state={v.activeRun.state} /> : <span className="text-sm text-muted-foreground">—</span>}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="py-10 text-center text-sm text-muted-foreground">
                  No vendors match this search.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
