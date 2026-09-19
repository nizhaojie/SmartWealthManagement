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

import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "../auth/tokenStore";
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

  // access token 只有 15 分钟。过期不是会话结束：拿 refresh token 换一张再重发，
  // 否则「登录后过一会就退回登录页」正是这条路径的必然结果。
  it("access token 过期时用 refresh token 续期并重发原请求", async () => {
    setTokens({ accessToken: "expired-token", refreshToken: "refresh-1" });
    rememberUsername("wangc1");
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/customer/auth/refresh")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            code: 200,
            message: "success",
            data: { access_token: "fresh-token", token_type: "bearer", expires_in: 900 },
            trace_id: "trace-1",
          }),
        };
      }
      const headers = (init?.headers ?? {}) as Record<string, string>;
      return headers.Authorization === "Bearer fresh-token"
        ? { ok: true, status: 200, json: async () => envelope(200, "success") }
        : { ok: false, status: 401, json: async () => envelope(401, "凭证无效或已过期") };
    });

    await expect(http.get("/api/customer/assets")).resolves.toBeNull();

    const urls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(urls.filter((url) => url.includes("/api/customer/auth/refresh"))).toHaveLength(1);
    expect(urls.filter((url) => url.includes("/api/customer/assets"))).toHaveLength(2);

    const refreshCall = fetchMock.mock.calls.find(([input]) =>
      String(input).includes("/api/customer/auth/refresh"),
    );
    expect(JSON.parse((refreshCall?.[1] as RequestInit).body as string)).toEqual({
      refresh_token: "refresh-1",
    });
    // 只换 access token，refresh token 原样留着，下次过期还能续。
    expect(getAccessToken()).toBe("fresh-token");
    expect(getRefreshToken()).toBe("refresh-1");
    // 会话没失效，展示名不该被清掉。
    expect(currentUsername.value).toBe("wangc1");
  });

  it("续期也换不到令牌时才清会话", async () => {
    setTokens({ accessToken: "expired-token", refreshToken: "stale-refresh" });
    rememberUsername("wangc1");
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const message = String(input).includes("/api/customer/auth/refresh")
        ? "刷新凭证无效或已过期"
        : "凭证无效或已过期";
      return { ok: false, status: 401, json: async () => envelope(401, message) };
    });

    await expect(http.get("/api/customer/assets")).rejects.toThrow("凭证无效或已过期");

    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("wealth-customer-auth")).toBeNull();
    expect(currentUsername.value).toBe("");
    // 续期失败就收手：一次续期 + 一次原请求重发之前的那次，不再追问。
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
