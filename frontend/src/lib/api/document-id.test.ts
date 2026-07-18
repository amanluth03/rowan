import { describe, expect, it } from "vitest";
import { isValidDocumentId } from "./document-id";

/**
 * Regression test for the security-reviewer BLOCK (2026-07-18): the
 * `app/api/documents/[documentId]/route.ts` proxy must never forward a
 * `documentId` route param that isn't a real UUID -- a traversal payload
 * like ".." would otherwise escape the intended
 * `/api/v1/documents/{id}/download` request shape (and carry the trusted
 * org header along with it). See `document-id.ts`'s docstring for the full
 * confused-deputy rationale.
 */
describe("isValidDocumentId", () => {
  it("accepts a real UUID v7 document id", () => {
    expect(isValidDocumentId("019f76cf-bb77-7b43-986d-eefe47557f73")).toBe(true);
  });

  it("accepts uppercase UUIDs", () => {
    expect(isValidDocumentId("019F76CF-BB77-7B43-986D-EEFE47557F73")).toBe(true);
  });

  it("rejects a path-traversal payload", () => {
    expect(isValidDocumentId("..")).toBe(false);
  });

  it("rejects a path-traversal payload with a nested escape", () => {
    expect(isValidDocumentId("../../etc/passwd")).toBe(false);
  });

  it("rejects a UUID with a traversal segment smuggled after it", () => {
    expect(isValidDocumentId("019f76cf-bb77-7b43-986d-eefe47557f73/../../download")).toBe(false);
  });

  it("rejects an encoded traversal payload", () => {
    expect(isValidDocumentId("%2e%2e%2f%2e%2e")).toBe(false);
  });

  it("rejects an empty string", () => {
    expect(isValidDocumentId("")).toBe(false);
  });

  it("rejects a non-UUID identifier", () => {
    expect(isValidDocumentId("not-a-uuid")).toBe(false);
  });

  it("rejects a UUID missing a segment", () => {
    expect(isValidDocumentId("019f76cf-bb77-7b43-986d")).toBe(false);
  });
});
