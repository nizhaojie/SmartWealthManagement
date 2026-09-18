// 身份域隔离（ADR-0009 护栏 2 在前端的落点）：
// 客户端的令牌只来自 wealth-customer-auth，不会捡到 internal 身份域的令牌；
// 401 被当作会话失效，清掉本地令牌。
import { beforeEach, describe, expect, it, vi } from "vitest";

// fetch 在 createHttpClient 创建实例时就被捕获，因此桩必须在 import 之前装好。
const fetchMock = vi.hoisted(() => {
  const fn = vi.fn();
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
});

import { clearTokens, getAccessToken, setTokens } from "../auth/tokenStore";
import { currentUsername, rememberUsername } from "../auth/username";
import { http } from "./http";

function envelope(code: number, message: string) {
  return { code, message, data: null, trace_id: "trace-1" };
}

describe("customer http client", () => {
  beforeEach(() => {
    localStorage.clear();
    clearTokens();
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => envelope(200, "success"),
    });
  });

  it("reads its bearer token from the customer key only", async () => {
    // 另一个身份域的令牌摆在同一个 localStorage 里，客户端必须视而不见。
    localStorage.setItem(
      "wealth-internal-auth",
      JSON.stringify({ accessToken: "employee-token", refreshToken: "r" }),
    );
    setTokens({ accessToken: "customer-token", refreshToken: "r" });

    await http.get("/api/customer/assets");

    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer customer-token");
  });

  it("does not pick up an internal-domain token on a fresh load", async () => {
    localStorage.setItem(
      "wealth-internal-auth",
      JSON.stringify({ accessToken: "employee-token", refreshToken: "r" }),
    );
    vi.resetModules();

    const freshStore = await import("../auth/tokenStore");

    expect(freshStore.getAccessToken()).toBeNull();
  });

  it("treats a 401 as an expired session and clears the stored tokens", async () => {
    setTokens({ accessToken: "expired-token", refreshToken: "r" });
    rememberUsername("wangc1");
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => envelope(401, "凭证无效或已过期"),
    });

    await expect(http.get("/api/customer/assets")).rejects.toThrow("凭证无效或已过期");

    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("wealth-customer-auth")).toBeNull();
    // 顶栏展示名与令牌同生同灭，会话失效时也一并清掉。
    expect(currentUsername.value).toBe("");
  });
});
