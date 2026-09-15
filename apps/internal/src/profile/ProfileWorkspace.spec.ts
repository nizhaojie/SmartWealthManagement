import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CustomerProfileView, RiskAssessmentRecord } from "./types";

const { listCustomers, getCustomerProfile, listRiskAssessments, writeProfileTag } = vi.hoisted(
  () => ({
    listCustomers: vi.fn(),
    getCustomerProfile: vi.fn(),
    listRiskAssessments: vi.fn(),
    writeProfileTag: vi.fn(),
  }),
);

vi.mock("./api", () => ({
  listCustomers,
  getCustomerProfile,
  listRiskAssessments,
  writeProfileTag,
}));

import ProfileWorkspace from "./ProfileWorkspace.vue";

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
    ],
    conflict_records: [],
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

async function mountWorkspace() {
  const wrapper = mount(ProfileWorkspace, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

describe("ProfileWorkspace", () => {
  beforeEach(() => {
    listCustomers.mockReset();
    getCustomerProfile.mockReset();
    listRiskAssessments.mockReset();
    writeProfileTag.mockReset();
    listCustomers.mockResolvedValue([
      {
        id: 1,
        username: "wangc1",
        real_name: "王守成",
        customer_level: "普通",
        risk_level: "C1",
      },
    ]);
    getCustomerProfile.mockResolvedValue(makeProfile());
    listRiskAssessments.mockResolvedValue([]);
  });

  it("shows the selected customer's assessment history with grade changes", async () => {
    const history: RiskAssessmentRecord[] = [
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
    listRiskAssessments.mockResolvedValue(history);

    const wrapper = await mountWorkspace();
    const text = wrapper.text();

    expect(text).toContain("2020-05-01");
    expect(text).toContain("C1");
    expect(text).toContain("2022-03-15");
    expect(text).toContain("C3");
  });

  it("after an advisor correction, the tag shows the new source and confidence", async () => {
    writeProfileTag.mockResolvedValue(
      makeProfile({
        tags: [
          {
            key: "investment_experience",
            label: "投资经验",
            value: "3-5年",
            source: "理财顾问手工修正",
            confidence: 0.95,
            observed_at: "2026-09-15T09:00:00",
          },
        ],
      }),
    );

    const wrapper = await mountWorkspace();
    await wrapper.get("[data-test=correct-tag]").trigger("click");
    await wrapper.get('input[name="correction-value"]').setValue("3-5年");
    await wrapper.get('textarea[name="correction-reason"]').setValue("访谈确认已有三年实盘经验");
    await wrapper.get("[data-test=save-correction]").trigger("click");
    await flushPromises();

    expect(writeProfileTag).toHaveBeenCalledWith({
      customerId: 1,
      tagKey: "investment_experience",
      value: "3-5年",
      source: "理财顾问手工修正",
      reason: "访谈确认已有三年实盘经验",
    });
    expect(wrapper.text()).toContain("3-5年");
    expect(wrapper.text()).toContain("理财顾问手工修正");
    expect(wrapper.text()).toContain("0.95");
  });
});
