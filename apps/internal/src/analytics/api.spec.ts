// 会话标识的去向（ticket 01）：请求体里带不带 `session_id` 决定这一轮接不接上
// 上下文。缺省不带——会话由登录凭证承载，同一次登录的追问因此共用一个上下文；
// 只有「清空对话」之后才带一个新的标识，用它把上下文换掉。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { stubApiFetch } from "../testing";
import { runAnalyticsQuery } from "./api";

const ANSWER = {
  question: "各产品类型的持仓市值分布",
  sql: "SELECT 1",
  columns: ["product_type"],
  rows: [["固收"]],
  row_count: 1,
  truncated: false,
  views: ["va_holding_distribution"],
  interpretation: "口径：持有中持仓的当前市值。",
  content_classification: "事实性内容",
  disclaimer: null,
};

function bodyOf(fetchMock: ReturnType<typeof stubApiFetch>): Record<string, unknown> {
  const call = fetchMock.mock.calls.find((entry) =>
    String(entry[0]).includes("/api/internal/analytics/query"),
  );
  return JSON.parse(String((call?.[1] as RequestInit).body));
}

beforeEach(() => {
  setTokens({ accessToken: "token-abc", refreshToken: "r" });
});

afterEach(() => {
  vi.unstubAllGlobals();
  clearTokens();
});

describe("runAnalyticsQuery", () => {
  it("带问题时不带会话标识，会话交给登录凭证", async () => {
    const fetchMock = stubApiFetch(() => ANSWER);

    await runAnalyticsQuery({ question: ANSWER.question });

    // 键不在请求体里：后端据此取凭证里的 sid，而不是收到一个前端现编的值。
    expect(bodyOf(fetchMock)).toEqual({ question: ANSWER.question });
  });

  it("显式给了会话标识时带上它——清空对话靠这一支换掉上下文", async () => {
    const fetchMock = stubApiFetch(() => ANSWER);

    await runAnalyticsQuery({ question: ANSWER.question, sessionId: "cleared-1" });

    expect(bodyOf(fetchMock)).toEqual({
      question: ANSWER.question,
      session_id: "cleared-1",
    });
  });
});
