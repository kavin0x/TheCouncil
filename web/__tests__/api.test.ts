import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "@/lib/api";

const TOKEN = "test_token";

function mockFetch(data: unknown, status = 200) {
  return vi.spyOn(global, "fetch").mockResolvedValueOnce({
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    json: async () => data,
  } as Response);
}

describe("api.getEntitlements", () => {
  afterEach(() => vi.restoreAllMocks());

  it("calls /me/entitlements with Bearer token", async () => {
    const spy = mockFetch({ tier: "pro", display_name: "Pro", limits: {}, features: {} });
    await api.getEntitlements(TOKEN);
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("/me/entitlements"),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${TOKEN}`,
        }),
      })
    );
  });
});

describe("api.listRuns", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns an array of runs", async () => {
    mockFetch([{ run_id: "abc", question: "Q?", status: "completed", created_at: 0 }]);
    const runs = await api.listRuns(TOKEN);
    expect(Array.isArray(runs)).toBe(true);
    expect(runs[0].run_id).toBe("abc");
  });
});

describe("api.createRun", () => {
  afterEach(() => vi.restoreAllMocks());

  it("posts to /runs with question", async () => {
    const spy = mockFetch({ run_id: "xyz", question: "Test?", status: "pending", created_at: 0 }, 202);
    const run = await api.createRun(TOKEN, { question: "Test?" });
    expect(spy).toHaveBeenCalledWith(
      expect.stringContaining("/runs"),
      expect.objectContaining({ method: "POST" })
    );
    expect(run.run_id).toBe("xyz");
  });

  it("throws on 429 with correct status", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: async () => ({ detail: "Monthly run limit reached" }),
    } as Response);
    await expect(api.createRun(TOKEN, { question: "Q" })).rejects.toMatchObject({
      status: 429,
    });
  });
});

describe("api.deletePersona", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends DELETE and returns undefined for 204", async () => {
    vi.spyOn(global, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 204,
      json: async () => null,
    } as Response);
    const result = await api.deletePersona(TOKEN, "persona-id");
    expect(result).toBeUndefined();
  });
});
