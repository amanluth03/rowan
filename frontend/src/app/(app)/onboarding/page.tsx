import { PageHeader } from "@/components/layout/page-header";
import { OnboardingFlow } from "@/components/onboarding/onboarding-flow";
import { getPropertyOptions, getVendorList } from "@/lib/api/read-models";

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const [properties, vendors] = await Promise.all([getPropertyOptions(), getVendorList()]);

  return (
    <>
      <PageHeader
        title="Onboarding"
        description="Add vendors, set what coverage they need to carry, and bring in certificates you already have."
      />
      <div className="p-6">
        <OnboardingFlow properties={properties} initialVendors={vendors.map((v) => ({ id: v.id, name: v.name }))} />
      </div>
    </>
  );
}
