// 充值的两条拒绝理由与申购、赎回、转账走同一条失败翻译（`describeAcceptanceFailure`）：
// 受理侧原文原样透传，且都不给「去风险测评」入口——风评门槛只属于申购（Q7）。
// 「交易金额必须大于零」是受理侧 `NON_POSITIVE_AMOUNT_MESSAGE` 的原文（issue 里的
// 「金额必须大于零」是它的简称）。
import { describe, expect, it } from "vitest";
import { ApiError } from "@wealth/shared";
import { describeAcceptanceFailure } from "./failure";

function apiError(code: number, message: string): ApiError {
  return new ApiError({ code, message, data: null, trace_id: "t-1" });
}

describe("describeAcceptanceFailure（充值）", () => {
  it("金额必须大于零：原文透传，不给测评入口", () => {
    const failure = describeAcceptanceFailure(
      apiError(400, "交易金额必须大于零"),
      "充值失败，请稍后重试",
    );

    expect(failure.message).toBe("交易金额必须大于零");
    expect(failure.assessmentRequired).toBe(false);
  });

  it("资金账户不存在：原文透传，不给测评入口", () => {
    const failure = describeAcceptanceFailure(
      apiError(404, "资金账户不存在"),
      "充值失败，请稍后重试",
    );

    expect(failure.message).toBe("资金账户不存在");
    expect(failure.assessmentRequired).toBe(false);
  });
});
