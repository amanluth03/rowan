import { NextResponse } from "next/server";
import { API_BASE, getOrgId } from "@/lib/api/config";
import { isValidDocumentId } from "@/lib/api/document-id";

/**
 * Proxies `GET /api/v1/documents/{documentId}/download` (backend's hardened
 * evidence-download route, see backend/README.md's "Fixed by security
 * review" #3) so `DocumentRef.url` resolves to something a browser can
 * actually load.
 *
 * Why this proxy exists at all: the backend's download route (a) lives on a
 * different origin/port than this app in dev, and (b) requires the
 * `X-Rowan-Org-Id` dev-auth-stub header -- a plain `<a href>` straight to the
 * backend can supply neither. This route runs server-side, so it can hold
 * the org header the same way `lib/api/client.ts` does, and streams the
 * response straight through.
 *
 * SECURITY (carries forward the watch-item from the prior chunk's review):
 * this handler forwards the backend's OWN response `Content-Type` /
 * `Content-Disposition` headers verbatim -- those are already derived
 * server-side from the guardrail-detected file extension, never from
 * `coi_documents.content_type` (the attacker-controlled inbound MIME
 * string; see `app/api/reads.py::_safe_media_type`'s docstring). This route
 * never reads or trusts `DocumentRef.contentType` (the wire DTO field) for
 * anything -- it isn't even in scope here. `X-Content-Type-Options: nosniff`
 * is re-asserted defensively in case a future change to this handler drops
 * the passthrough, and a `Content-Disposition: attachment` fallback is set
 * in case upstream ever omits its own (defense in depth; upstream always
 * sets one today).
 *
 * SECURITY (BLOCK, fixed 2026-07-18, security-reviewer): `documentId` is a
 * raw, attacker-influenceable route param -- prior to this fix it was
 * interpolated straight into the upstream URL with no shape validation, so
 * a value like ".." resolved `${API_BASE}/api/v1/documents/../download` ->
 * `${API_BASE}/api/v1/download`, escaping the one request shape this proxy
 * is meant to forward while still attaching the trusted, server-side-only
 * org header to wherever that escaped. Validated against the UUID shape
 * every real document id has (ADR 0001) before it ever reaches `fetch()` --
 * see `isValidDocumentId`'s docstring for the full rationale and
 * `document-id.test.ts` for the regression test. `encodeURIComponent` below
 * is redundant after that guard (a validated UUID has nothing to encode)
 * but kept as belt-and-suspenders, documenting intent at the interpolation
 * site itself.
 */
export async function GET(_request: Request, { params }: { params: Promise<{ documentId: string }> }) {
  const { documentId } = await params;

  if (!isValidDocumentId(documentId)) {
    return NextResponse.json({ detail: "invalid document id" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/v1/documents/${encodeURIComponent(documentId)}/download`, {
    headers: { "X-Rowan-Org-Id": getOrgId() },
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json(
      { detail: upstream.status === 404 ? "document not found" : "failed to fetch document" },
      { status: upstream.status === 404 ? 404 : 502 },
    );
  }

  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  const contentDisposition = upstream.headers.get("content-disposition");
  if (contentType) headers.set("Content-Type", contentType);
  headers.set("Content-Disposition", contentDisposition ?? "attachment");
  headers.set("X-Content-Type-Options", "nosniff");

  return new NextResponse(upstream.body, { status: 200, headers });
}
