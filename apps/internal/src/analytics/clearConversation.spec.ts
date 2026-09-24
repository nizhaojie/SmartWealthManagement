// 页头的「清空对话」：会话里有内容时二次确认，确认后主区回到空态、线程换上一个新的
// 会话标识随请求覆盖；留痕（历史查询）一条不动。
//
// 「换标识」这一条只能在请求体上验：后端 `session_id` 有值时优先于凭证，前端不再生成
// 标识、只在清空之后带一个新的——这是票号 01 钉下的机制前提。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ADVISOR } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { useAuthStore } from "../stores/auth";
import { requestedUrls, stubApiFetch } from "../testing";

const confirm = vi.hoisted(() => vi.fn(() => Promise.resolve("confirm")));

vi.mock("element-plus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("element-plus")>();
  // 二次确认走真实组件会拉起一整套浮层时序；这里只钉「确认之后才清」这条契约。
  return { ...actual, ElMessageBox: { ...actual.ElMessageBox, confirm } };
});

import DataAnalysisWorkspace from "./DataAnalysisWorkspace.vue";

const ANSWER = {
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
};

const EMPLOYEE = "张顾问";
const THREAD_KEY = `wealth-internal-analytics-thread:${EMPLOYEE}`;

let wrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

async function mountWorkspace(): Promise<VueWrapper> {
  fetchMock = stubApiFetch((url) => {
    if (url.includes("/api/internal/analytics/query")) {
      return ANSWER;
    }
    return undefined;
  });

  const pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  useAuthStore().currentEmployee = { real_name: EMPLOYEE, employee_role: ADVISOR };

  wrapper = mount(DataAnalysisWorkspace, { global: { plugins: [pinia, ElementPlus] } });
  await flushPromises();
  return wrapper;
}

/** 提问框在换成问答线程之前还是单行输入；形态再变一次时只需改这一行。 */
async function askQuestion(app: VueWrapper, text: string): Promise<void> {
  await app.get("input[name='question']").setValue(text);
  // jsdom 不实现「点 submit 按钮即提交表单」，这里直接触发 submit 事件（与登录页用例同一手法）。
  await app.get("form.ask").trigger("submit");
  await flushPromises();
}

async function clearThread(app: VueWrapper): Promise<void> {
  await app.get('[data-testid="clear-thread"]').trigger("click");
  await flushPromises();
}

/** 每一次查询请求的请求体：会话标识带没带、带的哪个，只能从这里看。 */
function queryBodies(): Record<string, unknown>[] {
  return fetchMock.mock.calls
    .filter((call) => String(call[0]).includes("/api/internal/analytics/query"))
    .map((call) => JSON.parse(String((call[1] as RequestInit).body)) as Record<string, unknown>);
}

/** 上一场登录留下的线程（已按 store 的存储形状落好）：用来验「重新挂载后读回来」。 */
function storeThread(droppedRounds = 0): void {
  sessionStorage.setItem(
    THREAD_KEY,
    JSON.stringify({
      version: 1,
      messages: [
        { id: "u-1", role: "user", question: "上个月各风险等级的客户分布" },
        { id: "a-1", role: "assistant", status: "answered", result: ANSWER, failure: null },
      ],
      droppedRounds,
      sessionId: null,
    }),
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
  confirm.mockClear();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
});

describe("页头的「清空对话」", () => {
  it("会话为空时这一下没有上下文可丢：按钮不可用", async () => {
    const app = await mountWorkspace();

    expect(app.get('[data-testid="clear-thread"]').attributes("disabled")).toBeDefined();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("会话里有内容时先确认；取消则什么都不清", async () => {
    const app = await mountWorkspace();
    await askQuestion(app, "这个月新增了几个客户");

    confirm.mockRejectedValueOnce(new Error("cancel"));
    await clearThread(app);

    expect(confirm).toHaveBeenCalled();
    // 取消不是错误，也不该有副作用：这一轮还留在主区上。
    expect(app.get('[data-testid="interpretation"]').text()).toBe("这个月新增 3 位客户。");
  });

  it("确认后主区回到空态，紧接着的提问带上了新的会话标识", async () => {
    const app = await mountWorkspace();
    await askQuestion(app, "这个月新增了几个客户");
    await askQuestion(app, "那上个季度呢");
    // 清空前不带标识：会话由登录凭证承载（票号 01）。
    expect(queryBodies()[0]?.session_id).toBeUndefined();
    expect(queryBodies()[1]?.session_id).toBeUndefined();

    await clearThread(app);

    expect(app.find('[data-testid="interpretation"]').exists()).toBe(false);

    await askQuestion(app, "清空之后的新问题");
    const clearedSessionId = queryBodies()[2]?.session_id;
    expect(typeof clearedSessionId).toBe("string");

    // 标识留在后续的每一问上：否则下一句会落回凭证那个标识，被丢弃的上下文又回来了。
    await askQuestion(app, "再问一句");
    expect(queryBodies()[3]?.session_id).toBe(clearedSessionId);
  });

  it("清空对话不触碰审计留痕：历史查询不因这一下重取", async () => {
    const app = await mountWorkspace();
    await askQuestion(app, "这个月新增了几个客户");
    const before = requestedUrls(fetchMock, "/api/internal/analytics/history").length;

    await clearThread(app);

    expect(requestedUrls(fetchMock, "/api/internal/analytics/history")).toHaveLength(before);
  });
});

describe("页面挂载时读回的线程", () => {
  it("sessionStorage 里的线程就是页面的线程：没问任何问题也清得掉", async () => {
    storeThread();
    const app = await mountWorkspace();

    expect(app.get('[data-testid="clear-thread"]').attributes("disabled")).toBeUndefined();

    await clearThread(app);

    const stored = JSON.parse(sessionStorage.getItem(THREAD_KEY) ?? "{}") as {
      messages?: unknown[];
      sessionId?: string | null;
    };
    expect(stored.messages).toEqual([]);
    // 换上的新标识也在持久层里：刷新之后紧接着那一问仍然甩得开旧上下文。
    expect(stored.sessionId).toEqual(expect.any(String));
  });

  it("被上限裁掉的更早轮次在界面留一句说明，而不是静默消失", async () => {
    storeThread(2);
    const app = await mountWorkspace();

    expect(app.get('[data-testid="dropped-rounds"]').text()).toBe("更早的一轮已从本页移除");
  });
});
