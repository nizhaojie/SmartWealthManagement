// 数据分析的线程 store：一轮问答的累积（含上限）与它的持久层（sessionStorage）。
//
// 会话边界是这里的重点：线程要活过刷新（切模块、F5 都不断），但登出与重新登录一律清空——
// 「不跨登录延续」由登录路径保证；「清空对话」只丢上下文、不结束会话，靠换一个会话标识
// 随请求覆盖来做到。
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "../stores/auth";
import { ADVISOR } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { stubApiFetch } from "../testing";
import {
  MAX_RESULT_ROWS,
  MAX_ROUNDS,
  useAnalyticsThreadStore,
  type AssistantMessage,
} from "./threadStore";
import type { AnalyticsQueryResponse } from "./types";

const EMPLOYEE = "张顾问";

type StoredThread = {
  version: number;
  messages: unknown[];
  droppedRounds: number;
  sessionId: string | null;
};

function answer(overrides: Partial<AnalyticsQueryResponse> = {}): AnalyticsQueryResponse {
  return {
    question: "这个月新增了几个客户",
    sql: "SELECT count(*) FROM v_customer",
    columns: ["count"],
    rows: [[3]],
    row_count: 1,
    truncated: false,
    views: ["v_customer"],
    interpretation: "这个月新增 3 位客户。",
    content_classification: "事实性内容",
    disclaimer: null,
    ...overrides,
  };
}

function signIn(name = EMPLOYEE): void {
  useAuthStore().currentEmployee = { real_name: name, employee_role: ADVISOR };
}

/** 换一个全新 pinia = 刷新页面：store 的 setup 重跑，重新从 sessionStorage 读。 */
function refresh(): void {
  setActivePinia(createPinia());
}

function storedThread(name = EMPLOYEE): StoredThread | null {
  const raw = sessionStorage.getItem(`wealth-internal-analytics-thread:${name}`);
  return raw ? (JSON.parse(raw) as StoredThread) : null;
}

let pinia: Pinia;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
  pinia = createPinia();
  setActivePinia(pinia);
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
});

describe("问答线程的累积与上限", () => {
  it("开启一轮先记下问题与「正在查询」的助手位，拿到结果再收尾", () => {
    signIn();
    const store = useAnalyticsThreadStore();

    const roundId = store.beginRound("这个月新增了几个客户");

    expect(store.messages.map((message) => message.role)).toEqual(["user", "assistant"]);
    expect(store.messages[1]).toMatchObject({ status: "pending", result: null, failure: null });

    store.settleRound(roundId, answer());

    const settled = store.messages[1] as AssistantMessage;
    expect(settled.status).toBe("answered");
    expect(settled?.result?.interpretation).toBe("这个月新增 3 位客户。");
  });

  it("失败收尾把业务码与后端那句原文都留在这一轮里", () => {
    signIn();
    const store = useAnalyticsThreadStore();

    const roundId = store.beginRound("查一下这个月的交易笔数");
    store.failRound(roundId, { code: 1103, message: "查询未通过安全校验" });

    expect(store.messages[1]).toMatchObject({
      status: "failed",
      result: null,
      failure: { code: 1103, message: "查询未通过安全校验" },
    });
  });

  it("只保留最近 20 轮，更早的整轮移出本页并记账", () => {
    signIn();
    const store = useAnalyticsThreadStore();

    for (let round = 1; round <= MAX_ROUNDS + 1; round += 1) {
      const roundId = store.beginRound(`第 ${round} 轮`);
      store.settleRound(roundId, answer({ question: `第 ${round} 轮` }));
    }

    expect(store.messages).toHaveLength(MAX_ROUNDS * 2);
    // 整轮走：不会只留下它的问题或只留下它的回答。
    expect(store.messages[0]).toMatchObject({ role: "user", question: "第 2 轮" });
    expect(store.droppedRounds).toBe(1);
    expect(storedThread()?.droppedRounds).toBe(1);
  });

  it("结果行收在后端上限之内，多出来的不落进线程", () => {
    signIn();
    const store = useAnalyticsThreadStore();
    const rows = Array.from({ length: MAX_RESULT_ROWS + 10 }, (_, index) => [index]);

    const roundId = store.beginRound("大结果");
    store.settleRound(roundId, answer({ rows, row_count: rows.length }));

    const settled = store.messages[1] as AssistantMessage;
    expect(settled?.result?.rows).toHaveLength(MAX_RESULT_ROWS);
  });
});

describe("线程的持久层", () => {
  it("经 sessionStorage 往返后不变形：刷新后两轮问答都还在", () => {
    signIn();
    const first = useAnalyticsThreadStore();
    first.settleRound(first.beginRound("上个月各风险等级的客户分布"), answer());
    first.failRound(first.beginRound("查一下这个月的交易笔数"), {
      code: 1104,
      message: "查询超时",
    });
    const before = JSON.parse(JSON.stringify(first.messages)) as unknown[];

    refresh();
    signIn();
    const restored = useAnalyticsThreadStore();

    expect(restored.messages).toEqual(before);
    expect(restored.droppedRounds).toBe(0);
    // 没清空过，就没有要覆盖凭证的标识。
    expect(restored.sessionId).toBeNull();
  });

  it("键按员工隔离：别人的线程不在我的线程里", () => {
    signIn();
    useAnalyticsThreadStore().beginRound(`${EMPLOYEE} 的问题`);

    refresh();
    signIn("李顾问");

    expect(useAnalyticsThreadStore().messages).toEqual([]);
    expect(storedThread()).not.toBeNull();
    expect(storedThread("李顾问")).toBeNull();
  });

  it("读不回来的持久层数据当它不存在，不把页面挂掉", () => {
    signIn();
    sessionStorage.setItem(`wealth-internal-analytics-thread:${EMPLOYEE}`, "{不是 JSON");

    expect(useAnalyticsThreadStore().messages).toEqual([]);
    expect(storedThread()).toBeNull();
  });
});

describe("会话边界", () => {
  it("「清空对话」清掉线程与持久层，并换一个新的会话标识", () => {
    signIn();
    const store = useAnalyticsThreadStore();
    store.settleRound(store.beginRound("这个月新增了几个客户"), answer());
    expect(store.sessionId).toBeNull();

    store.discardContext();

    expect(store.messages).toEqual([]);
    expect(store.isEmpty).toBe(true);
    expect(store.droppedRounds).toBe(0);
    expect(store.sessionId).toEqual(expect.any(String));
    // 新标识落进持久层：刷新之后紧接着的那一问仍然甩得开清空前的上下文。
    expect(storedThread()?.sessionId).toBe(store.sessionId);
  });

  it("清空之后的新标识活过刷新：重新挂载时紧接着那一问仍然甩得开旧上下文", () => {
    signIn();
    const store = useAnalyticsThreadStore();
    store.discardContext();
    const clearedSessionId = store.sessionId;

    refresh();
    signIn();

    expect(useAnalyticsThreadStore().sessionId).toBe(clearedSessionId);
  });

  it("登出清空线程与 sessionStorage", async () => {
    stubApiFetch();
    setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
    signIn();
    const store = useAnalyticsThreadStore();
    store.settleRound(store.beginRound("登出前问的问题"), answer());
    expect(storedThread()).not.toBeNull();

    await useAuthStore().logout();

    expect(store.messages).toEqual([]);
    expect(store.sessionId).toBeNull();
    expect(storedThread()).toBeNull();
    expect(sessionStorage.length).toBe(0);
  });

  it("重新登录也清空：上一场会话的线程不进新会话", async () => {
    stubApiFetch((url) => {
      if (url.includes("/api/internal/auth/login")) {
        return { access_token: "access-token", refresh_token: "refresh-token" };
      }
      if (url.includes("/api/internal/auth/me")) {
        return { real_name: EMPLOYEE, employee_role: ADVISOR };
      }
      return undefined;
    });
    signIn();
    const store = useAnalyticsThreadStore();
    store.beginRound("上一场会话的问题");
    expect(storedThread()).not.toBeNull();

    await useAuthStore().login("zhang", "Test@1234");

    expect(store.messages).toEqual([]);
    expect(storedThread()).toBeNull();
  });
});
