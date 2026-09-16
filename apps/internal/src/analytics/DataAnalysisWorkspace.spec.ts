import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import { toCsv } from "./csv";
import type { AnalyticsQueryResponse } from "./types";

const { runAnalyticsQuery, listAnalyticsHistory, listAnalyticsExamples } = vi.hoisted(
  () => ({
    runAnalyticsQuery: vi.fn(),
    listAnalyticsHistory: vi.fn(),
    listAnalyticsExamples: vi.fn(),
  }),
);

vi.mock("./api", () => ({
  runAnalyticsQuery,
  listAnalyticsHistory,
  listAnalyticsExamples,
}));

import DataAnalysisWorkspace from "./DataAnalysisWorkspace.vue";

function makeResult(overrides: Partial<AnalyticsQueryResponse> = {}): AnalyticsQueryResponse {
  return {
    question: "各产品类型的持仓市值分布",
    sql: "SELECT product_type, SUM(current_value) AS total_value FROM va_holding_distribution GROUP BY product_type",
    columns: ["product_type", "total_value"],
    rows: [
      ["固收类", 1523000.5],
      ["权益类", 986000],
    ],
    row_count: 2,
    truncated: false,
    views: ["va_holding_distribution"],
    interpretation: "本次查询共返回 2 行。数据口径：持仓分布按当前市值合计。",
    content_classification: "事实性内容",
    disclaimer: null,
    ...overrides,
  };
}

async function mountWorkspace() {
  const wrapper = mount(DataAnalysisWorkspace, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

async function ask(wrapper: Awaited<ReturnType<typeof mountWorkspace>>, question: string) {
  await wrapper.get('textarea[name="question"]').setValue(question);
  await wrapper.get('[data-test="ask"]').trigger("click");
  await flushPromises();
}

describe("DataAnalysisWorkspace", () => {
  beforeEach(() => {
    runAnalyticsQuery.mockReset();
    listAnalyticsHistory.mockReset();
    listAnalyticsExamples.mockReset();
    listAnalyticsHistory.mockResolvedValue([]);
    listAnalyticsExamples.mockResolvedValue([
      { question: "资产规模超过一百万的客户有多少" },
    ]);
    runAnalyticsQuery.mockResolvedValue(makeResult());
  });

  it("renders the result table together with the interpretation, not just a table", async () => {
    const wrapper = await mountWorkspace();

    await ask(wrapper, "各产品类型的持仓市值分布");

    const text = wrapper.text();
    // 解读与表格同时可见。
    expect(text).toContain("数据口径");
    expect(text).toContain("固收类");
    expect(text).toContain("1523000.5");
    expect(text).toContain("权益类");
  });

  it("keeps the generated query collapsed by default and expands on demand", async () => {
    const wrapper = await mountWorkspace();
    await ask(wrapper, "各产品类型的持仓市值分布");

    expect(wrapper.text()).not.toContain("SELECT product_type");

    await wrapper.get('[data-test="toggle-sql"]').trigger("click");
    expect(wrapper.text()).toContain("SELECT product_type");

    await wrapper.get('[data-test="toggle-sql"]').trigger("click");
    expect(wrapper.text()).not.toContain("SELECT product_type");
  });

  it("renders a truncation notice when the result is truncated", async () => {
    runAnalyticsQuery.mockResolvedValue(makeResult({ truncated: true, row_count: 200 }));
    const wrapper = await mountWorkspace();

    await ask(wrapper, "各产品类型的持仓市值分布");

    expect(wrapper.text()).toContain("截断");
  });

  it("renders the reason instead of an empty table when the question is out of scope", async () => {
    runAnalyticsQuery.mockRejectedValue(
      new ApiError({ code: 1101, message: "问题超出可查范围", data: null, trace_id: "" }),
    );
    const wrapper = await mountWorkspace();

    await ask(wrapper, "今天天气怎么样");

    expect(wrapper.text()).toContain("问题超出可查范围");
    expect(wrapper.find('[data-test="result-table"]').exists()).toBe(false);
  });

  it("renders the reason when a query cannot be generated", async () => {
    runAnalyticsQuery.mockRejectedValue(
      new ApiError({ code: 1102, message: "无法生成查询", data: null, trace_id: "" }),
    );
    const wrapper = await mountWorkspace();

    await ask(wrapper, "持仓视角下一个无法生成查询的问题");

    expect(wrapper.text()).toContain("无法生成查询");
    expect(wrapper.find('[data-test="result-table"]').exists()).toBe(false);
  });

  it("attaches the disclaimer for report-class output and omits it for plain queries", async () => {
    runAnalyticsQuery.mockResolvedValue(
      makeResult({
        content_classification: "投顾内容",
        disclaimer: "本内容仅为投资分析参考，不构成任何直接投资建议。",
      }),
    );
    const wrapper = await mountWorkspace();
    await ask(wrapper, "给我一份财富报告");

    expect(wrapper.text()).toContain("不构成任何直接投资建议");

    runAnalyticsQuery.mockResolvedValue(makeResult());
    await ask(wrapper, "各产品类型的持仓市值分布");

    expect(wrapper.text()).not.toContain("不构成任何直接投资建议");
  });

  it("offers example questions so employees know what the tool can answer", async () => {
    const wrapper = await mountWorkspace();

    await wrapper.get('[data-test="example-question"]').trigger("click");

    const input = wrapper.get('textarea[name="question"]');
    expect((input.element as HTMLTextAreaElement).value).toBe(
      "资产规模超过一百万的客户有多少",
    );
  });

  it("lists past queries and reuses one on click", async () => {
    listAnalyticsHistory.mockResolvedValue([
      {
        id: 7,
        question: "最近一个月各产品的申购金额",
        sql: "SELECT ...",
        status: "成功",
        row_count: 12,
        truncated: false,
        error_code: null,
        create_time: "2026-09-16T09:30:00",
      },
    ]);
    const wrapper = await mountWorkspace();

    expect(wrapper.text()).toContain("最近一个月各产品的申购金额");

    await wrapper.get('[data-test="history-item-7"]').trigger("click");
    const input = wrapper.get('textarea[name="question"]');
    expect((input.element as HTMLTextAreaElement).value).toBe("最近一个月各产品的申购金额");
  });

  it("sends the same session id across questions so follow-ups share context", async () => {
    const wrapper = await mountWorkspace();

    await ask(wrapper, "各产品类型的持仓市值分布");
    await ask(wrapper, "那上个季度呢");

    expect(runAnalyticsQuery).toHaveBeenCalledTimes(2);
    const first = runAnalyticsQuery.mock.calls[0][0];
    const second = runAnalyticsQuery.mock.calls[1][0];
    expect(first.sessionId).toBeTruthy();
    expect(second.sessionId).toBe(first.sessionId);
  });

  it("exports the current result as a CSV download", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const wrapper = await mountWorkspace();
    await ask(wrapper, "各产品类型的持仓市值分布");

    await wrapper.get('[data-test="export-csv"]').trigger("click");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsText(blob);
    });
    expect(text).toContain("product_type,total_value");
    expect(text).toContain("固收类,1523000.5");
    vi.unstubAllGlobals();
  });
});

describe("toCsv", () => {
  it("escapes commas, quotes and newlines in cell values", () => {
    const csv = toCsv(
      ["name", "note"],
      [
        ["固收类,稳健", '他说"你好"'],
        ["权益类", "两行\n文本"],
      ],
    );

    expect(csv).toBe(
      'name,note\n"固收类,稳健","他说""你好"""\n权益类,"两行\n文本"',
    );
  });
});
