// access token 只有 15 分钟，过期不该把人踢下线：401 先续期、重发一次，续不到才算失效。
// 这里只测这条分岔，不测信封拆包（那由各应用的 http 客户端用例覆盖）。
import { describe, expect, it, vi } from "vitest";
import { ApiError, createHttpClient, type HttpClientOptions } from "./http";

type EnvelopeLike = {
  code: number;
  message: string;
  data: unknown;
  trace_id: string;
};

function envelope(code: number, data: unknown = null, message = "ok"): EnvelopeLike {
  return { code, message, data, trace_id: "trace-1" };
}

function response(code: number, data: unknown = null, message = "ok"): Response {
  return {
    ok: code === 200,
    status: code,
    json: async () => envelope(code, data, message),
  } as unknown as Response;
}

function authorizationOf(init?: RequestInit): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

/** 记下每次请求带的 Authorization，按它决定回 401 还是 200。 */
function tokenAwareFetch() {
  const calls: (string | undefined)[] = [];
  const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const authorization = authorizationOf(init);
    calls.push(authorization);
    return authorization === "Bearer fresh"
      ? response(200, { ok: true })
      : response(401, null, "凭证无效或已过期");
  });
  return { fetchImpl, calls };
}

function clientWith(
  fetchImpl: ReturnType<typeof tokenAwareFetch>["fetchImpl"],
  extra: Partial<HttpClientOptions> = {},
) {
  return createHttpClient({
    baseUrl: "http://api",
    fetchImpl: fetchImpl as unknown as typeof fetch,
    ...extra,
  });
}

describe("createHttpClient 的会话续期", () => {
  it("access token 过期时先续期，再用新令牌重发一次原请求", async () => {
    let token = "expired";
    const { fetchImpl, calls } = tokenAwareFetch();
    const renewTokens = vi.fn(async () => {
      token = "fresh";
      return true;
    });
    const onUnauthorized = vi.fn();
    const http = clientWith(fetchImpl, { getToken: () => token, renewTokens, onUnauthorized });

    await expect(http.get("/things")).resolves.toEqual({ ok: true });

    expect(renewTokens).toHaveBeenCalledTimes(1);
    expect(calls).toEqual(["Bearer expired", "Bearer fresh"]);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("续期失败才算会话失效：不重发，交给 onUnauthorized", async () => {
    const fetchImpl = vi.fn(async () => response(401, null, "凭证无效或已过期"));
    const renewTokens = vi.fn(async () => false);
    const onUnauthorized = vi.fn();
    const http = clientWith(fetchImpl, { getToken: () => "expired", renewTokens, onUnauthorized });

    await expect(http.get("/things")).rejects.toThrow("凭证无效或已过期");

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(renewTokens).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("重发后还是 401 就收手，不再续期（避免两边互相不认时转圈）", async () => {
    const fetchImpl = vi.fn(async () => response(401));
    const renewTokens = vi.fn(async () => true);
    const onUnauthorized = vi.fn();
    const http = clientWith(fetchImpl, { getToken: () => "expired", renewTokens, onUnauthorized });

    await expect(http.get("/things")).rejects.toBeInstanceOf(ApiError);

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(renewTokens).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("首屏并发请求一起撞上 401 时只续期一次", async () => {
    let token = "expired";
    const { fetchImpl } = tokenAwareFetch();
    const renewTokens = vi.fn(async () => {
      // 让在途状态真实存在：没有单飞的话三个请求会各续一次。
      await Promise.resolve();
      token = "fresh";
      return true;
    });
    const http = clientWith(fetchImpl, { getToken: () => token, renewTokens });

    const results = await Promise.all([http.get("/a"), http.get("/b"), http.get("/c")]);

    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(renewTokens).toHaveBeenCalledTimes(1);
    expect(fetchImpl).toHaveBeenCalledTimes(6);
  });

  it("没有续期钩子时，401 的处理与从前一致", async () => {
    const fetchImpl = vi.fn(async () => response(401, null, "凭证无效或已过期"));
    const onUnauthorized = vi.fn();
    const http = clientWith(fetchImpl, { getToken: () => "token", onUnauthorized });

    await expect(http.get("/things")).rejects.toThrow("凭证无效或已过期");

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("非 401 的失败不触发续期", async () => {
    const fetchImpl = vi.fn(async () => response(500, null, "服务内部错误"));
    const renewTokens = vi.fn(async () => true);
    const http = clientWith(fetchImpl, { getToken: () => "token", renewTokens });

    await expect(http.get("/things")).rejects.toThrow("服务内部错误");

    expect(renewTokens).not.toHaveBeenCalled();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});
