/**
 * Frontend API client error contract tests.
 *
 * Verifies that ApiError exposes the typed `code` field parsed from the
 * backend's `{ error: { code, message } }` envelope, and that unknown codes
 * are preserved as-is.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the auth modules before importing the client so they don't try to
// touch localStorage in the jsdom environment.
vi.mock("@/lib/learner-auth", () => ({ getStoredProfile: () => null }));
vi.mock("@/lib/operator-auth", () => ({ getStoredOperatorKey: () => null }));

function mockFetchResponse(status: number, body: unknown): void {
  const response = new Response(JSON.stringify(body), { status });
  vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
}

async function expectApiError(
  fn: () => Promise<unknown>,
): Promise<{ status: number; code: string; message: string }> {
  // Attach the rejection handler synchronously so the unhandled-rejection
  // event does not fire before vitest has a chance to observe it.
  const caught = fn().then(
    () => {
      throw new Error("expected ApiError but promise resolved");
    },
    (err: unknown) => err as { status: number; code: string; message: string },
  );
  await vi.runAllTimersAsync();
  return caught;
}

describe("ApiError", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("parses backend error envelope into code + message", async () => {
    mockFetchResponse(503, {
      error: { code: "circuit_open", message: "LLM provider circuit breaker is open." },
    });

    const { get } = await import("@/api/client");
    const err = await expectApiError(() => get("/some/path"));

    expect(err).toMatchObject({
      name: "ApiError",
      status: 503,
      code: "circuit_open",
      message: "LLM provider circuit breaker is open.",
    });
  });

  it("falls back to service_unavailable when envelope is missing", async () => {
    mockFetchResponse(500, { detail: "internal error" });

    const { get } = await import("@/api/client");
    const err = await expectApiError(() => get("/some/path"));

    expect(err).toMatchObject({
      name: "ApiError",
      status: 500,
      code: "service_unavailable",
    });
  });

  it("preserves unknown codes for forward compatibility", async () => {
    mockFetchResponse(503, {
      error: { code: "provider_budget_exhausted", message: "daily budget reached" },
    });

    const { get } = await import("@/api/client");
    const err = await expectApiError(() => get("/some/path"));

    expect(err).toMatchObject({
      code: "provider_budget_exhausted",
      message: "daily budget reached",
    });
  });

  it("rate_limit_exceeded is surfaced with its code", async () => {
    mockFetchResponse(429, {
      error: { code: "rate_limit_exceeded", message: "Too many requests." },
    });

    const { post } = await import("@/api/client");
    const err = await expectApiError(() => post("/some/path", { data: 1 }));

    expect(err).toMatchObject({
      status: 429,
      code: "rate_limit_exceeded",
    });
  });

  it("constructor defaults code to service_unavailable", async () => {
    const { ApiError } = await import("@/api/client");
    const err = new ApiError(500, "oops");
    expect(err.code).toBe("service_unavailable");
    expect(err.status).toBe(500);
    expect(err.message).toBe("oops");
  });
});
