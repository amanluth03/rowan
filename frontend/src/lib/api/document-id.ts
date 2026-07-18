/**
 * Backend document ids are UUID (v7, per ADR 0001's "Cross-cutting
 * conventions: IDs ... UUID v7 (time-sortable) primary keys"). Validating a
 * route param against this shape BEFORE it's interpolated into the upstream
 * proxy URL closes a confused-deputy / path-traversal risk flagged at
 * security review (2026-07-18, BLOCK):
 *
 * An unvalidated `documentId` of `".."` would resolve
 * `${API_BASE}/api/v1/documents/../download` -> `${API_BASE}/api/v1/download`
 * -- the param escapes the one request shape
 * `app/api/documents/[documentId]/route.ts` is meant to forward, and the
 * proxy would still attach the trusted, server-side-only org header to
 * whatever that resolves to. Low severity today (fixed host, same-org reads
 * only, single-org dev-auth stub) but a real confused-deputy risk once
 * per-session auth replaces that stub.
 *
 * Kept as a standalone, dependency-free function (no Next.js imports) so it
 * can be unit-tested directly -- see `document-id.test.ts`.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isValidDocumentId(value: string): boolean {
  return UUID_RE.test(value);
}
