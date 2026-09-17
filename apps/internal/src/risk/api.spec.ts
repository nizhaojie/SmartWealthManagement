import { beforeEach, describe, expect, it, vi } from "vitest";

const { get, post, patch } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}));

vi.mock("../api/http", () => ({ http: { get, post, patch } }));

import {
  acceptWorkOrder,
  closeWorkOrder,
  completeWorkOrder,
  deriveWorkOrder,
  escalateAlert,
  excludeAlert,
  getAlert,
  getWorkOrder,
  listAlerts,
  listRiskRules,
  listWorkOrders,
  setRiskRuleEnabled,
} from "./api";

function paramsOf(url: string): URLSearchParams {
  const [, search = ""] = url.split("?");
  return new URLSearchParams(search);
}

describe("risk api", () => {
  beforeEach(() => {
    get.mockReset().mockResolvedValue([]);
    post.mockReset();
    patch.mockReset();
  });

  it("maps every alert filter onto the snake_case parameters the backend reads", async () => {
    await listAlerts({
      alertLevel: "重度",
      status: "未处理",
      createdFrom: "2026-09-01T00:00:00.000Z",
      createdTo: "2026-09-30T23:59:59.000Z",
    });

    const [url] = get.mock.calls[0];
    expect(url.startsWith("/api/internal/risk-alerts?")).toBe(true);
    const params = paramsOf(url);
    expect(params.get("alert_level")).toBe("重度");
    expect(params.get("status")).toBe("未处理");
    expect(params.get("created_from")).toBe("2026-09-01T00:00:00.000Z");
    expect(params.get("created_to")).toBe("2026-09-30T23:59:59.000Z");
    expect([...params.keys()].sort()).toEqual([
      "alert_level",
      "created_from",
      "created_to",
      "status",
    ]);
  });

  it("sends no query string at all when nothing is filtered", async () => {
    await listAlerts();

    expect(get).toHaveBeenCalledWith("/api/internal/risk-alerts");
  });

  it("drops empty filters instead of sending blank parameters", async () => {
    await listAlerts({ alertLevel: undefined, status: undefined, createdFrom: "", createdTo: "" });

    expect(get).toHaveBeenCalledWith("/api/internal/risk-alerts");
  });

  it("reads one alert by its own URL so the detail page can be linked to", async () => {
    get.mockResolvedValue({});

    await getAlert(12);

    expect(get).toHaveBeenCalledWith("/api/internal/risk-alerts/12");
  });

  it("posts a disposition with its reason", async () => {
    post.mockResolvedValue({});

    await excludeAlert(12, "客户资金来源为工资卡，误报");
    await escalateAlert(12, "超出我的处置权限");

    expect(post).toHaveBeenNthCalledWith(1, "/api/internal/risk-alerts/12/exclude", {
      reason: "客户资金来源为工资卡，误报",
    });
    expect(post).toHaveBeenNthCalledWith(2, "/api/internal/risk-alerts/12/escalate", {
      reason: "超出我的处置权限",
    });
  });

  it("derives a work order from an alert with its reason", async () => {
    post.mockResolvedValue({});

    await deriveWorkOrder(12, "金额与实际收入不匹配");

    expect(post).toHaveBeenCalledWith("/api/internal/risk-alerts/12/work-orders", {
      reason: "金额与实际收入不匹配",
    });
  });

  it("sends the work order status filter and reads transitions from the detail URL", async () => {
    await listWorkOrders({ status: "处理中" });
    await getWorkOrder(5);

    expect(paramsOf(get.mock.calls[0][0]).get("status")).toBe("处理中");
    expect(get).toHaveBeenNthCalledWith(2, "/api/internal/work-orders/5");
  });

  it("uses one named endpoint per transition so the required fields stay explicit", async () => {
    post.mockResolvedValue({});

    await acceptWorkOrder(5, "我来核实");
    await completeWorkOrder(5, { reason: "核实完毕", conclusion: "资金合法" });
    await closeWorkOrder(5, { reason: "客户已销户", conclusion: "" });

    expect(post).toHaveBeenNthCalledWith(1, "/api/internal/work-orders/5/accept", {
      reason: "我来核实",
    });
    expect(post).toHaveBeenNthCalledWith(2, "/api/internal/work-orders/5/complete", {
      reason: "核实完毕",
      conclusion: "资金合法",
    });
    expect(post).toHaveBeenNthCalledWith(3, "/api/internal/work-orders/5/close", {
      reason: "客户已销户",
      conclusion: "",
    });
  });

  it("reads the rule catalogue and toggles one rule with PATCH", async () => {
    patch.mockResolvedValue({});

    await listRiskRules();
    await setRiskRuleEnabled(4, false);

    expect(get).toHaveBeenCalledWith("/api/internal/risk-rules");
    expect(patch).toHaveBeenCalledWith("/api/internal/risk-rules/4/enabled", {
      enabled: false,
      reason: "",
    });
  });
});
