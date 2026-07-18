import Link from "next/link";
import { UserPlus } from "lucide-react";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { VendorListClient } from "@/components/vendors/vendor-list-client";
import { getVendorList } from "@/lib/api/read-models";

export const dynamic = "force-dynamic";

export default async function VendorsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string }>;
}) {
  const [vendors, { status }] = await Promise.all([getVendorList(), searchParams]);

  return (
    <>
      <PageHeader
        title="Vendors"
        description="Every vendor Rowan is tracking, with coverage status and requirements."
        actions={
          <Button asChild size="sm">
            <Link href="/onboarding">
              <UserPlus className="size-4" />
              Add vendor
            </Link>
          </Button>
        }
      />
      <VendorListClient vendors={vendors} initialStatus={status} />
    </>
  );
}
