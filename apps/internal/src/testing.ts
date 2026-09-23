import { vi } from "vitest";
import { DEFAULT_PAGE_SIZE } from "@wealth/shared";

/**
 * 测试用的 fetch 替身：按 URL 给统一响应信封，而不是逐个 vi.mock API 模块。
 *
 * 这样做的好处是测试跑的是真实的 API 层（参数拼装、信封拆包、401 回调），
 * 只把网络边界换掉。`respond` 返回 `undefined` 表示「这一条走默认」。
 */
export type ApiResponder = (url: string, init?: RequestInit) => unknown;

export function envelope(data: unknown, code = 200, message = "success") {
  return { code, message, data, trace_id: "test-trace" };
}

/** 列表接口的一页（ADR-0024）：形状恒为 `{items, total, page, page_size}`。 */
function emptyPage(pageSize = DEFAULT_PAGE_SIZE) {
  return { items: [], total: 0, page: 1, page_size: pageSize };
}

const DEFAULTS: [string, unknown][] = [
  // 更具体的路径排在前面：这一串是按顺序取第一个命中的前缀。
  ["/risk-assessments", emptyPage()],
  ["/api/internal/customers", emptyPage()],
  ["/api/internal/risk-alerts", emptyPage()],
  ["/api/internal/risk-focus", emptyPage()],
  ["/api/internal/risk-rules", emptyPage()],
  ["/api/internal/work-orders", []],
  ["/api/internal/knowledge/documents", []],
  ["/api/internal/analytics/history", []],
  ["/api/internal/analytics/examples", []],
  ["/api/internal/advisory/queue", emptyPage()],
  ["/api/internal/advisory/history", emptyPage()],
  ["/api/internal/advisory-requests", emptyPage()],
];

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function response(data: unknown): Response {
  return { ok: true, status: 200, json: async () => envelope(data) } as unknown as Response;
}

/** 非 200 的响应：http 客户端会把 code≠200 拆成 ApiError。 */
export function apiError(code: number, message: string): Response {
  return {
    ok: false,
    status: code,
    json: async () => envelope(null, code, message),
  } as unknown as Response;
}

function isResponseLike(value: unknown): boolean {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { json?: unknown }).json === "function"
  );
}

export function stubApiFetch(respond?: ApiResponder) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = urlOf(input);
    const custom = respond?.(url, init);
    if (custom !== undefined) {
      return isResponseLike(custom) ? (custom as Response) : response(custom);
    }
    const fallback = DEFAULTS.find(([path]) => url.includes(path));
    return response(fallback ? fallback[1] : null);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** 某次请求是否发到了这个片段，用来断言「动作有没有真的打出去」。 */
export function requestedUrls(fetchMock: { mock: { calls: unknown[][] } }, fragment: string): string[] {
  return fetchMock.mock.calls
    .map((call) => urlOf(call[0] as RequestInfo | URL))
    .filter((url) => url.includes(fragment));
}
