// 交易流水组件：四类记录并排在一张表里——转账行没有产品而有收款人，申赎行有产品而
// 没有收款人（ADR-0019、ADR-0023）。漏掉转账的那处 `INNER JOIN fin_product` 不会报错，
// 只会让那一行整行消失，所以这里专门盯「流水里有转账」。
import ElementPlus from "element-plus";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TransactionRecord } from "./types";

const { listTransactions } = vi.hoisted(() => ({ listTransactions: vi.fn() }));

vi.mock("./api", () => ({ listTransactions }));

import TransactionHistory from "./TransactionHistory.vue";

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

let activeWrapper: VueWrapper | null = null;

async function mountHistory(): Promise<VueWrapper> {
  activeWrapper = mount(TransactionHistory, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return activeWrapper;
}

describe("TransactionHistory", () => {
  beforeEach(() => {
    listTransactions.mockReset();
    listTransactions.mockResolvedValue({ transactions: [] });
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("renders 申购、赎回与转账 together, with the payee on the transfer row", async () => {
    listTransactions.mockResolvedValue({
      transactions: [
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
    });
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
  });
});
