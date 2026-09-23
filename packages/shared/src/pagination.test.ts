// `usePagination` 的三件事：拿哪一对参数去取数、把返回的 items/total 落地、
// 取不到时不留旧数据。它不碰 DOM，因此跑在 node 环境里。
//
// 这里刻意用「一页行」这种与技术无关的造数（`{ id }`），不借任何业务的形状：
// shared 是两端共用的层，业务词汇一旦写进这里就会跟着进两端产物（ADR-0003）。
import { describe, expect, it, vi } from "vitest";
import { ApiError, type Envelope } from "./http";
import { DEFAULT_PAGE_SIZE, usePagination } from "./pagination";

type Row = { id: string };

function page(rows: Row[], total: number, query = { page: 1, page_size: DEFAULT_PAGE_SIZE }) {
  return { items: rows, total, page: query.page, page_size: query.page_size };
}

function apiError(message: string): ApiError {
  const envelope: Envelope<null> = { code: 500, message, data: null, trace_id: "t-1" };
  return new ApiError(envelope);
}

/** 取数桩：把请求的窗口原样回传——服务端就是这么回话的。 */
function echoLoad(total: number) {
  return vi.fn().mockImplementation((query: { page: number; page_size: number }) =>
    Promise.resolve(page([], total, query)),
  );
}

describe("usePagination", () => {
  it("asks for the first page with the shared default page size", async () => {
    const load = vi.fn().mockResolvedValue(page([{ id: "R1" }], 1));
    const pagination = usePagination<Row>(load);

    await pagination.refresh();

    expect(load).toHaveBeenCalledWith({ page: 1, page_size: DEFAULT_PAGE_SIZE });
    expect(pagination.items.value).toEqual([{ id: "R1" }]);
    expect(pagination.total.value).toBe(1);
    expect(pagination.loading.value).toBe(false);
    expect(pagination.errorMessage.value).toBe("");
  });

  it("takes the page size from the caller when one is given", async () => {
    const load = vi.fn().mockResolvedValue(page([], 0, { page: 1, page_size: 50 }));
    const pagination = usePagination<Row>(load, { pageSize: 50 });

    await pagination.refresh();

    expect(load).toHaveBeenCalledWith({ page: 1, page_size: 50 });
  });

  it("fetches the page it was sent to", async () => {
    const load = echoLoad(40);
    const pagination = usePagination<Row>(load);

    await pagination.refresh();
    await pagination.goTo(2);

    expect(load).toHaveBeenLastCalledWith({ page: 2, page_size: DEFAULT_PAGE_SIZE });
    expect(pagination.page.value).toBe(2);
  });

  it("does not refetch when the pager repeats the page it is already on", async () => {
    const load = echoLoad(40);
    const pagination = usePagination<Row>(load);

    await pagination.refresh();
    await pagination.goTo(1);

    expect(load).toHaveBeenCalledTimes(1);
  });

  it("goes back to the first page when the filters change", async () => {
    // 停在第 3 页看完筛选结果，会看到「筛选后为空」——那不是筛选的结果，是页码的。
    const load = echoLoad(40);
    const pagination = usePagination<Row>(load);

    await pagination.goTo(3);
    expect(pagination.page.value).toBe(3);

    await pagination.reset();

    expect(pagination.page.value).toBe(1);
    expect(load).toHaveBeenLastCalledWith({ page: 1, page_size: DEFAULT_PAGE_SIZE });
  });

  it("keeps the total from the server response, not the length of the page", async () => {
    const load = vi.fn().mockResolvedValue(page([{ id: "R1" }], 45));
    const pagination = usePagination<Row>(load);

    await pagination.refresh();

    expect(pagination.items.value).toHaveLength(1);
    expect(pagination.total.value).toBe(45);
  });

  it("adopts the window the server actually served when the page size was clamped", async () => {
    // 页长超上限会在后端被钳到 100。前端若还按 200 算总页数，而服务端按 100 切片，
    // 翻页就会重读或漏读——两边各自的数字都是「对」的，错在它们不是同一个数。
    const load = vi.fn().mockResolvedValue(page([], 300, { page: 1, page_size: 100 }));
    const pagination = usePagination<Row>(load, { pageSize: 200 });

    await pagination.refresh();

    expect(pagination.pageSize.value).toBe(100);
    expect(pagination.page.value).toBe(1);
  });

  it("drops the previous page and its total when a load fails", async () => {
    // 留着上一页的记录，页面会在「加载失败」下面继续显示一批数据，而那个总数
    // 还会继续驱动翻页控件——两处都在陈述没发生过的事。
    const load = vi
      .fn()
      .mockResolvedValueOnce(page([{ id: "R1" }], 45))
      .mockRejectedValueOnce(apiError("服务内部错误"));
    const pagination = usePagination<Row>(load);

    await pagination.refresh();
    await pagination.goTo(2);

    expect(pagination.items.value).toEqual([]);
    expect(pagination.total.value).toBe(0);
    expect(pagination.errorMessage.value).toBe("服务内部错误");
    expect(pagination.loading.value).toBe(false);
  });

  it("falls back to the caller's own wording for an unknown failure", async () => {
    const load = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    const pagination = usePagination<Row>(load, { failureMessage: "这一页加载失败" });

    await pagination.refresh();

    expect(pagination.errorMessage.value).toBe("这一页加载失败");
  });
});
