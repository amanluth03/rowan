/**
 * The client sends a bearer token and NEVER an org header. The negative
 * assertion is the important one: X-Rowan-Org-Id was an authentication
 * bypass, and leaving it in place "just in case" would preserve the bypass.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/auth/session", () => ({
  getSession: vi.fn(async () => ({
    accessToken: "test-token-123",
    user: { id: "u1", email: "dana@example.com" },
  })),
}));

afterEach(() => vi.restoreAllMocks());

describe("apiFetch", () => {
  it("sends the bearer token and no org header", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const { apiFetch } = await import("./client");
    await apiFetch("/api/v1/vendors");

    const call = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(call[1].headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer test-token-123");
    expect(headers.get("X-Rowan-Org-Id")).toBeNull();
  });

  it("throws when there is no session rather than sending an anonymous request", async () => {
    const { getSession } = await import("@/lib/auth/session");
    vi.mocked(getSession).mockResolvedValueOnce(null);
    vi.stubGlobal("fetch", vi.fn());

    const { apiFetch } = await import("./client");
    await expect(apiFetch("/api/v1/vendors")).rejects.toThrow(/not authenticated/i);
  });

  it("maps a 404 to null via apiFetchOrNull", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "nope" }), { status: 404 })),
    );
    const { apiFetchOrNull } = await import("./client");
    expect(await apiFetchOrNull("/api/v1/vendors/xyz")).toBeNull();
  });
});
