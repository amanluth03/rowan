"use client";

import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AddVendorForm } from "./add-vendor-form";
import { RequirementsBuilder } from "./requirements-builder";
import { ImportCoiDropzone } from "./import-coi-dropzone";
import type { PropertyOption } from "@/lib/api/read-models";

interface VendorOption {
  id: string;
  name: string;
}

export function OnboardingFlow({
  properties,
  initialVendors,
}: {
  properties: PropertyOption[];
  initialVendors: VendorOption[];
}) {
  const [vendors, setVendors] = useState<VendorOption[]>(initialVendors);
  const [selectedVendorId, setSelectedVendorId] = useState<string>(initialVendors[0]?.id ?? "");
  const [tab, setTab] = useState("add-vendor");

  const selectedVendor = vendors.find((v) => v.id === selectedVendorId) ?? null;

  return (
    <Tabs value={tab} onValueChange={setTab} className="gap-6">
      <TabsList>
        <TabsTrigger value="add-vendor">1. Add vendor</TabsTrigger>
        <TabsTrigger value="requirements">2. Coverage requirements</TabsTrigger>
        <TabsTrigger value="import">3. Import certificate</TabsTrigger>
      </TabsList>

      <TabsContent value="add-vendor">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Add a vendor</CardTitle>
            <CardDescription>Rowan tracks renewals per vendor, resolved to a primary property for jurisdiction.</CardDescription>
          </CardHeader>
          <CardContent>
            <AddVendorForm
              properties={properties}
              onAdded={(vendorId, vendorName) => {
                setVendors((prev) => [...prev, { id: vendorId, name: vendorName }]);
                setSelectedVendorId(vendorId);
                setTab("requirements");
              }}
            />
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="requirements">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Coverage requirements</CardTitle>
            <CardDescription>
              Rowan validates every renewal against these lines, all-or-nothing. Each line should trace to a verified source.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="max-w-xs space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Vendor</label>
              <Select value={selectedVendorId} onValueChange={setSelectedVendorId}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select a vendor" />
                </SelectTrigger>
                <SelectContent>
                  {vendors.map((v) => (
                    <SelectItem key={v.id} value={v.id}>{v.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {selectedVendor ? (
              <RequirementsBuilder vendorId={selectedVendor.id} vendorName={selectedVendor.name} />
            ) : (
              <p className="text-sm text-muted-foreground">Add a vendor first, or pick one above.</p>
            )}
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="import">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Import an existing certificate</CardTitle>
            <CardDescription>
              Already have a current COI on file for {selectedVendor ? selectedVendor.name : "a vendor"}? Upload it so Rowan starts from a known state instead of chasing a renewal it doesn&apos;t need to.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ImportCoiDropzone />
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  );
}
