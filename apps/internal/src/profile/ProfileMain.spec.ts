// 画像主体上的等级大字是**风险承受等级**（画像标签 `risk_level`），不是四维度研判算出来的
// 那个等级。两者可以不同——它们互为印证而不是同一个数——同屏出现时必须各说各的，
// 否则顾问读到的「C3 平衡型」会被当成客户的承受等级，而适当性按的是另一个（王守成实测：
// 标签与最近一次评测都是 C5，研判加权 59.83 落在 C3）。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { stubApiFetch } from "../testing";
import ProfileMain from "./ProfileMain.vue";
import type { CustomerProfileView } from "./types";

/** 王守成（客户 1）的实测画像：标签 C5，四维度研判 C3。 */
function profileFixture(overrides: Partial<CustomerProfileView> = {}): CustomerProfileView {
  return {
    customer_id: 1,
    real_name: "王守成",
    computed_at: "2026-09-28T23:07:37",
    tags: [
      {
        key: "risk_level",
        label: "风险承受等级",
        value: "C5",
        source: "理财顾问手工修正",
        confidence: 0.95,
        observed_at: "2026-09-28T23:07:37",
      },
      {
        key: "investment_experience",
        label: "投资经验",
        value: "0-1年",
        source: "风评问卷",
        confidence: 0.9,
        observed_at: "2022-03-16T01:00:00",
      },
    ],
    conflict_records: [],
    judgement: {
      circuit_break: false,
      reasons: [],
      risk_level: "C3",
      dimension_scores: { 基础属性: 43.33, 投资经验: 20, 风险偏好: 100, 行为异常: 70 },
      weighted_score: 59.83,
    },
    ...overrides,
  };
}

let activeWrapper: VueWrapper | null = null;

// 图表 / 图谱 / 评测历史三块各自取数与画布，与本次要看的两个字无关：替身掉，只留主体自己的记号。
const HEAVY_CHILDREN = {
  AllocationComparisonChart: true,
  ProfileHistoryPanel: true,
  CustomerGraphPanel: true,
};

function mountMain(profile: CustomerProfileView): VueWrapper {
  stubApiFetch();
  activeWrapper = mount(ProfileMain, {
    props: { profile, riskValidUntil: "2027-09-27", holdings: [], loading: false },
    global: { plugins: [ElementPlus], stubs: HEAVY_CHILDREN },
  });
  return activeWrapper;
}

describe("画像主体的等级大字", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.unstubAllGlobals();
  });

  it("shows the customer's risk capacity level, not the four-dimension judgement grade", async () => {
    const page = mountMain(profileFixture());
    await flushPromises();

    expect(page.get('[data-testid="risk-grade"]').text()).toBe("C5 激进型");
  });

  it("keeps the four-dimension judgement visible and names it as such", async () => {
    const page = mountMain(profileFixture());
    await flushPromises();

    const judgement = page.get('[data-testid="judgement-grade"]').text();
    expect(judgement).toContain("四维度研判");
    expect(judgement).toContain("C3 平衡型");
  });

  it("says nothing is assessed when the risk capacity tag is missing", async () => {
    const profile = profileFixture();
    profile.tags = profile.tags.filter((tag) => tag.key !== "risk_level");
    const page = mountMain(profile);
    await flushPromises();

    expect(page.get('[data-testid="risk-grade"]').text()).toBe("未评测");
  });

  it("keeps the circuit-break reasons instead of a grade when a hard threshold trips", async () => {
    const profile = profileFixture();
    profile.judgement = {
      circuit_break: true,
      reasons: [{ code: "ASSESSMENT_EXPIRED", message: "风险评测已过期，画像权限已冻结，请重新评估" }],
      risk_level: null,
      dimension_scores: null,
      weighted_score: null,
    };
    const page = mountMain(profile);
    await flushPromises();

    expect(page.get('[data-testid="circuit-break"]').text()).toContain("风险评测已过期");
    expect(page.find('[data-testid="risk-grade"]').exists()).toBe(false);
  });
});
