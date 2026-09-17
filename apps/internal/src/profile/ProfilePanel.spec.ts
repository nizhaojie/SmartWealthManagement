import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ProfilePanel from "./ProfilePanel.vue";
import type { CustomerProfileView, Holding, RiskAssessmentRecord } from "./types";

// jsdom 里元素尺寸恒为 0，ECharts 拿不到画布尺寸就没有可布局的文字。
Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 480 });
Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, value: 220 });

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    product_code: "F000001",
    product_name: "天枢货币基金",
    product_type: "货币基金",
    product_risk_level: "R1",
    shares: "20000.0000",
    cost_amount: "20000.00",
    market_value: "20420.00",
    profit_loss: "420.00",
    profit_ratio: "2.1000",
    ...overrides,
  };
}

function makeProfile(overrides: Partial<CustomerProfileView> = {}): CustomerProfileView {
  return {
    customer_id: 1,
    real_name: "王守成",
    computed_at: "2022-03-16T09:00:00",
    tags: [
      {
        key: "investment_experience",
        label: "投资经验",
        value: "0-1年",
        source: "风评问卷",
        confidence: 0.9,
        observed_at: "2022-03-16T09:00:00",
      },
      {
        key: "annual_income_range",
        label: "收入区间",
        value: "10万以下",
        source: "客户自述",
        confidence: 0.55,
        observed_at: "2022-03-16T09:00:00",
      },
    ],
    conflict_records: [
      {
        tag_key: "investment_experience",
        old_value: "无",
        old_source: "默认值",
        new_value: "0-1年",
        new_source: "风评问卷",
        changed_at: "2022-03-16T09:00:00",
        reason: null,
      },
    ],
    judgement: {
      circuit_break: false,
      reasons: [],
      risk_level: "C2",
      dimension_scores: {
        基础属性: 43.33,
        投资经验: 20,
        风险偏好: 20,
        行为异常: 70,
      },
      weighted_score: 35.83,
    },
    ...overrides,
  };
}

function makeAssessments(): RiskAssessmentRecord[] {
  return [
    {
      id: 1,
      assessment_date: "2020-05-01",
      risk_level: "C1",
      total_score: 18,
      valid_until: "2021-05-01",
    },
    {
      id: 2,
      assessment_date: "2022-03-15",
      risk_level: "C3",
      total_score: 55,
      valid_until: "2023-03-15",
    },
  ];
}

function mountPanel(
  profile: CustomerProfileView,
  assessments: RiskAssessmentRecord[] = [],
  holdings: Holding[] = [],
) {
  return mount(ProfilePanel, {
    global: { plugins: [ElementPlus] },
    props: { profile, assessments, holdings },
  });
}

function makeTargetAllocationTag() {
  return {
    key: "target_allocation",
    label: "目标配置",
    value: { 股票: 40, 债券: 35, 现金: 15, 另类: 10 },
    source: "风评问卷",
    confidence: 0.9,
    observed_at: "2022-03-16T09:00:00",
  };
}

describe("ProfilePanel", () => {
  it("renders each tag's confidence and source", () => {
    const text = mountPanel(makeProfile()).text();
    expect(text).toContain("投资经验");
    expect(text).toContain("0-1年");
    expect(text).toContain("风评问卷");
    expect(text).toContain("0.90");
    expect(text).toContain("收入区间");
    expect(text).toContain("客户自述");
    expect(text).toContain("0.55");
  });

  it("shows the profile computation time", () => {
    expect(mountPanel(makeProfile()).text()).toContain("2022-03-16 09:00");
  });

  it("lets the advisor expand the four dimension scores", async () => {
    const wrapper = mountPanel(makeProfile());
    expect(wrapper.text()).not.toContain("43.33");

    await wrapper.get("[data-test=dimension-toggle]").trigger("click");
    await flushPromises();

    const text = wrapper.text();
    expect(text).toContain("基础属性");
    expect(text).toContain("43.33");
    expect(text).toContain("投资经验");
    expect(text).toContain("风险偏好");
    expect(text).toContain("行为异常");
    expect(text).toContain("70");
  });

  it("renders the circuit-break reason instead of a blank state", () => {
    const wrapper = mountPanel(
      makeProfile({
        judgement: {
          circuit_break: true,
          reasons: [{ code: "AGE_UNDER_18", message: "年龄不足 18 岁，需人工审核" }],
          risk_level: null,
          dimension_scores: null,
          weighted_score: null,
        },
      }),
    );

    const text = wrapper.text();
    expect(text).toContain("年龄不足 18 岁，需人工审核");
    expect(text).not.toContain("该模块尚未实现");
    expect(wrapper.find("[data-test=circuit-break]").exists()).toBe(true);
  });

  it("shows past risk assessments so the advisor can see grade changes", () => {
    const text = mountPanel(makeProfile(), makeAssessments()).text();
    expect(text).toContain("2020-05-01");
    expect(text).toContain("C1");
    expect(text).toContain("2022-03-15");
    expect(text).toContain("C3");
  });

  it("shows tag conflict history with the old value still visible", () => {
    const text = mountPanel(makeProfile()).get("[data-test=conflict-records]").text();
    expect(text).toContain("投资经验");
    expect(text).toContain("默认值");
    expect(text).toContain("无");
    expect(text).toContain("风评问卷");
    expect(text).toContain("0-1年");
    expect(text).toContain("被 风评问卷 改为");
  });

  it("warns when a tag's confidence is low", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "product_preference",
            label: "产品偏好",
            value: { 基金: ["货币基金"] },
            source: "默认值",
            confidence: 0.3,
            observed_at: "2022-03-16T09:00:00",
          },
        ],
      }),
    );

    expect(wrapper.find("[data-test=profile-warning]").exists()).toBe(true);
    expect(wrapper.text()).toContain("置信度偏低");
  });

  it("renders the confidence the backend decayed for this read, not the value at write time", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "0-1年",
            source: "风评问卷",
            confidence: 0.31,
            observed_at: "2022-03-16T09:00:00",
          },
        ],
      }),
    );

    expect(wrapper.text()).toContain("0.31");
    expect(wrapper.find("[data-test=profile-warning]").exists()).toBe(true);
  });

  it("marks a tag the periodic calibration flagged as expired", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "0-1年",
            source: "默认值",
            confidence: 0,
            observed_at: "2022-03-16T09:00:00",
            expired: true,
          },
        ],
      }),
    );

    expect(wrapper.get("[data-test=tag-expired]").text()).toBe("已过期");
    expect(wrapper.text()).toContain("0.00");
  });

  it("warns when the risk assessment has expired", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "0-1年",
            source: "风评问卷",
            confidence: 0.9,
            observed_at: "2022-03-16T09:00:00",
          },
        ],
        judgement: {
          circuit_break: true,
          reasons: [{ code: "ASSESSMENT_EXPIRED", message: "风险评测已过期，画像权限已冻结，请重新评估" }],
          risk_level: null,
          dimension_scores: null,
          weighted_score: null,
        },
      }),
    );

    expect(wrapper.find("[data-test=profile-warning]").exists()).toBe(true);
    expect(wrapper.text()).toContain("过期");
  });

  it("does not warn when tags are reliable and the assessment is current", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "0-1年",
            source: "风评问卷",
            confidence: 0.9,
            observed_at: "2022-03-16T09:00:00",
          },
        ],
        judgement: {
          circuit_break: false,
          reasons: [],
          risk_level: "C2",
          dimension_scores: {
            基础属性: 43.33,
            投资经验: 20,
            风险偏好: 20,
            行为异常: 70,
          },
          weighted_score: 35.83,
        },
      }),
      [
        {
          id: 1,
          assessment_date: "2026-01-01",
          risk_level: "C2",
          total_score: 36,
          valid_until: "2027-01-01",
        },
      ],
    );

    expect(wrapper.find("[data-test=profile-warning]").exists()).toBe(false);
  });

  it("does not treat an older expired assessment as making a current profile stale", () => {
    const wrapper = mountPanel(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "0-1年",
            source: "风评问卷",
            confidence: 0.9,
            observed_at: "2022-03-16T09:00:00",
          },
        ],
        conflict_records: [],
        judgement: {
          circuit_break: false,
          reasons: [],
          risk_level: "C3",
          dimension_scores: {
            基础属性: 43.33,
            投资经验: 20,
            风险偏好: 20,
            行为异常: 70,
          },
          weighted_score: 35.83,
        },
      }),
      [
        {
          id: 1,
          assessment_date: "2020-05-01",
          risk_level: "C1",
          total_score: 18,
          valid_until: "2021-05-01",
        },
        {
          id: 2,
          assessment_date: "2026-01-01",
          risk_level: "C3",
          total_score: 55,
          valid_until: "2027-01-01",
        },
      ],
    );

    expect(wrapper.find("[data-test=profile-warning]").exists()).toBe(false);
    expect(wrapper.text()).toContain("2020-05-01");
    expect(wrapper.text()).toContain("C1");
    expect(wrapper.text()).toContain("C3");
  });

  it("requires a reason before emitting an advisor correction", async () => {
    const wrapper = mountPanel(makeProfile());
    await wrapper.get("[data-test=correct-tag]").trigger("click");
    await wrapper.get('input[name="correction-value"]').setValue("3-5年");
    await wrapper.get("[data-test=save-correction]").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("手工修正必须填写理由");
    expect(wrapper.emitted("correct")).toBeUndefined();
  });

  it("emits the corrected value and reason so confidence and source can update", async () => {
    const wrapper = mountPanel(makeProfile());
    await wrapper.get("[data-test=correct-tag]").trigger("click");
    await wrapper.get('input[name="correction-value"]').setValue("3-5年");
    await wrapper.get('textarea[name="correction-reason"]').setValue("访谈确认已有三年实盘经验");
    await wrapper.get("[data-test=save-correction]").trigger("click");
    await flushPromises();

    expect(wrapper.emitted("correct")).toEqual([
      [{ tagKey: "investment_experience", value: "3-5年", reason: "访谈确认已有三年实盘经验" }],
    ]);
  });

  it("draws the target-vs-actual allocation chart when a target and holdings exist", async () => {
    const wrapper = mountPanel(
      makeProfile({ tags: [makeTargetAllocationTag()] }),
      [],
      [makeHolding()],
    );
    await flushPromises();

    const frame = wrapper.find('[data-testid="chart-frame"]');
    expect(frame.exists()).toBe(true);
    expect(frame.find("figcaption").text()).toBe("目标配置 vs 实际配置");
    expect(frame.find('[data-testid="chart-canvas"]').exists()).toBe(true);
  });

  it("keeps the same category order on both sides of the allocation chart", async () => {
    const wrapper = mountPanel(
      makeProfile({ tags: [makeTargetAllocationTag()] }),
      [],
      [makeHolding()],
    );
    await flushPromises();

    const labels = wrapper
      .find('[data-testid="chart-frame"]')
      .findAll("svg text")
      .map((node) => node.text())
      .filter((text) => ["现金", "债券", "混合", "股票", "另类"].includes(text));

    // 每个类别在图上出现两次（目标配置一次、实际配置一次），但类别本身
    // 先后顺序必须一致，否则同一行读到的就不是同一个类别。
    const order = [...new Set(labels)];
    expect(order).toEqual(["现金", "债券", "混合", "股票", "另类"]);
  });

  it("renders an empty state instead of a blank chart when there is no target or holdings data", () => {
    const wrapper = mountPanel(makeProfile(), [], []);

    const frame = wrapper.find('[data-testid="chart-frame"]');
    expect(frame.find('[data-testid="chart-empty"]').exists()).toBe(true);
    expect(frame.find('[data-testid="chart-canvas"]').exists()).toBe(false);
  });
});
