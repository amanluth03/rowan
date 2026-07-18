import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
      <p className="text-sm font-medium text-muted-foreground">Not found</p>
      <h1 className="text-lg font-semibold">We couldn&apos;t find that.</h1>
      <p className="max-w-sm text-sm text-muted-foreground">
        The vendor or run you&apos;re looking for doesn&apos;t exist, or has been removed from this demo dataset.
      </p>
      <Button asChild size="sm" className="mt-2">
        <Link href="/">Back to activity</Link>
      </Button>
    </div>
  );
}
