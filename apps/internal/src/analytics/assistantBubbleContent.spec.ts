// 助手气泡的内容面（ticket 04）：一轮的产物按固定次序落在气泡里——
// 口径解读 → 结果表 → 可折叠 SQL → 贴底的元信息行，另有截断与免责两处提示。
//
// 合规呈现面一件都不能少：失败不是一句「出错了」，五种业务码各自成文案；
// 被拒绝的查询看到的是「查询未通过安全校验」，而不是一张空表格。
//
// 沿袭 `frontend-rebuild` 的口径：只测合规呈现面与交互语义，不测排版（气泡宽度、对齐、滚动）。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssistantBubble from "./AssistantBubble.vue";
import type { AssistantMessage } from "./threadStore";
import type { AnalyticsQueryResponse } from "./types";

function answer(overrides: Partial<AnalyticsQueryResponse> = {}): AnalyticsQueryResponse {
  return {
    question: "上个月各风险等级的客户分布",
    sql: "SELECT risk_level, count(*) FROM v_customer GROUP BY risk_level",
    columns: ["risk_level", "count"],
    rows: [
      ["C1", 2],
      ["C2", 3],
    ],
    row_count: 2,
    truncated: false,
    views: ["v_customer"],
    interpretation: "上个月 C1 有 2 位、C2 有 3 位客户。",
    content_classification: "事实性内容",
    disclaimer: null,
    ...overrides,
  };
}

function bubble(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "a-1",
    role: "assistant",
    status: "answered",
    result: answer(),
    failure: null,
    ...overrides,
  };
}

function failed(failure: { code: number | null; message: string }): AssistantMessage {
  return bubble({ status: "failed", result: null, failure });
}

let wrappers: VueWrapper[] = [];

function mountBubble(message: AssistantMessage, typing = false): VueWrapper {
  const app = mount(AssistantBubble, {
    props: { message, typing },
    global: { plugins: [ElementPlus] },
  });
  wrappers.push(app);
  return app;
}

/** 导出走的下载是浏览器行为：jsdom 不实现这两个，替掉它们才能看「导出了什么」。 */
const createObjectURL = vi.fn((_blob: Blob) => "blob:analytics-csv");
const revokeObjectURL = vi.fn();
let clicked: HTMLAnchorElement | null = null;

/** jsdom 的 Blob 没有 arrayBuffer()：要按字节看 BOM，只能经 FileReader。 */
function readBytes(blob: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

beforeEach(() => {
  Object.defineProperty(URL, "createObjectURL", {
    value: createObjectURL,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: revokeObjectURL,
    configurable: true,
    writable: true,
  });
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  clicked = null;
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked = this;
  });
});

afterEach(() => {
  wrappers.forEach((app) => app.unmount());
  wrappers = [];
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("五种业务码各自的文案", () => {
  const COPIES: Array<[number, string]> = [
    [1101, "超出可查范围"],
    [1102, "无法生成查询"],
    [1103, "查询未通过安全校验"],
    [1104, "查询超时"],
    [1105, "查询执行失败"],
  ];

  it.each(COPIES)("%i 渲染它自己的文案", (code, copy) => {
    const app = mountBubble(failed({ code, message: "后端写下的那句话" }));

    expect(app.get("[data-testid='failure-reason']").text()).toContain(copy);
    // 失败也是「一轮的产物」：警示块落在正常回答的位置上，气泡的状态如实写着 failed。
    expect(app.get("[data-testid='assistant-bubble']").attributes("data-status")).toBe("failed");
    // 没问成就是没问成：不摆一张空表格充数。
    expect(app.find("[data-testid='result-table']").exists()).toBe(false);
  });

  it("五种码的文案互不相同，不是一句笼统的「出错了」", () => {
    const texts = COPIES.map(([code]) =>
      mountBubble(failed({ code, message: "后端写下的那句话" }))
        .get("[data-testid='failure-reason']")
        .text(),
    );

    expect(new Set(texts).size).toBe(COPIES.length);
  });

  it("后端原文留着另起一行：呈现文案由码决定，原文用来诊断", () => {
    const app = mountBubble(failed({ code: 1103, message: "表 customer_base 不在可查范围内" }));

    expect(app.get("[data-testid='failure-reason']").text()).toContain("查询未通过安全校验");
    expect(app.get("[data-testid='failure-detail']").text()).toContain(
      "表 customer_base 不在可查范围内",
    );
  });

  it("认不出的码不编文案：后端那句话原样呈现", () => {
    const app = mountBubble(failed({ code: null, message: "对话连接已中断" }));

    expect(app.get("[data-testid='failure-reason']").text()).toContain("对话连接已中断");
    // 原文已经当了呈现文案，不再重复一遍。
    expect(app.find("[data-testid='failure-detail']").exists()).toBe(false);
  });
});

describe("结果表与元信息行", () => {
  it("列由 columns 决定，行由 rows 拉链成对象", async () => {
    const app = mountBubble(bubble());
    // 表格的列是在挂载后注册进 store 的：等一个 tick 才看得到表头与表体。
    await flushPromises();

    const table = app.get("[data-testid='result-table']");
    const header = table.findAll("thead th").map((cell) => cell.text());
    const body = table.findAll("tbody tr").map((row) => row.findAll("td").map((c) => c.text()));

    expect(header).toEqual(["risk_level", "count"]);
    // 拉链对了才会是 C1↔2、C2↔3：错位的话这两行会变成 C1↔3、C2↔2。
    expect(body).toEqual([
      ["C1", "2"],
      ["C2", "3"],
    ]);
  });

  it("元信息行给出返回行数与涉及的视图", () => {
    const app = mountBubble(
      bubble({ result: answer({ row_count: 42, views: ["v_customer", "v_holding"] }) }),
    );

    expect(app.get("[data-testid='result-meta']").text()).toBe("共 42 行 · 涉及 v_customer、v_holding");
  });

  it("截断时渲染截断提示", () => {
    const app = mountBubble(bubble({ result: answer({ truncated: true, row_count: 200 }) }));

    expect(app.get("[data-testid='truncation-notice']").text()).toContain(
      "结果超过行数上限，已截断：仅显示前 200 行，并非全量",
    );
  });

  it("没截断就没有这条提示", () => {
    const app = mountBubble(bubble());

    expect(app.find("[data-testid='truncation-notice']").exists()).toBe(false);
  });

  it("免责声明非空时渲染，纯内部数据查询不带", () => {
    const withDisclaimer = mountBubble(
      bubble({ result: answer({ disclaimer: "本回答仅为参考，不构成投资建议。" }) }),
    );
    expect(withDisclaimer.get("[data-testid='disclaimer']").text()).toContain("不构成投资建议");

    const without = mountBubble(bubble());
    expect(without.find("[data-testid='disclaimer']").exists()).toBe(false);
  });
});

describe("可折叠的 SQL", () => {
  it("默认折叠，点开才出现，再点收起", async () => {
    const app = mountBubble(bubble());

    expect(app.find("[data-testid='sql-block']").exists()).toBe(false);

    await app.get("[data-testid='toggle-sql']").trigger("click");
    expect(app.get("[data-testid='sql-block']").text()).toContain("GROUP BY risk_level");

    await app.get("[data-testid='toggle-sql']").trigger("click");
    expect(app.find("[data-testid='sql-block']").exists()).toBe(false);
  });

  it("展开把气泡撑高时报一声 grow，线程才跟得上", async () => {
    const app = mountBubble(bubble());
    expect(app.emitted("grow")).toBeUndefined();

    await app.get("[data-testid='toggle-sql']").trigger("click");

    expect(app.emitted("grow")).toHaveLength(1);
  });
});

describe("导出 CSV", () => {
  it("导出的是当前结果，带 UTF-8 BOM", async () => {
    const app = mountBubble(bubble());

    await app.get("[data-testid='export-csv']").trigger("click");

    const blob = createObjectURL.mock.calls[0]?.[0] as Blob;
    const bytes = await readBytes(blob);
    // 头三字节是 UTF-8 BOM：Excel 靠它认出编码，中文列名才不乱码。
    expect([...bytes.slice(0, 3)]).toEqual([0xef, 0xbb, 0xbf]);
    // TextDecoder 默认吃掉 BOM，剩下的就是 CSV 正文。
    expect(new TextDecoder().decode(bytes)).toBe("risk_level,count\nC1,2\nC2,3");

    expect(clicked?.download).toMatch(/^analytics-\d+\.csv$/);
    expect(clicked?.getAttribute("href")).toBe("blob:analytics-csv");
    // 用完就回收：Blob URL 不撤销会一直占着内存。
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:analytics-csv");
  });
});

describe("结果面与逐字解读的次序", () => {
  it("刚到的这一轮：解读播完，表格与 SQL 才出现", async () => {
    // 只 fake 打字机的 setInterval：setTimeout 保持真实，flushPromises 才 resolve 得掉。
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const app = mountBubble(bubble(), true);
    await flushPromises();

    // 还在逐字上屏：结果面一个字都还没出来。
    expect(app.get("[data-testid='interpretation']").text()).not.toBe("上个月 C1 有 2 位、C2 有 3 位客户。");
    expect(app.find("[data-testid='result-table']").exists()).toBe(false);
    expect(app.find("[data-testid='result-meta']").exists()).toBe(false);

    await vi.advanceTimersByTimeAsync(4000);
    await flushPromises();

    expect(app.get("[data-testid='interpretation']").text()).toBe("上个月 C1 有 2 位、C2 有 3 位客户。");
    expect(app.get("[data-testid='result-table']").text()).toContain("C1");
    expect(app.get("[data-testid='result-meta']").text()).toBe("共 2 行 · 涉及 v_customer");
  });

  it("读回的轮次：解读全文直出，结果面不等", async () => {
    const app = mountBubble(bubble());
    // 没有 setInterval 可推，只等表格把列注册进来：读回的轮次不逐字播放，结果面也立刻就位。
    await flushPromises();

    expect(app.get("[data-testid='interpretation']").text()).toBe("上个月 C1 有 2 位、C2 有 3 位客户。");
    expect(app.get("[data-testid='result-table']").text()).toContain("C1");
  });
});
