import { createHttpClient } from "@wealth/shared";
import { describe, expect, it, vi } from "vitest";

function fakeFetch(body: unknown, status = 200): typeof fetch {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as typeof fetch;
}

describe("createHttpClient", () => {
  it("calls onUnauthorized when the envelope reports a 401 business code", async () => {
    const onUnauthorized = vi.fn();
    const http = createHttpClient({
      baseUrl: "",
      fetchImpl: fakeFetch(
        { code: 401, message: "凭证无效或已过期", data: null, trace_id: "trace-1" },
        401,
      ),
      onUnauthorized,
    });

    await expect(http.get("/api/customer/auth/me")).rejects.toThrow();

    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("does not call onUnauthorized on a successful response", async () => {
    const onUnauthorized = vi.fn();
    const http = createHttpClient({
      baseUrl: "",
      fetchImpl: fakeFetch({ code: 200, message: "success", data: { ok: true }, trace_id: "trace-2" }),
      onUnauthorized,
    });

    await http.get("/api/health");

    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("attaches a bearer token from getToken when one is present", async () => {
    const fetchImpl = fakeFetch({ code: 200, message: "success", data: null, trace_id: "t" });
    const http = createHttpClient({
      baseUrl: "",
      fetchImpl,
      getToken: () => "the-token",
    });

    await http.get("/api/customer/auth/me");

    const [, init] = vi.mocked(fetchImpl).mock.calls[0];
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer the-token");
  });
});
