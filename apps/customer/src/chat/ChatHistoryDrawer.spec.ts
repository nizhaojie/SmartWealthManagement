// 历史记录抽屉的分页（ADR-0024）：历史会话没有上限，列表靠翻页逐页取。
//
// 抽屉自己取数（`history.ts` 被 mock 掉），因此这里盯的是抽屉自己的行为：打开取的是
// 第一页、翻页换的是服务端的下一页、每次打开都回到第一页、加载失败与两种「空」各说
// 各的话，以及详情视图里没有分页条——回看的是这一场会话，与列表的页长无关。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type Paginated, type PageQuery } from "@wealth/shared";
import type { CustomerSessionDetail, CustomerSessionSummary } from "./history";

const { listCustomerConversations, getCustomerConversation } = vi.hoisted(() => ({
  listCustomerConversations: vi.fn(),
  getCustomerConversation: vi.fn(),
}));

vi.mock("./history", () => ({ listCustomerConversations, getCustomerConversation }));

import ChatHistoryDrawer from "./ChatHistoryDrawer.vue";

const PAGE_SIZE = 10;

function makeSession(sessionId: string): CustomerSessionSummary {
  return {
    session_id: sessionId,
    title: `第 ${sessionId} 场`,
    message_count: 2,
    started_at: "2026-09-20T09:00:00",
    ended_at: "2026-09-20T09:05:00",
  };
}

/** 历史会话接口的一页（ADR-0024）：形状恒为 `{items, total, page, page_size}`。 */
function makePage(
  items: CustomerSessionSummary[],
  overrides: Partial<Paginated<CustomerSessionSummary>> = {},
): Paginated<CustomerSessionSummary> {
  return { items, total: items.length, page: 1, page_size: PAGE_SIZE, ...overrides };
}

function makeDetail(sessionId: string): CustomerSessionDetail {
  return {
    session_id: sessionId,
    started_at: "2026-09-20T09:00:00",
    ended_at: "2026-09-20T09:05:00",
    messages: [
      {
        role: "user",
        content: "你好",
        citations: [],
        created_at: "2026-09-20T09:00:00",
        data: null,
      },
      {
        role: "assistant",
        content: "你好呀",
        citations: [],
        created_at: "2026-09-20T09:01:00",
        data: null,
      },
    ],
  };
}

/** 一轮数据问答的归档（ADR-0028）：assistant 那一行带结构化结果，提问行没有。 */
function makeDataDetail(sessionId: string): CustomerSessionDetail {
  return {
    session_id: sessionId,
    started_at: "2026-09-20T09:00:00",
    ended_at: "2026-09-20T09:05:00",
    messages: [
      {
        role: "user",
        content: "我持有哪些产品",
        citations: [],
        created_at: "2026-09-20T09:00:00",
        data: null,
      },
      {
        role: "assistant",
        content: "为您查到 1 行数据，已列在下表。数据口径：您当前持有的产品。",
        citations: [],
        created_at: "2026-09-20T09:01:00",
        data: {
          columns: [
            { key: "product_name", label: "产品名称" },
            { key: "market_value", label: "市值（元）" },
          ],
          rows: [["稳健增利", 120000]],
          row_count: 1,
          truncated: false,
          views: ["持仓明细"],
        },
      },
    ],
  };
}

let activeWrapper: VueWrapper | null = null;

/**
 * 打开抽屉：真实用法是先挂成关闭、再打开（`open` 由 false 变 true 才触发取数）。
 *
 * `teleport: true` 把 el-drawer 的传送门就地渲染：抽屉默认挂到 body 上，
 * 不然用例只能去 `document.body` 里翻。
 */
async function openDrawer(): Promise<VueWrapper> {
  activeWrapper = mount(ChatHistoryDrawer, {
    props: { open: false },
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  });
  await activeWrapper.setProps({ open: true });
  await flushPromises();
  return activeWrapper;
}

function lastQuery(): PageQuery {
  return vi.mocked(listCustomerConversations).mock.calls.at(-1)?.[0] as PageQuery;
}

describe("ChatHistoryDrawer", () => {
  beforeEach(() => {
    vi.mocked(listCustomerConversations).mockReset();
    vi.mocked(getCustomerConversation).mockReset();
    vi.mocked(listCustomerConversations).mockResolvedValue(makePage([]));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("打开时取第一页并给出过滤后的总数", async () => {
    vi.mocked(listCustomerConversations).mockResolvedValue(
      makePage([makeSession("s-1")], { total: 45 }),
    );

    const wrapper = await openDrawer();

    expect(listCustomerConversations).toHaveBeenCalledWith({ page: 1, page_size: PAGE_SIZE });
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
    expect(wrapper.get('[data-testid="history-item"]').text()).toContain("第 s-1 场");
  });

  it("翻页换的是服务端的下一页", async () => {
    vi.mocked(listCustomerConversations).mockImplementation((query: PageQuery) =>
      Promise.resolve(
        query.page === 1
          ? makePage([makeSession("s-1")], { total: 21 })
          : makePage([makeSession("s-2")], { total: 21, page: 2 }),
      ),
    );

    const wrapper = await openDrawer();
    expect(wrapper.get('[data-testid="history-item"]').text()).toContain("第 s-1 场");

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastQuery()).toEqual({ page: 2, page_size: PAGE_SIZE });
    const items = wrapper.findAll('[data-testid="history-item"]');
    expect(items).toHaveLength(1);
    expect(items[0].text()).toContain("第 s-2 场");
    // 总数不随翻页变：它是过滤后的总数，不是本页条数。
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });

  it("每次打开都从第一页重取", async () => {
    vi.mocked(listCustomerConversations).mockImplementation((query: PageQuery) =>
      Promise.resolve(makePage([makeSession("s-1")], { total: 21, page: query.page })),
    );

    const wrapper = await openDrawer();
    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastQuery().page).toBe(2);

    await wrapper.setProps({ open: false });
    await wrapper.setProps({ open: true });
    await flushPromises();

    // 上次停在第 2 页不该带到这一次来。
    expect(lastQuery().page).toBe(1);
  });

  it("加载失败时留一句原因，而不是一份空历史", async () => {
    vi.mocked(listCustomerConversations).mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "t-1" }),
    );

    const wrapper = await openDrawer();

    expect(wrapper.get('[data-testid="history-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("一条历史都没有时说「暂无历史记录」，也不给分页条", async () => {
    const wrapper = await openDrawer();

    expect(wrapper.get('[data-testid="history-empty"]').text()).toContain("暂无历史记录");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="history-page-empty"]').exists()).toBe(false);
  });

  it("把空页与「没有历史」分开", async () => {
    // 数据在两次取数之间变少，或页码跑到了末页之后：一条也拿不到，但总数说是有的。
    vi.mocked(listCustomerConversations).mockResolvedValue(
      makePage([], { total: 45, page: 99 }),
    );

    const wrapper = await openDrawer();

    expect(wrapper.get('[data-testid="history-page-empty"]').text()).toContain("前面几页");
    expect(wrapper.find('[data-testid="history-empty"]').exists()).toBe(false);
    // 分页条仍在：人得靠它翻回去。
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("详情是这一场会话本身，列表的页码与它无关", async () => {
    vi.mocked(listCustomerConversations).mockResolvedValue(
      makePage([makeSession("s-1")], { total: 45 }),
    );
    vi.mocked(getCustomerConversation).mockResolvedValue(makeDetail("s-1"));

    const wrapper = await openDrawer();
    await wrapper.get('[data-testid="history-item"]').trigger("click");
    await flushPromises();

    const detail = wrapper.get('[data-testid="history-detail"]');
    expect(detail.text()).toContain("你好呀");
    // 详情视图里没有分页条：详情不分页。
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);

    await wrapper.get('[data-testid="history-back"]').trigger("click");
    await flushPromises();

    // 回列表仍在原来那一页：列表没有被重取一次。
    expect(wrapper.find('[data-testid="history-detail"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
    expect(listCustomerConversations).toHaveBeenCalledTimes(1);
  });

  // 文本收敛之后回看里那一轮只剩「N 行 + 口径」，表必须一起归档、一起重绘（ADR-0028）：
  // 实时与回看看到的是同一张表，渲染的是同一个组件。
  it("回看里那一轮数据回答带出当时那张表，知识问答那轮没有表", async () => {
    vi.mocked(listCustomerConversations).mockResolvedValue(makePage([makeSession("s-1")]));
    vi.mocked(getCustomerConversation).mockResolvedValue(makeDataDetail("s-1"));

    const wrapper = await openDrawer();
    await wrapper.get('[data-testid="history-item"]').trigger("click");
    await flushPromises();

    const detail = wrapper.get('[data-testid="history-detail"]');
    const table = detail.get('[data-testid="data-answer-table"]');
    expect(table.findAll("thead th").map((th) => th.text())).toEqual(["产品名称", "市值（元）"]);
    expect(table.find("tbody tr").text()).toContain("稳健增利");
    expect(detail.get('[data-testid="data-answer-count"]').text()).toContain("共 1 行");
  });

  it("详情里没有表的那一轮不留下空壳", async () => {
    vi.mocked(listCustomerConversations).mockResolvedValue(makePage([makeSession("s-1")]));
    vi.mocked(getCustomerConversation).mockResolvedValue(makeDetail("s-1"));

    const wrapper = await openDrawer();
    await wrapper.get('[data-testid="history-item"]').trigger("click");
    await flushPromises();

    const detail = wrapper.get('[data-testid="history-detail"]');
    expect(detail.text()).toContain("你好呀");
    expect(detail.find('[data-testid="data-answer"]').exists()).toBe(false);
  });
});
