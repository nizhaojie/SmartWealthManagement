// 历史查询搬进壳层右侧栏后的四条行为：栏里列记录、点开看的是那条记录、
// 点开不再改写提问框、提问后收起已点开的记录。
// 写在这里而不是页面单测里：只有挂上壳，才能证明这张卡真的在第三栏、而不在内容区。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { ADVISOR } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { apiError, stubApiFetch } from "../testing";

const HISTORY = [
  {
    id: 7,
    question: "上个月各风险等级的客户分布",
    sql: "SELECT risk_level, count(*) FROM v_customer GROUP BY risk_level",
    status: "成功",
    row_count: 5,
    truncated: false,
    error_code: null,
    create_time: "2026-09-18T10:00:00",
  },
  {
    id: 6,
    question: "查一下这个月的交易笔数",
    sql: "SELECT count(*) FROM v_transaction",
    status: "校验拒绝",
    row_count: null,
    truncated: false,
    error_code: 1103,
    create_time: "2026-09-17T09:00:00",
  },
];

const EXAMPLE = "上个月各风险等级的客户分布";

const ANSWER = {
  question: "这个月新增了几个客户",
  sql: "SELECT count(*) FROM v_customer",
  columns: ["count"],
  rows: [[3]],
  row_count: 1,
  truncated: false,
  views: ["v_customer"],
  interpretation: "这个月新增 3 位客户。",
  content_classification: "事实性",
  disclaimer: null,
};

let pinia: Pinia;
let wrapper: VueWrapper | null = null;

async function mountAnalysis(options: { history?: unknown } = {}): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: ADVISOR };
    }
    if (url.includes("/api/internal/analytics/history")) {
      return options.history ?? HISTORY;
    }
    if (url.includes("/api/internal/analytics/examples")) {
      return [{ question: EXAMPLE }];
    }
    if (url.includes("/api/internal/analytics/query")) {
      return ANSWER;
    }
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  await router.push("/data-analysis");
  await flushPromises();
  return wrapper;
}

function railItem(app: VueWrapper, id: number) {
  return app.get(`.app-shell__inspector [data-testid="history-item-${id}"]`);
}

/**
 * 提问框现在是单行输入（`el-input` 的默认形态，见 `DataAnalysisWorkspace.vue`）。
 * 三处断言都从这里取它，形态再变一次时只需改这一行。
 */
function questionInput(app: VueWrapper) {
  return app.get("input[name='question']");
}

function questionText(app: VueWrapper): string {
  return (questionInput(app).element as HTMLInputElement).value;
}

beforeEach(() => {
  localStorage.clear();
  clearTokens();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  clearTokens();
});

describe("数据分析的历史查询右侧栏", () => {
  it("历史查询常驻右侧栏并列出记录", async () => {
    const app = await mountAnalysis();

    expect(app.classes()).toContain("app-shell--with-inspector");
    expect(railItem(app, 7).text()).toContain("上个月各风险等级的客户分布");
    // 内容区不再重复这张卡：历史查询只有栏里这一份。
    expect(app.findAll(".app-shell__content [data-testid='history-item-7']")).toHaveLength(0);
  });

  it("点击历史记录在主区展示该条记录", async () => {
    const app = await mountAnalysis();
    expect(app.find("[data-testid='history-detail']").exists()).toBe(false);

    await railItem(app, 7).trigger("click");

    const detail = app.get(".app-shell__content [data-testid='history-detail']");
    expect(detail.get("[data-testid='history-detail-question']").text()).toBe(
      "上个月各风险等级的客户分布",
    );
    expect(detail.get("[data-testid='history-detail-status']").text()).toBe("成功");
    expect(detail.get("[data-testid='history-detail-sql']").text()).toContain(
      "GROUP BY risk_level",
    );
    expect(detail.text()).toContain("5 行");
  });

  it("点击历史记录不改写提问框", async () => {
    const app = await mountAnalysis();
    await questionInput(app).setValue("我正在输入的问题");

    await railItem(app, 7).trigger("click");

    expect(questionText(app)).toBe("我正在输入的问题");
  });

  it("提问后收起已选中的历史记录", async () => {
    const app = await mountAnalysis();
    await railItem(app, 7).trigger("click");
    expect(app.find("[data-testid='history-detail']").exists()).toBe(true);

    await questionInput(app).setValue("这个月新增了几个客户");
    // jsdom 不实现「点 submit 按钮即提交表单」，这里直接触发 submit 事件（与登录页用例同一手法）。
    await app.get("form.ask").trigger("submit");
    await flushPromises();

    expect(app.get("[data-testid='interpretation']").text()).toBe("这个月新增 3 位客户。");
    expect(app.find("[data-testid='history-detail']").exists()).toBe(false);
  });

  it("历史拉取失败时栏内说明加载失败", async () => {
    const app = await mountAnalysis({ history: apiError(500, "服务内部错误") });

    const rail = app.get(".app-shell__inspector");
    expect(rail.get("[data-testid='history-error']").text()).toContain("加载失败");
    expect(rail.find("[data-testid='history-empty']").exists()).toBe(false);
  });

  it("点击示例问题仍写回提问框", async () => {
    const app = await mountAnalysis();

    await app.get("[data-testid='example-question']").trigger("click");

    expect(questionText(app)).toBe(EXAMPLE);
  });
});
