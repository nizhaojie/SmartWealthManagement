// 历次风险评测：画像里的第一条独立列表，自己取数、自己翻页（ADR-0024）。
//
// 它缠着两件事：翻页取的是服务端的下一页，以及换客户回到第一页——停在第 3 页会看到
// 「这位客户没有记录」，而那不是他的历史。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RiskAssessmentRecord } from "./types";
import { apiError, requestedUrls, stubApiFetch, type ApiResponder } from "../testing";
import ProfileHistoryPanel from "./ProfileHistoryPanel.vue";

const PAGE_SIZE = 10;

function makeAssessment(id: number): RiskAssessmentRecord {
  return {
    id,
    assessment_date: `2026-05-${String((id % 28) + 1).padStart(2, "0")}`,
    risk_level: "C3",
    total_score: id,
    valid_until: "2027-05-01",
  };
}

let activeWrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

/** 最小服务端：按客户标识给 25 次评测，最近的在前，按页切。 */
function historyResponder() {
  return (url: string) => {
    if (!url.includes("/risk-assessments")) return undefined;
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const page = Number(query.get("page") ?? 1);
    const pageSize = Number(query.get("page_size") ?? PAGE_SIZE);
    const all = Array.from({ length: 25 }, (_, index) => makeAssessment(25 - index));
    const offset = (page - 1) * pageSize;
    return {
      items: all.slice(offset, offset + pageSize),
      total: all.length,
      page,
      page_size: pageSize,
    };
  };
}

async function mountPanel(
  customerId = 1,
  respond: ApiResponder = historyResponder(),
): Promise<VueWrapper> {
  fetchMock = stubApiFetch(respond);
  activeWrapper = mount(ProfileHistoryPanel, {
    props: { customerId, conflicts: [] },
    global: { plugins: [ElementPlus] },
  });
  await flushPromises();
  return activeWrapper;
}

function lastHistoryUrl(): string {
  return decodeURIComponent(requestedUrls(fetchMock, "/risk-assessments").at(-1) ?? "");
}

describe("历次风险评测的分页", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.unstubAllGlobals();
  });

  it("takes the first page of this customer and shows the total", async () => {
    const panel = await mountPanel(7);

    expect(lastHistoryUrl()).toContain("/customers/7/risk-assessments?page=1&page_size=10");
    expect(panel.get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
    expect(panel.get('[data-testid="assessment-history"]').findAll("li")).toHaveLength(PAGE_SIZE);
  });

  it("takes the next page from the server instead of slicing what it already has", async () => {
    const panel = await mountPanel();

    await panel.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastHistoryUrl()).toContain("page=2&page_size=10");
    expect(panel.get('[data-testid="assessment-history"]').findAll("li")).toHaveLength(PAGE_SIZE);
  });

  it("goes back to the first page when another customer is picked", async () => {
    const panel = await mountPanel(1);

    await panel.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastHistoryUrl()).toContain("page=2");

    await panel.setProps({ customerId: 2 });
    await flushPromises();

    expect(lastHistoryUrl()).toContain("/customers/2/risk-assessments?page=1");
  });

  it("says so when the customer has no assessment at all", async () => {
    const panel = await mountPanel(1, (url) =>
      url.includes("/risk-assessments")
        ? { items: [], total: 0, page: 1, page_size: PAGE_SIZE }
        : undefined,
    );

    expect(panel.get('[data-testid="assessment-empty"]').text()).toContain("还没有风险评测记录");
    expect(panel.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("leaves a reason instead of a stale history when the load fails", async () => {
    const panel = await mountPanel(1, () => apiError(500, "风险评测历史加载失败"));

    expect(panel.get('[data-testid="assessment-error"]').text()).toContain("风险评测历史加载失败");
    expect(panel.find('[data-testid="assessment-history"]').exists()).toBe(false);
    expect(panel.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
