// 智能客服的流式通道。
//
// SSE 帧为 `event:` / `data:` 两行，帧之间以空行分隔；`event: done` 携带定案答案与引用，
// 其余帧携带 `delta`。用 fetch + body.getReader() 手动切帧，不用 EventSource——
// EventSource 只能发 GET，而这条通道是 POST。
import { apiBaseUrl, handleExpiredSession } from "../api/http";
import { getAccessToken } from "../auth/tokenStore";

export type Citation = {
  knowledge_id: number;
  chunk_index: number;
  title: string;
  source_file: string;
  heading_path: string[];
  marker: number;
};

export type ChatStreamDone = {
  answer: string;
  citations: Citation[];
  intent: string;
  content_classification: string;
  // 贯穿全链路的追踪标识；排障时用它把一次用户可见的失败对到后端日志。
  trace_id?: string;
  // 这一轮是否走了降级路径（模型兜底、向量超时转关键词……）。降级后的回答照常渲染，
  // 缺引用也不报错；这个标记只用于说明这次回答的成色。
  degraded?: boolean;
};

export type ChatStreamHandlers = {
  onDelta: (text: string) => void;
  onDone: (payload: ChatStreamDone) => void;
  onError: (error: unknown) => void;
};

const STREAM_PATH = "/api/customer/chat/stream";

function streamUrl(): string {
  return `${apiBaseUrl()}${STREAM_PATH}`;
}

function parseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  let dataLine: string | null = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLine = line.slice("data:".length).trim();
    }
  }
  if (dataLine === null) {
    return null;
  }
  return { event, data: JSON.parse(dataLine) };
}

export async function streamChatMessage(
  message: string,
  handlers: ChatStreamHandlers,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  try {
    const token = getAccessToken();
    const response = await fetchImpl(streamUrl(), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message }),
    });

    if (response.status === 401) {
      handleExpiredSession();
      throw new Error("凭证无效或已过期");
    }
    if (!response.ok || !response.body) {
      throw new Error("对话流连接失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const rawFrame of frames) {
        if (!rawFrame.trim()) {
          continue;
        }
        const parsed = parseFrame(rawFrame);
        if (!parsed) {
          continue;
        }
        if (parsed.event === "done") {
          handlers.onDone(parsed.data as ChatStreamDone);
        } else {
          handlers.onDelta((parsed.data as { delta: string }).delta);
        }
      }
    }
  } catch (error) {
    handlers.onError(error);
  }
}
