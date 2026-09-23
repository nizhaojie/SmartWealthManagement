// 文档列表：筛选 + 分页 + 「处理中」轮询三者的协同（ADR-0024）。
//
// 分页给轮询出了两道题：定时器刷的必须是**当前页**（刷第一页会把正在看的第 3 页拽走），
// 以及这一页落定之后要停表。筛选则要保证翻页带着它、改筛选回第一页。
//
// 定时器只假造 `setInterval`/`clearInterval`：`flushPromises` 自己走 `setTimeout`，
// 连它一起假造，所有 await 都会停在那儿不动。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PageQuery } from "@wealth/shared";
import type { KnowledgeDocument } from "./types";

const { listDocuments, deleteDocument, uploadDocument } = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  uploadDocument: vi.fn(),
}));

// 上传与删除不在本文件的范围里，但组件在模块顶层就import 它们，桩里要有东西落。
vi.mock("./api", () => ({ listDocuments, deleteDocument, uploadDocument }));

import DocumentManagerPanel from "./DocumentManagerPanel.vue";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 1500;

function makeDocument(overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    knowledge_id: 1,
    knowledge_type: "FAQ",
    title: "随存随取说明",
    source_file: "faq.md",
    version: "1",
    status: "active",
    chunk_count: 3,
    expire_at: null,
    create_time: "2026-09-18T10:00:00",
    stage: null,
    failure_reason: null,
    ...overrides,
  };
}

function makePage(
  items: KnowledgeDocument[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

async function mountPanel(): Promise<VueWrapper> {
  activeWrapper = mount(DocumentManagerPanel, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return activeWrapper;
}

/**
 * 表单里的筛选走真实的控件：点开那一栏的下拉，再点中选项。
 *
 * 筛选挑**状态**这一栏：它的选项文案（已过期 / 处理中…）只出现在筛选项里；类型那一栏
 * 的选项与上传表单的类型下拉逐字相同，而那两个下拉同时挂在 body 上，按文案找会点错。
 * 两栏的取值走的是同一条路径（同一个闭包读筛选值），覆盖一栏即可。
 */
async function chooseOption(fieldLabel: string, optionLabel: string): Promise<void> {
  const field = activeWrapper!
    .findAll(".filters__field")
    .find((item) => item.get(".filters__label").text() === fieldLabel);
  expect(field, `找不到「${fieldLabel}」这一栏`).toBeTruthy();

  await field!.get(".el-select").trigger("click");
  await flushPromises();

  const option = [...document.querySelectorAll<HTMLElement>(".el-select-dropdown__item")].find(
    (item) => item.textContent?.trim() === optionLabel,
  );
  expect(option, `找不到选项「${optionLabel}」`).toBeTruthy();

  option!.click();
  await flushPromises();
}

function lastFilters(): Record<string, unknown> {
  return listDocuments.mock.calls.at(-1)![0] as Record<string, unknown>;
}

function lastQuery(): PageQuery {
  return listDocuments.mock.calls.at(-1)![1] as PageQuery;
}

function tableText(): string {
  return activeWrapper!.get('[data-testid="documents-table"]').text();
}

/** 筛选表单里只有这一个按钮：它的 loading 亮不亮就是「筛选按钮在不在切换状态」。 */
function filterButton(wrapper: VueWrapper) {
  return wrapper.get(".filters button");
}

describe("文档列表的筛选、分页与轮询", () => {
  beforeEach(() => {
    listDocuments.mockReset();
    deleteDocument.mockReset();
    listDocuments.mockResolvedValue(makePage([], 0));
    // 只假造定时器：`flushPromises` 走的是 `setTimeout`，连它一起假造就再也不返回了。
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
    vi.useRealTimers();
  });

  it("asks for the first page and shows how many documents there are in total", async () => {
    listDocuments.mockResolvedValue(makePage([makeDocument()], 45));
    const wrapper = await mountPanel();

    expect(listDocuments).toHaveBeenCalledWith({}, { page: 1, page_size: PAGE_SIZE });
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page and carries the status filter along", async () => {
    listDocuments.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeDocument({ title: query.page === 1 ? "第一页" : "第二页" })],
          45,
          query,
        ),
      ),
    );
    await mountPanel();

    // 下拉里显示的是「已过期」，交给接口的是状态标识。
    await chooseOption("状态", "已过期");
    expect(lastFilters().status).toBe("expired");
    expect(lastQuery().page).toBe(1);

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    // 少了筛选，第 2 页会变成「全部文档的第 2 页」，与筛选框里留着的状态对不上。
    expect(lastFilters().status).toBe("expired");
    expect(lastQuery().page).toBe(2);
    expect(tableText()).toContain("第二页");
    expect(tableText()).not.toContain("第一页");
  });

  it("goes back to the first page when the filter changes", async () => {
    listDocuments.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(makePage([makeDocument()], 45, query)),
    );
    await mountPanel();

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastQuery().page).toBe(2);

    await chooseOption("状态", "处理失败");

    expect(lastQuery().page).toBe(1);
  });

  it("polls the page it is on instead of pulling back to the first one", async () => {
    listDocuments.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(
        makePage(
          query.page === 1
            ? [makeDocument({ status: "active" })]
            : [makeDocument({ knowledge_id: 2, status: "processing" })],
          45,
          query,
        ),
      ),
    );
    await mountPanel();

    // 第一页没有处理中的文档：不该有定时器。推进一拍，请求数不变。
    const afterFirstPage = listDocuments.mock.calls.length;
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    await flushPromises();
    expect(listDocuments.mock.calls.length).toBe(afterFirstPage);

    await activeWrapper!.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastQuery().page).toBe(2);

    // 这一页有一份在入库：轮询刷的是第 2 页，不是把人拽回第 1 页。
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    await flushPromises();

    expect(lastQuery()).toEqual({ page: 2, page_size: PAGE_SIZE });
    expect(tableText()).toContain("处理中");
  });

  it("stops polling once nothing on the page is still being ingested", async () => {
    let processing = true;
    listDocuments.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(
        makePage([makeDocument({ status: processing ? "processing" : "active" })], 45, query),
      ),
    );
    await mountPanel();

    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    await flushPromises();
    const pollingCalls = listDocuments.mock.calls.length;
    expect(pollingCalls).toBe(2);

    // 入库落定：再推进几拍都不该再发请求。
    processing = false;
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    await flushPromises();
    const settled = listDocuments.mock.calls.length;

    vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    await flushPromises();

    expect(settled).toBe(3);
    expect(listDocuments.mock.calls.length).toBe(settled);
  });

  it("shows the filter button busy while the person's own request is in flight", async () => {
    let settle: (() => void) | null = null;
    listDocuments.mockImplementation(
      () =>
        new Promise((resolve) => {
          settle = () => resolve(makePage([], 0));
        }),
    );
    const wrapper = await mountPanel();

    expect(filterButton(wrapper).classes()).toContain("is-loading");

    settle!();
    await flushPromises();

    expect(filterButton(wrapper).classes()).not.toContain("is-loading");
  });

  it("leaves the filter button alone while the list refreshes itself in the background", async () => {
    let settlePoll: (() => void) | null = null;
    let calls = 0;
    listDocuments.mockImplementation((_filters, query: PageQuery) => {
      calls += 1;
      if (calls === 1) {
        return Promise.resolve(makePage([makeDocument({ status: "processing" })], 45, query));
      }
      return new Promise((resolve) => {
        settlePoll = () =>
          resolve(makePage([makeDocument({ status: "processing" })], 45, query));
      });
    });
    const wrapper = await mountPanel();
    expect(filterButton(wrapper).classes()).not.toContain("is-loading");

    // 一拍轮询还挂在路上：这是后台刷列表，不是人在等的那次取数。
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    await flushPromises();
    expect(filterButton(wrapper).classes()).not.toContain("is-loading");

    settlePoll!();
    await flushPromises();
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listDocuments.mockImplementation((_filters, query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeDocument()] : [], 45, query)),
    );
    const wrapper = await mountPanel();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="documents-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="documents-empty"]').text()).toContain("没有符合条件的文档");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("shows no pager at all when there is no document to page through", async () => {
    const wrapper = await mountPanel();

    expect(wrapper.get('[data-testid="documents-empty"]').text()).toContain("没有符合条件的文档");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("leaves the reason on screen when the load fails", async () => {
    listDocuments.mockRejectedValue(new Error("boom"));
    const wrapper = await mountPanel();

    expect(wrapper.get('[data-testid="document-error"]').text()).toContain("文档列表加载失败");
    expect(wrapper.find('[data-testid="documents-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
