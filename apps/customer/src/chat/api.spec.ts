// SSE 帧解析是客服链路的传输面：`event: done` 携带定案答案与引用，其余帧携带 delta，
// 异常必须走 onError 而不是抛出去。这里只测这三件事，不测页面渲染。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearTokens, getAccessToken, setTokens } from "../auth/tokenStore";
import { streamChatMessage } from "./api";

// 续期请求走的是全局 fetch（http 客户端自己那一份），不随 streamChatMessage 注入的
// fetchImpl 走。默认装一个「刷新凭证也已过期」的替身：任何用例都不会真的出网，
// 要验证续期成功的用例在用例内自带替身。
beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: false,
      status: 401,
      json: async () => ({
        code: 401,
        message: "刷新凭证无效或已过期",
        data: null,
        trace_id: "trace-1",
      }),
    })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearTokens();
});

function sseResponse(
  frames: string[],
  options: { ok?: boolean; body?: boolean; status?: number } = {},
): typeof fetch {
  let index = 0;
  const encoder = new TextEncoder();
  return vi.fn().mockResolvedValue({
    ok: options.ok ?? true,
    status: options.status ?? (options.ok === false ? 500 : 200),
    body:
      options.body === false
        ? null
        : {
            getReader() {
              return {
                async read() {
                  if (index < frames.length) {
                    return { done: false, value: encoder.encode(frames[index++]) };
                  }
                  return { done: true, value: undefined };
                },
              };
            },
          },
  }) as unknown as typeof fetch;
}

describe("streamChatMessage", () => {
  // 这是客户侧 SSE 契约第一次长出结构（ADR-0028）：`data_answer` 是一份嵌套载荷，
  // 用深度相等把它整个钉住——下一次有人往 `ChatResponse` 里静默加字段时，这条会红。
  it("emits deltas in order and the final structured payload on done", async () => {
    const fetchImpl = sseResponse([
      'data: {"delta":"为您查到"}\n\n',
      'data: {"delta":" 1 行数据"}\n\n',
      'event: done\ndata: {"answer":"为您查到 1 行数据，已列在下表。数据口径：我的持仓明细。","citations":[],"intent":"数据查询","content_classification":"事实性内容","data_answer":{"columns":[{"key":"product_name","label":"产品名称"},{"key":"market_value","label":"当前市值"}],"rows":[["稳健增利","120000.00"]],"row_count":1,"truncated":false,"views":["持仓明细"]}}\n\n',
    ]);

    const deltas: string[] = [];
    const done = vi.fn();
    await streamChatMessage(
      "我持有哪些产品",
      { onDelta: (delta) => deltas.push(delta), onDone: done, onError: vi.fn() },
      fetchImpl,
    );

    expect(deltas).toEqual(["为您查到", " 1 行数据"]);
    expect(done).toHaveBeenCalledWith({
      answer: "为您查到 1 行数据，已列在下表。数据口径：我的持仓明细。",
      citations: [],
      intent: "数据查询",
      content_classification: "事实性内容",
      data_answer: {
        columns: [
          { key: "product_name", label: "产品名称" },
          { key: "market_value", label: "当前市值" },
        ],
        rows: [["稳健增利", "120000.00"]],
        row_count: 1,
        truncated: false,
        views: ["持仓明细"],
      },
    });
  });

  it("reassembles a frame that arrives split across chunk boundaries", async () => {
    const fetchImpl = sseResponse([
      'data: {"del',
      'ta":"字"}\n\n',
      'event: done\ndata: {"answer":"字","citations":[],"intent":"FAQ","content_classification":"事实性内容"}\n\n',
    ]);

    const deltas: string[] = [];
    await streamChatMessage(
      "问题",
      { onDelta: (delta) => deltas.push(delta), onDone: vi.fn(), onError: vi.fn() },
      fetchImpl,
    );

    expect(deltas).toEqual(["字"]);
  });

  it("carries citations through the done frame", async () => {
    const fetchImpl = sseResponse([
      'event: done\ndata: {"answer":"最短持有期为九十天[1]。","citations":[{"knowledge_id":1,"chunk_index":0,"title":"产品说明书","source_file":"product.txt","heading_path":["赎回规则"],"marker":1}],"intent":"产品咨询","content_classification":"事实性内容"}\n\n',
    ]);

    const done = vi.fn();
    await streamChatMessage("最短持有期", { onDelta: vi.fn(), onDone: done, onError: vi.fn() }, fetchImpl);

    expect(done.mock.calls[0][0].citations[0].source_file).toBe("product.txt");
  });

  it("calls onError instead of throwing when the response has no body", async () => {
    const fetchImpl = sseResponse([], { body: false });
    const onError = vi.fn();

    await streamChatMessage("问题", { onDelta: vi.fn(), onDone: vi.fn(), onError }, fetchImpl);

    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("attaches the bearer token when one is stored", async () => {
    setTokens({ accessToken: "token-abc", refreshToken: "r" });
    const fetchImpl = sseResponse([
      'event: done\ndata: {"answer":"","citations":[],"intent":"FAQ","content_classification":"事实性内容"}\n\n',
    ]);

    try {
      await streamChatMessage("问题", { onDelta: vi.fn(), onDone: vi.fn(), onError: vi.fn() }, fetchImpl);

      const [, init] = vi.mocked(fetchImpl).mock.calls[0];
      expect((init?.headers as Record<string, string>)["Authorization"]).toBe("Bearer token-abc");
    } finally {
      clearTokens();
    }
  });

  it("clears stored tokens and reports an error when the session is no longer valid", async () => {
    setTokens({ accessToken: "expired-token", refreshToken: "r" });
    const fetchImpl = sseResponse([], { ok: false, status: 401 });
    const onError = vi.fn();

    await streamChatMessage("问题", { onDelta: vi.fn(), onDone: vi.fn(), onError }, fetchImpl);

    expect(onError).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBeNull();
  });

  // 这条通道绕过了 http 客户端，401 得自己处理。access token 过期不等于会话结束：
  // 换一张再重连，而不是把人送回登录页。
  it("renews the access token on 401 and reconnects the stream", async () => {
    setTokens({ accessToken: "expired-token", refreshToken: "refresh-1" });
    const refreshFetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      json: async () => ({
        code: 200,
        message: "success",
        data: { access_token: "fresh-token", token_type: "bearer", expires_in: 900 },
        trace_id: "trace-1",
      }),
    }));
    vi.stubGlobal("fetch", refreshFetch);

    const streamFetch = vi
      .fn()
      .mockImplementationOnce(sseResponse([], { ok: false, status: 401 }))
      .mockImplementationOnce(
        sseResponse([
          'event: done\ndata: {"answer":"续上了","citations":[],"intent":"FAQ","content_classification":"事实性内容"}\n\n',
        ]),
      ) as unknown as typeof fetch;

    const onDone = vi.fn();
    const onError = vi.fn();
    await streamChatMessage("问题", { onDelta: vi.fn(), onDone, onError }, streamFetch);

    expect(String(refreshFetch.mock.calls[0][0])).toContain("/api/customer/auth/refresh");
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe("fresh-token");

    const [, retryInit] = vi.mocked(streamFetch).mock.calls[1] as [RequestInfo | URL, RequestInit];
    expect((retryInit.headers as Record<string, string>).Authorization).toBe("Bearer fresh-token");
  });
});
