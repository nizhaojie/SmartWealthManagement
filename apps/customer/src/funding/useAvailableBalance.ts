// 可用余额的加载，资产页与交易页共用一个：两页都要「读余额、失败时留一句原因」，
// 各写一遍就会各有一种失败口径（一边说「加载失败」、一边把「—」当成余额为零）。
import { ref } from "vue";
import { ApiError } from "@wealth/shared";
import { getFundingAccount } from "./api";

export function useAvailableBalance() {
  const balance = ref("—");
  const error = ref("");

  async function load(): Promise<void> {
    error.value = "";
    try {
      balance.value = (await getFundingAccount()).available_balance;
    } catch (caught) {
      // 拉不到余额时给「—」而不是 0：零是在陈述一个事实，而这里只是没读到。
      balance.value = "—";
      error.value = caught instanceof ApiError ? caught.message : "可用余额加载失败";
    }
  }

  return { balance, error, load };
}
