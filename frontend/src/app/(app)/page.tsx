import { PageHeader } from "@/components/layout/page-header";
import { PortfolioSnapshotStrip } from "@/components/activity/portfolio-snapshot";
import { ActivityFeedItem } from "@/components/activity/activity-feed-item";
import { getActivityFeed, getPortfolioSnapshot } from "@/lib/mock/read-models";

export default async function HomePage() {
  const [feed, snapshot] = await Promise.all([getActivityFeed(), getPortfolioSnapshot()]);
  const actionable = feed.filter((f) => f.actionRequired);

  return (
    <>
      <PageHeader
        title="Activity"
        description="What Rowan has been doing across your portfolio, most recent first."
      />
      <PortfolioSnapshotStrip snapshot={snapshot} />

      <div className="flex-1">
        {actionable.length > 0 ? (
          <div className="border-b border-border bg-amber-50/40 px-6 py-3 dark:bg-amber-950/10">
            <p className="text-sm font-medium text-amber-800 dark:text-amber-400">
              {actionable.length} item{actionable.length === 1 ? "" : "s"} need{actionable.length === 1 ? "s" : ""} you — look for the highlighted rows below, or head to the{" "}
              <a href="/review" className="underline underline-offset-2">review queue</a>.
            </p>
          </div>
        ) : null}
        <ul>
          {feed.map((item) => (
            <ActivityFeedItem key={item.id} item={item} />
          ))}
        </ul>
      </div>
    </>
  );
}
