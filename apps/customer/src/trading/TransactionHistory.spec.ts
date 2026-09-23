// 交易流水组件：四类记录并排在一张表里——转账行没有产品而有收款人，申赎行有产品而
// 没有收款人（ADR-0019、ADR-0023）。漏掉转账的那处 `INNER JOIN fin_product` 不会报错，
// 只会让那一行整行消失，所以这里专门盯「流水里有转账」。
//
// 分页这一侧盯两件事：翻页真的换了数据（不是只改了控件上的数字），以及翻页时筛选条件
// 原样带走——少了筛选，第 2 页会变成「全部记录的第 2 页」，与页面上还留着的筛选条件
// 对不上，而看起来完全正常。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@wealth/shared";
import type { PageQuery } from "@wealth/shared";
import type { TransactionFilters, TransactionRecord } from "./types";

const { listTransactions } = vi.hoisted(() => ({ listTransactions: vi.fn() }));

vi.mock("./api", () => ({ listTransactions }));

import TransactionHistory from "./TransactionHistory.vue";

const PAGE_SIZE = 20;

function makeFlow(overrides: Partial<TransactionRecord> = {}): TransactionRecord {
  return {
    transaction_no: "TR20260921ABCDEF",
    transaction_type: "转账",
    product_code: null,
    product_name: null,
    amount: "500000.00",
    shares: null,
    nav: null,
    fee: null,
    status: "已确认",
    traded_at: "2026-09-21T09:00:00",
    payee_name: "张三",
    payee_account: "6222020200112233",
    ...overrides,
  };
}

function makePage(
  items: TransactionRecord[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

async function mountHistory(): Promise<VueWrapper> {
  activeWrapper = mount(TransactionHistory, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return activeWrapper;
}

/** 表单里的筛选条件走真实的控件：选一项类型，再提交筛选。 */
async function chooseTransactionType(label: string): Promise<void> {
  await activeWrapper!.get(".filters .el-select").trigger("click");
  await flushPromises();
  const option = [...document.querySelectorAll<HTMLElement>(".el-select-dropdown__item")].find(
    (item) => item.textContent?.trim() === label,
  );
  expect(option).toBeTruthy();
  option!.click();
  await flushPromises();
}

async function submitFilters(): Promise<void> {
  await activeWrapper!.get(".filters").trigger("submit.prevent");
  await flushPromises();
}

function lastCall(): [TransactionFilters, PageQuery] {
  return listTransactions.mock.calls.at(-1) as [TransactionFilters, PageQuery];
}

describe("TransactionHistory", () => {
  beforeEach(() => {
    listTransactions.mockReset();
    listTransactions.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("renders 申购、赎回与转账 together, with the payee on the transfer row", async () => {
    listTransactions.mockResolvedValue(
      makePage(
        [
          makeFlow(),
          makeFlow({
            transaction_no: "TR20260920AAAAAA",
            transaction_type: "赎回",
            product_code: "F000001",
            product_name: "天枢货币基金",
            shares: "1000.0000",
            nav: "1.0000",
            fee: "1.00",
            payee_name: null,
            payee_account: null,
          }),
        ],
        2,
      ),
    );
    const wrapper = await mountHistory();

    const transfer = wrapper.get('[data-transaction-type="转账"]');
    expect(transfer.text()).toContain("张三");
    expect(transfer.text()).toContain("6222020200112233");
    // 转账没有产品：这一格是「—」，不是空白，也不是某只产品的名字。
    expect(transfer.text()).toContain("—");
    expect(transfer.text()).not.toContain("天枢货币基金");

    const redemption = wrapper.get('[data-transaction-type="赎回"]');
    expect(redemption.text()).toContain("天枢货币基金");
    expect(redemption.text()).not.toContain("张三");
  });

  it("leaves an explanation instead of a blank history when there is no transaction", async () => {
    const wrapper = await mountHistory();

    expect(wrapper.get('[data-testid="transactions-empty"]').text()).toContain(
      "没有符合条件的交易记录",
    );
    // 一条记录都没有时不给翻页条：那是「没有流水」，不是「还有第 2 页」。
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("asks for the first page and shows how many there are in total", async () => {
    listTransactions.mockResolvedValue(makePage([makeFlow()], 45));
    const wrapper = await mountHistory();

    expect(listTransactions).toHaveBeenCalledWith(
      { start_date: null, end_date: null, transaction_type: "" },
      { page: 1, page_size: PAGE_SIZE },
    );
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("turns the page and shows the rows of the page it landed on", async () => {
    listTransactions.mockImplementation((_filters: TransactionFilters, query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeFlow({ transaction_no: query.page === 1 ? "TR-PAGE1" : "TR-PAGE2" })],
          21,
          query,
        ),
      ),
    );
    const wrapper = await mountHistory();

    expect(wrapper.get('[data-testid="transactions-table"]').text()).toContain("TR-PAGE1");

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastCall()[1]).toEqual({ page: 2, page_size: PAGE_SIZE });
    const table = wrapper.get('[data-testid="transactions-table"]').text();
    expect(table).toContain("TR-PAGE2");
    expect(table).not.toContain("TR-PAGE1");
    // 总数不随翻页变：它是过滤后的总数，不是本页条数。
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });

  it("carries the filters into the next page instead of silently dropping them", async () => {
    listTransactions.mockImplementation((_filters: TransactionFilters, query: PageQuery) =>
      Promise.resolve(makePage([makeFlow()], 45, query)),
    );
    const wrapper = await mountHistory();

    await chooseTransactionType("转账");
    await submitFilters();

    expect(lastCall()[0].transaction_type).toBe("转账");
    expect(lastCall()[1].page).toBe(1);

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastCall()[0].transaction_type).toBe("转账");
    expect(lastCall()[1].page).toBe(2);
  });

  it("goes back to the first page when the filters change", async () => {
    // 停在第 3 页再改筛选，看到的会是「筛选后为空」——那不是筛选的结果，是页码的。
    listTransactions.mockImplementation((_filters: TransactionFilters, query: PageQuery) =>
      Promise.resolve(makePage([makeFlow()], 45, query)),
    );
    const wrapper = await mountHistory();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastCall()[1].page).toBe(2);

    await submitFilters();

    expect(lastCall()[1].page).toBe(1);
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    // 翻到的那一页没有记录（越界，或记录在这两次取数之间变少了）：服务端给空 items
    // 而 total 不变。空态要说清楚，但翻页条必须留着——撤掉它，人就困在这一页上。
    listTransactions.mockImplementation((_filters: TransactionFilters, query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeFlow()] : [], 21, query)),
    );
    const wrapper = await mountHistory();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="transactions-table"]').exists()).toBe(false);
    expect(wrapper.get('[data-testid="transactions-empty"]').text()).toContain(
      "没有符合条件的交易记录",
    );
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("leaves the reason on screen instead of an empty history when the load fails", async () => {
    listTransactions.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "t-1" }),
    );
    const wrapper = await mountHistory();

    expect(wrapper.get('[data-testid="transactions-error"]').text()).toContain("服务内部错误");
    expect(wrapper.find('[data-testid="transactions-empty"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});
