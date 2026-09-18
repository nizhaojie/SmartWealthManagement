// SSE 帧解析是客服链路的传输面：`event: done` 携带定案答案与引用，其余帧携带 delta，
// 异常必须走 onError 而不是抛出去。这里只测这三件事，不测页面渲染。
import { describe, expect, it, vi } from "vitest";
import { clearTokens, getAccessToken, setTokens } from "../auth/tokenStore";
import { streamChatMessage } from "./api";

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
  it("emits deltas in order and the final structured payload on done", async () => {
    const fetchImpl = sseResponse([
      'data: {"delta":"你"}\n\n',
      'data: {"delta":"好"}\n\n',
      'event: done\ndata: {"answer":"你好","citations":[],"intent":"闲聊","content_classification":"事实性内容"}\n\n',
    ]);

    const deltas: string[] = [];
    const done = vi.fn();
    await streamChatMessage(
      "你好",
      { onDelta: (delta) => deltas.push(delta), onDone: done, onError: vi.fn() },
      fetchImpl,
    );

    expect(deltas).toEqual(["你", "好"]);
    expect(done).toHaveBeenCalledWith({
      answer: "你好",
      citations: [],
      intent: "闲聊",
      content_classification: "事实性内容",
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
});
