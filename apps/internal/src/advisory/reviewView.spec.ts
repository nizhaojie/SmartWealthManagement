import { describe, expect, it } from "vitest";
import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER } from "../auth/identity";
import { canReview, isDecided, toCandidatePayload } from "./reviewView";
import type { EditableCandidate } from "./types";

function candidate(overrides: Partial<EditableCandidate> = {}): EditableCandidate {
  return {
    product_code: "P001",
    product_name: "稳健增利一号",
    product_type: "债券基金",
    risk_level: "R2",
    expected_return: "3.5",
    term_days: 365,
    composite_score: 88.2,
    score_breakdown: [],
    reason: "与目标配置一致",
    included: true,
    ...overrides,
  };
}

describe("审核动作的角色与载荷", () => {
  it("只有理财顾问能放行或驳回", () => {
    expect(canReview(ADVISOR)).toBe(true);
    expect(canReview(ACCOUNT_MANAGER)).toBe(false);
    expect(canReview(RISK_OFFICER)).toBe(false);
    expect(canReview(undefined)).toBe(false);
  });

  it("已放行与已驳回都算已决", () => {
    expect(isDecided("已放行")).toBe(true);
    expect(isDecided("已驳回")).toBe(true);
    expect(isDecided("待审")).toBe(false);
    expect(isDecided("处理中")).toBe(false);
    expect(isDecided(undefined)).toBe(false);
  });

  it("放行载荷只带勾选的候选，并剥掉前端专用的 included", () => {
    const payload = toCandidatePayload([
      candidate(),
      candidate({ product_code: "P002", included: false }),
    ]);

    expect(payload).toHaveLength(1);
    expect(payload[0].product_code).toBe("P001");
    expect(Object.keys(payload[0])).not.toContain("included");
  });
});
