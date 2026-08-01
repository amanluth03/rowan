/**
 * Auth screens sit outside the app shell -- no nav, no sidebar. Calm and
 * plain, per CLAUDE.md's brand section: "competent operations person," not
 * a marketing splash.
 */

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-xl font-semibold tracking-tight">Rowan</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Vendor compliance, handled.
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}
