import { clearTokens, getAccessToken } from "../auth/tokenStore";

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
};

export type ChatStreamHandlers = {
  onDelta: (text: string) => void;
  onDone: (payload: ChatStreamDone) => void;
  onError: (error: unknown) => void;
};

const STREAM_PATH = "/api/customer/chat/stream";

function streamUrl(): string {
  const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
  return `${base}${STREAM_PATH}`;
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
      clearTokens();
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
