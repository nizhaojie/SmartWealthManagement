// 智能客服的流式通道。
//
// SSE 帧为 `event:` / `data:` 两行，帧之间以空行分隔；`event: done` 携带定案答案与引用，
// 其余帧携带 `delta`。用 fetch + body.getReader() 手动切帧，不用 EventSource——
// EventSource 只能发 GET，而这条通道是 POST。
import { apiBaseUrl, handleExpiredSession, renewSession } from "../api/http";
import { getAccessToken } from "../auth/tokenStore";

export type Citation = {
  knowledge_id: number;
  chunk_index: number;
  title: string;
  source_file: string;
  heading_path: string[];
  marker: number;
};

export type DataAnswerColumn = {
  key: string;
  label: string;
};

/**
 * 客户侧数据查询的结果表（ADR-0028）。
 *
 * 它是一份客户契约，与后端 `DataAnswerResponse` 逐字段对齐，不是内部
 * `AnalyticsQueryResponse` 的裁剪版：没有 SQL、没有 `va_*` 视图名（`views` 是中文名）、
 * 没有 `customer_id` 列。`columns[].key` 是英文列名，只用来定位行里的值，不上界面。
 * `row_count` 是**已返回**的行数，是否被行数上限截断由 `truncated` 表达。
 */
export type DataAnswer = {
  columns: DataAnswerColumn[];
  // 拉链式二维数组：每行的值与 `columns` 一一对应。
  rows: unknown[][];
  row_count: number;
  truncated: boolean;
  views: string[];
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
  // 数据查询「有行」时才有的结果表。零行、失败/超时、白名单外三种出口都不带它——
  // 一张空表会把「没有数据」与「查询挂了」在观感上抹平。
  data_answer?: DataAnswer | null;
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
  return runStream(message, handlers, fetchImpl, true);
}

/** 这条通道绕过了 http 客户端，401 得自己处理——与那边的续期/失效两段式保持一致。 */
async function runStream(
  message: string,
  handlers: ChatStreamHandlers,
  fetchImpl: typeof fetch,
  // 续期后只重发一次：再 401 就是真的失效，不能再续，否则两边互相不认时会转圈。
  allowRenewal: boolean,
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
      // access token 过期不是会话结束：换一张再重发，令牌已由 renewSession 写回。
      if (allowRenewal && (await renewSession())) {
        return runStream(message, handlers, fetchImpl, false);
      }
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
