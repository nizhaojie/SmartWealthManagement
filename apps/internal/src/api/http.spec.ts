// 身份域隔离（ADR-0009 护栏 2）在 internal 这一侧的落点：
// 内部客户端的 Bearer 只能来自 `wealth-internal-auth`。
// 客户域的令牌即使躺在同一个 localStorage 里，也不得被带上任何一个请求。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http } from "./http";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { stubApiFetch } from "../testing";

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
});
