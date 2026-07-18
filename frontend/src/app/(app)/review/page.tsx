import { PageHeader } from "@/components/layout/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReviewItemCard } from "@/components/review/review-item-card";
import { getReviewQueue } from "@/lib/mock/read-models";
import { Inbox } from "lucide-react";

export default async function ReviewQueuePage() {
  const items = await getReviewQueue();
  const needsReview = items.filter((i) => i.kind === "needs_human_review");
  const escalated = items.filter((i) => i.kind === "escalated_to_pm");

  return (
    <>
      <PageHeader
        title="Review queue"
        description="Rowan holds anything that fails validation, comes back uncertain, or hits a wall — nothing here was auto-approved."
      />

      <div className="p-6">
        {items.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-border py-16 text-center">
            <Inbox className="size-6 text-muted-foreground" />
            <p className="text-sm font-medium">Queue is empty</p>
            <p className="text-sm text-muted-foreground">Nothing needs you right now — Rowan is monitoring the rest of the portfolio.</p>
          </div>
        ) : (
          <Tabs defaultValue="needs_review">
            <TabsList>
              <TabsTrigger value="needs_review" data-testid="tab-needs-review">Needs your review ({needsReview.length})</TabsTrigger>
              <TabsTrigger value="escalated" data-testid="tab-escalated">Escalated ({escalated.length})</TabsTrigger>
            </TabsList>
            <TabsContent value="needs_review" className="mt-4 flex flex-col gap-4">
              {needsReview.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Nothing waiting on a coverage decision.</p>
              ) : (
                needsReview.map((item) => <ReviewItemCard key={item.escalationId} item={item} />)
              )}
            </TabsContent>
            <TabsContent value="escalated" className="mt-4 flex flex-col gap-4">
              {escalated.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">Nothing escalated to you right now.</p>
              ) : (
                escalated.map((item) => <ReviewItemCard key={item.escalationId} item={item} />)
              )}
            </TabsContent>
          </Tabs>
        )}
      </div>
    </>
  );
}
