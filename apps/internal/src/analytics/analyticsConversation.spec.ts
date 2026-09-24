// 对话壳与输入区（ticket 03）：主区是一条**可累积的线程**，底部是一个多行输入区。
//
// 这里钉的是这次改动要修的核心缺陷——「连问两次，上一轮还看得见」。表单范式下
// `result` 是单槽，第二问必然覆盖第一问，追问在界面上不成立。
//
// 不测排版（气泡左右对齐、宽度、滚动条）：沿袭 `frontend-rebuild` 的口径，
// 只测交互语义与可点可发问这件事。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ADVISOR } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { useAuthStore } from "../stores/auth";
import { requestedUrls, stubApiFetch } from "../testing";
import DataAnalysisWorkspace from "./DataAnalysisWorkspace.vue";

const EMPLOYEE = "张顾问";
const EXAMPLE = "上个月各风险等级的客户余额";

function answer(question: string) {
  return {
    question,
    sql: "SELECT count(*) FROM v_customer",
    columns: ["count"],
    rows: [[3]],
    row_count: 1,
    truncated: false,
    views: ["v_customer"],
    interpretation: `关于「${question}」的解读。`,
    content_classification: "事实性内容",
    disclaimer: null,
  };
}

let wrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

async function mountWorkspace(options: { hang?: boolean } = {}): Promise<VueWrapper> {
  if (options.hang) {
    // 一个永远不落地的请求：用来观察「在途」这一段时间里界面上有什么。
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
  } else {
    fetchMock = stubApiFetch((url, init) => {
      if (url.includes("/api/internal/analytics/query")) {
        const body = JSON.parse(String(init?.body)) as { question: string };
        // 每条回答都带上它自己的问题：哪一轮答的是哪一问，界面上必须对得上。
        return answer(body.question);
      }
      if (url.includes("/api/internal/analytics/examples")) {
        return [{ question: EXAMPLE }];
      }
      return undefined;
    });
  }

  const pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  useAuthStore().currentEmployee = { real_name: EMPLOYEE, employee_role: ADVISOR };

  wrapper = mount(DataAnalysisWorkspace, {
    global: { plugins: [pinia, ElementPlus] },
    // 挂进文档：提交后要保持焦点，`document.activeElement` 只在已连接的节点上说得通。
    attachTo: document.body,
  });
  await flushPromises();
  return wrapper;
}

/** 输入区是 2–4 行自适应的多行输入（ticket 03 起从单行输入换过来）。 */
function composer(app: VueWrapper) {
  return app.get("textarea[name='question']");
}

/** 每一次查询请求的请求体：问的是哪一句，只能从这里看。 */
function queryBodies(): Record<string, unknown>[] {
  return fetchMock.mock.calls
    .filter((call) => String(call[0]).includes("/api/internal/analytics/query"))
    .map((call) => JSON.parse(String((call[1] as RequestInit).body)) as Record<string, unknown>);
}

/** 解读是逐字上屏的（30ms/字）：把打字机走完再看文本。 */
async function playOutTypewriter(): Promise<void> {
  await vi.advanceTimersByTimeAsync(4000);
  await flushPromises();
}

async function ask(app: VueWrapper, question: string): Promise<void> {
  await composer(app).setValue(question);
  await app.get("form.ask").trigger("submit");
  await flushPromises();
  await playOutTypewriter();
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
  // 只 fake 打字机的 setInterval：setTimeout 保持真实，flushPromises 才 resolve 得掉。
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.useRealTimers();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
});

describe("空态", () => {
  it("给一句引导与示例问题，并写明只能问语义视图覆盖的范围", async () => {
    const app = await mountWorkspace();

    // 先说出可查范围，「超出可查范围」才是可预期的结果，而不是碰了才知道。
    expect(app.get("[data-testid='conversation-empty']").text()).toContain("语义视图");
    expect(app.findAll("[data-testid='example-question']")).toHaveLength(1);
    // 还没问过，就没有线程。
    expect(app.find("[data-testid='conversation-thread']").exists()).toBe(false);
  });

  it("点示例问题直接发问，而不是只填进输入框", async () => {
    const app = await mountWorkspace();

    await app.get("[data-testid='example-question']").trigger("click");
    await flushPromises();
    await playOutTypewriter();

    const asked = requestedUrls(fetchMock, "/api/internal/analytics/query");
    expect(asked).toHaveLength(1);
    expect(queryBodies()[0]?.question).toBe(EXAMPLE);
    // 这一问已经在线程里（问与答都要出现），不是回填到输入框等用户再按一次。
    expect(app.get("[data-testid='user-bubble']").text()).toContain(EXAMPLE);
    expect((composer(app).element as HTMLTextAreaElement).value).toBe("");
  });
});

describe("线程", () => {
  it("连问两次后两轮问答同时看得见", async () => {
    const app = await mountWorkspace();

    await ask(app, "上个月各风险等级的客户分布");
    await ask(app, "那上个季度呢");

    expect(app.findAll("[data-testid='user-bubble']").map((bubble) => bubble.text())).toEqual([
      "上个月各风险等级的客户分布",
      "那上个季度呢",
    ]);
    expect(
      app.findAll("[data-testid='interpretation']").map((bubble) => bubble.text()),
    ).toEqual(["关于「上个月各风险等级的客户分布」的解读。", "关于「那上个季度呢」的解读。"]);
    // 两轮都在，谁也没有覆盖谁：这正是表单范式下做不到的。
    expect(app.findAll("[data-testid='assistant-bubble']")).toHaveLength(2);
    // 空态只在没问过的时候出现。
    expect(app.find("[data-testid='conversation-empty']").exists()).toBe(false);
  });

  it("解读逐字上屏：整包到达后一个字一个字地出现", async () => {
    const app = await mountWorkspace();
    await composer(app).setValue("这个月新增了几个客户");
    await app.get("form.ask").trigger("submit");
    await flushPromises();

    // 服务端已经把整句交过来了，但页面上才吐了两个字（30ms 一个字）。
    await vi.advanceTimersByTimeAsync(60);
    expect(app.get("[data-testid='interpretation']").text()).toBe("关于");

    await vi.advanceTimersByTimeAsync(4000);
    expect(app.get("[data-testid='interpretation']").text()).toBe("关于「这个月新增了几个客户」的解读。");
  });

  it("线程自动滚到底部", async () => {
    const app = await mountWorkspace();
    await ask(app, "上个月各风险等级的客户分布");
    const list = app.get("[data-testid='conversation-thread']").element as HTMLElement;
    Object.defineProperty(list, "scrollHeight", { value: 900, configurable: true });

    await ask(app, "那上个季度呢");

    expect(list.scrollTop).toBe(900);
  });
});

describe("加载态", () => {
  it("在途期间只有「正在查询数据…」，不演后端并未告知的阶段", async () => {
    const app = await mountWorkspace({ hang: true });

    await composer(app).setValue("这个月新增了几个客户");
    await app.get("form.ask").trigger("submit");
    await flushPromises();

    // 助手气泡先出现，内容只有一个诚实的加载态。
    expect(app.get("[data-testid='user-bubble']").text()).toBe("这个月新增了几个客户");
    const loading = app.get("[data-testid='loading']");
    expect(loading.text()).toContain("正在查询数据…");
    for (const stage of ["生成查询", "校验", "执行", "解读"]) {
      expect(loading.text()).not.toContain(stage);
    }
    // 还没拿到回答，就没有解读。
    expect(app.findAll("[data-testid='interpretation']")).toHaveLength(0);
  });
});

describe("输入区", () => {
  it("Ctrl+Enter 提交，Enter 只换行", async () => {
    const app = await mountWorkspace();

    await composer(app).setValue("这个月新增了几个客户");
    await composer(app).trigger("keydown", { key: "Enter" });
    await flushPromises();
    // Enter 留给换行：中文输入法组字时的 Enter 上屏也就不会被当成发送。
    expect(requestedUrls(fetchMock, "/api/internal/analytics/query")).toHaveLength(0);

    await composer(app).trigger("keydown", { key: "Enter", ctrlKey: true });
    await flushPromises();
    await playOutTypewriter();
    expect(requestedUrls(fetchMock, "/api/internal/analytics/query")).toHaveLength(1);
  });

  it("提交后输入框清空并留在输入框里", async () => {
    const app = await mountWorkspace();

    await ask(app, "这个月新增了几个客户");

    const element = composer(app).element as HTMLTextAreaElement;
    expect(element.value).toBe("");
    expect(document.activeElement).toBe(element);
  });
});
