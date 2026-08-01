import { redirect } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { InviteForm } from "@/components/settings/invite-form";
import { RevokeInvitationButton } from "@/components/settings/revoke-invitation-button";
import { getMe, getPendingInvitations } from "@/lib/api/read-models";
import { formatDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TeamSettingsPage() {
  const me = await getMe();
  // Cosmetic guard only -- the backend's `require_role(Command.invite_user |
  // list_invitations | revoke_invitation)` (app/api/deps.py) returns 403 for
  // an assistant regardless of this redirect. This just avoids showing a
  // page whose every action would fail, for someone who isn't malicious --
  // it is not, and must never be treated as, the security boundary.
  if (me.role !== "owner") redirect("/");

  const invitations = await getPendingInvitations();

  return (
    <>
      <PageHeader
        title="Team"
        description="Assistants can see everything and keep renewals moving. Changing coverage requirements and approving certificates stay with you."
      />

      <div className="mx-auto w-full max-w-2xl space-y-8 p-6">
        <InviteForm />

        <section className="space-y-3">
          <h2 className="text-sm font-medium">Pending invitations</h2>
          {invitations.length === 0 ? (
            <p className="text-sm text-muted-foreground">No pending invitations.</p>
          ) : (
            <ul className="divide-y rounded-md border border-border" data-testid="pending-invitations">
              {invitations.map((invite) => (
                <li key={invite.id} className="flex items-center justify-between px-4 py-3" data-testid="pending-invitation">
                  <div>
                    <p className="text-sm">{invite.email}</p>
                    <p className="text-xs text-muted-foreground">Expires {formatDate(invite.expiresAt)}</p>
                  </div>
                  <RevokeInvitationButton invitationId={invite.id} email={invite.email} />
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
