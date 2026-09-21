// 处置动作的角色门控：排除 / 升级 / 派生工单只对风控专员、且只对「未处理」的预警开放；
// 三个动作共用同一份理由，理由为空时提交不出去。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { ADVISOR, RISK_OFFICER, type EmployeeRole } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import { apiError, requestedUrls, stubApiFetch } from "../testing";
import AlertDetailPage from "./AlertDetailPage.vue";

const ALERT_DETAIL = {
  id: 3,
  customer_id: 9,
  customer_name: "王客户",
  alert_type: "大额转账",
  alert_level: "重度",
  confidence: 0.93,
  rule_codes: ["R001"],
  rule_hits: [
    {
      rule_code: "R001",
      rule_name: "单笔大额转账",
      category: "交易",
      alert_level: "重度",
      weight: 0.6,
      field: "amount",
      field_label: "交易金额",
      operator: ">=",
      operator_label: "大于等于",
      operator_symbol: "≥",
      threshold: "500000",
      observed_value: "520000",
      evidence: "交易金额 520000 ≥ 阈值 500000",
    },
  ],
  transaction_ids: [11],
  trigger_detail: "命中单笔大额转账",
  status: "未处理",
  source: "客户发起",
  handler_id: null,
  handle_result: null,
  handled_by_name: "",
  created_at: "2026-09-18T10:00:00",
  customer: {
    customer_id: 9,
    real_name: "王客户",
    customer_level: "白金",
    risk_level: "C3",
    manager_name: "李经理",
  },
  transactions: [],
  customer_history: [],
  work_order: null,
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

async function mountPage(role: EmployeeRole, detail: unknown = ALERT_DETAIL): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/risk-alerts/3")) return detail;
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "测试员工", employee_role: role };

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/risk-monitoring/alerts/:alertId", name: "risk-alert-detail", component: AlertDetailPage },
      { path: "/risk-monitoring", name: "risk-monitoring", component: { template: "<div />" } },
      { path: "/work-orders/:workOrderId", name: "work-order-detail", component: { template: "<div />" } },
    ],
  });
  await router.push("/risk-monitoring/alerts/3");
  await router.isReady();

  wrapper = mount(AlertDetailPage, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("预警详情", () => {
  it("命中依据给出判定字段、实测值与阈值", async () => {
    const page = await mountPage(RISK_OFFICER);

    const table = page.get('[data-testid="rule-hits-table"]');
    expect(table.text()).toContain("交易金额");
    expect(table.text()).toContain("520000");
    expect(table.text()).toContain("≥ 500000");
  });

  it("没有结构化命中依据时回退到 trigger_detail", async () => {
    const page = await mountPage(RISK_OFFICER, {
      ...ALERT_DETAIL,
      rule_hits: [],
      trigger_detail: "多规则交叉命中",
    });

    expect(page.get('[data-testid="trigger-detail"]').text()).toContain("多规则交叉命中");
  });

  it("风控专员在未处理预警上能看到处置表单，理由为空时三个动作都点不动", async () => {
    const page = await mountPage(RISK_OFFICER);

    expect(page.find('[data-testid="disposition"]').exists()).toBe(true);
    expect(page.get('[data-testid="exclude-alert"]').attributes("disabled")).toBeDefined();
    expect(page.get('[data-testid="escalate-alert"]').attributes("disabled")).toBeDefined();
    expect(page.get('[data-testid="derive-work-order"]').attributes("disabled")).toBeDefined();

    await page.get('[data-testid="disposition-reason"]').setValue("核实为客户本人转账");
    expect(page.get('[data-testid="exclude-alert"]').attributes("disabled")).toBeUndefined();
  });

  it("理财顾问看不到处置表单，只看到一句说明", async () => {
    const page = await mountPage(ADVISOR);

    expect(page.find('[data-testid="disposition"]').exists()).toBe(false);
    expect(page.get('[data-testid="read-only-hint"]').text()).toContain("处置由风控专员完成");
  });

  it("已处置过的预警不再给处置入口", async () => {
    const page = await mountPage(RISK_OFFICER, {
      ...ALERT_DETAIL,
      status: "已排除",
      handled_by_name: "李风控",
      handle_result: "误报",
    });

    expect(page.find('[data-testid="disposition"]').exists()).toBe(false);
  });

  it("403 时显示无权查看", async () => {
    const page = await mountPage(ADVISOR, apiError(403, "该客户不在你的名下，无权查看"));

    expect(page.get('[data-testid="alert-forbidden"]').text()).toContain("无权查看");
  });

  it("排除动作只在理由填好后发出请求", async () => {
    const page = await mountPage(RISK_OFFICER);
    const fetchMock = vi.mocked(globalThis.fetch);

    await page.get('[data-testid="disposition-reason"]').setValue("客户已确认");
    await page.get('[data-testid="exclude-alert"]').trigger("click");
    await flushPromises();

    const calls = requestedUrls(fetchMock, "/exclude");
    expect(calls).toHaveLength(1);
    const init = fetchMock.mock.calls.find((call) =>
      String(call[0]).includes("/exclude"),
    )?.[1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ reason: "客户已确认" });
  });
});

// 来源标注（issue 09）：这条预警值不值得信，取决于那笔交易是谁发起的。
describe("预警来源", () => {
  it("客户自助发起的交易标成客户发起", async () => {
    const page = await mountPage(RISK_OFFICER);

    expect(page.get('[data-testid="alert-source"]').text()).toContain("客户发起");
  });

  it("内部补录的交易标成内部补录，并点明它没过业务校验", async () => {
    const page = await mountPage(RISK_OFFICER, {
      ...ALERT_DETAIL,
      source: "内部补录",
    });

    const source = page.get('[data-testid="alert-source"]');
    expect(source.text()).toContain("内部补录");
    expect(source.text()).toContain("未经适当性与余额校验");
  });
});
