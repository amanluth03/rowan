"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { addVendorAction } from "@/app/actions";
import type { PropertyOption } from "@/lib/mock/read-models";
import type { VendorRole } from "@/lib/types";
import { formatVendorRole } from "@/lib/format";

const ROLES: VendorRole[] = [
  "plumber",
  "electrician",
  "hvac",
  "general_contractor",
  "landscaper",
  "roofer",
  "cleaner",
  "pest_control",
  "other",
];

export function AddVendorForm({
  properties,
  onAdded,
}: {
  properties: PropertyOption[];
  onAdded: (vendorId: string, vendorName: string) => void;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<VendorRole | "">("");
  const [propertyId, setPropertyId] = useState(properties[0]?.id ?? "");
  const [notes, setNotes] = useState("");
  const [isPending, startTransition] = useTransition();

  const canSubmit = name.trim().length > 0 && role !== "" && propertyId !== "";

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!canSubmit) return;
        startTransition(async () => {
          const result = await addVendorAction({
            name: name.trim(),
            primaryEmail: email.trim(),
            vendorRole: role,
            primaryPropertyId: propertyId,
            notes: notes.trim() || undefined,
          });
          toast(result.message);
          if (result.ok && result.data) {
            onAdded(result.data.vendorId, name.trim());
            setName("");
            setEmail("");
            setRole("");
            setNotes("");
          }
        });
      }}
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="vendor-name">Vendor name</Label>
          <Input id="vendor-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hernandez Plumbing" required />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="vendor-email">Primary email</Label>
          <Input id="vendor-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="office@vendor.example" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="vendor-role">Trade</Label>
          <Select value={role} onValueChange={(v) => setRole(v as VendorRole)}>
            <SelectTrigger id="vendor-role" className="w-full">
              <SelectValue placeholder="Select a trade" />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map((r) => (
                <SelectItem key={r} value={r}>{formatVendorRole(r)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="vendor-property">Primary property</Label>
          <Select value={propertyId} onValueChange={setPropertyId}>
            <SelectTrigger id="vendor-property" className="w-full">
              <SelectValue placeholder="Select a property" />
            </SelectTrigger>
            <SelectContent>
              {properties.map((p) => (
                <SelectItem key={p.id} value={p.id}>{p.name} — {p.jurisdiction}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">Resolves the jurisdiction Rowan uses to look up requirements.</p>
        </div>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="vendor-notes">Notes (optional)</Label>
        <Textarea id="vendor-notes" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Anything Dana should remember about this vendor." />
      </div>
      <Button type="submit" disabled={!canSubmit || isPending}>
        <UserPlus className="size-4" />
        Add vendor
      </Button>
    </form>
  );
}
