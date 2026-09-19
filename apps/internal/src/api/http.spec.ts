// 身份域隔离（ADR-0009 护栏 2）在 internal 这一侧的落点：
// 内部客户端的 Bearer 只能来自 `wealth-internal-auth`。
// 客户域的令牌即使躺在同一个 localStorage 里，也不得被带上任何一个请求。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./http";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "../auth/tokenStore";
import { apiError, requestedUrls, stubApiFetch } from "../testing";

let fetchMock: ReturnType<typeof stubApiFetch>;

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(
    "wealth-customer-auth",
    JSON.stringify({ accessToken: "customer-token", refreshToken: "customer-refresh" }),
  );
  setTokens({ accessToken: "internal-token", refreshToken: "internal-refresh" });
  fetchMock = stubApiFetch(() => ({ ok: true }));
});

afterEach(() => {
  clearTokens();
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("内部身份域的 http 客户端", () => {
  it("只发内部域的令牌，不碰同机上的客户域令牌", async () => {
    await http.get("/api/internal/example");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer internal-token");
    expect(JSON.stringify(headers)).not.toContain("customer-token");
  });

  it("没有内部令牌时不带 Authorization 头", async () => {
    clearTokens();

    await http.get("/api/internal/example");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });

  // access token 只有 15 分钟。过期不是会话结束：换一张再重发，
  // 深链进来时守卫里的 /auth/me 也走这条路，否则刷新页面就被送回登录页。
  it("access token 过期时用 refresh token 续期并重发原请求", async () => {
    fetchMock = stubApiFetch((url, init) => {
      // 与其它用例一致：responder 返回的是 data，信封由 stubApiFetch 补齐。
      if (url.includes("/api/internal/auth/refresh")) {
        return { access_token: "fresh-internal-token", token_type: "bearer", expires_in: 900 };
      }
      const headers = (init?.headers ?? {}) as Record<string, string>;
      return headers.Authorization === "Bearer fresh-internal-token"
        ? { ok: true }
        : apiError(401, "凭证无效或已过期");
    });

    await http.get("/api/internal/example");

    expect(requestedUrls(fetchMock, "/api/internal/auth/refresh")).toHaveLength(1);
    expect(requestedUrls(fetchMock, "/api/internal/example")).toHaveLength(2);
    // 只换 access token，refresh token 原样留着，下次过期还能续。
    expect(getAccessToken()).toBe("fresh-internal-token");
    expect(getRefreshToken()).toBe("internal-refresh");
  });
});
