import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import ProfilePanel from "./ProfilePanel.vue";
import type { CustomerProfileView } from "./types";

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

function mountPanel(profile: CustomerProfileView) {
  return mount(ProfilePanel, {
    global: { plugins: [ElementPlus] },
    props: { profile },
  });
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
    expect(mountPanel(makeProfile()).text()).toContain("2022-03-16");
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
});
