// 「我的建议」的数据源，同时喂侧栏的待决定角标。
//
// 页面按状态分组渲染，壳只数「待客户决定」的条数，两处读的是同一个列表接口——但读法
// 不同：页面要的是混合状态的一页（分组在页内现分），角标要的是「待决定共几条」。
// 列表分页之后（ADR-0024）本页条数不再等于全局条数，所以角标走的是同一接口的
// `status` 过滤后 `total`，而不是本页条数——分页不该让「还有几件在等」变少。
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { usePagination } from "@wealth/shared";
import { countAwaitingAdvice, decideAdvice, listMyAdvice } from "../operation-advice/api";
import {
  ADVICE_ACCEPTED,
  ADVICE_AWAITING,
  ADVICE_EXPIRED,
  ADVICE_REJECTED,
  type AdviceDecision,
  type AdviceStatus,
  type OperationAdvice,
} from "../operation-advice/types";

export const useAdviceStore = defineStore("advice", () => {
  const pagination = usePagination<OperationAdvice>((query) => listMyAdvice(query), {
    failureMessage: "操作建议加载失败",
  });

  // 「拉取成功」与「一条都没有」要分得开：接口故障不该被说成「还没有建议」。
  const loaded = ref(false);
  // 角标：待客户决定的总数。`undefined` 是「还不知道」——`0` 是一句断言
  // （「没有待办」），在还没取到或取失败时不能这么说。
  const pendingCount = ref<number | undefined>(undefined);

  // 分组按**当前页**的条目现分：四个分组不是四份数据，翻页只换窗口，
  // 「哪一条在等客户决定」始终由服务端算出来的状态说了算。
  const group = (status: AdviceStatus) =>
    computed(() => pagination.items.value.filter((item) => item.status === status));

  const awaiting = group(ADVICE_AWAITING);
  const accepted = group(ADVICE_ACCEPTED);
  const rejected = group(ADVICE_REJECTED);
  const expired = group(ADVICE_EXPIRED);

  async function loadPendingCount(): Promise<void> {
    try {
      pendingCount.value = await countAwaitingAdvice();
    } catch {
      pendingCount.value = undefined;
    }
  }

  async function refresh(): Promise<void> {
    await pagination.refresh();
    loaded.value = pagination.errorMessage.value === "";
    await loadPendingCount();
  }

  /**
   * 接受或拒绝。成功之后重新拉一次列表（状态由服务端现算，本地不推导）；
   * 失败时**不刷新**——受理校验没过，建议仍留在待客户决定，把原因交给调用方渲染。
   */
  async function decide(adviceId: number, decision: AdviceDecision): Promise<void> {
    await decideAdvice(adviceId, decision);
    await refresh();
  }

  /** 清空（登录 / 登出时调用）：会话不跨登录延续，角标也不该带着上一位客户的数字。 */
  function reset(): void {
    loaded.value = false;
    pendingCount.value = undefined;
    // 只清不发请求：登出那一刻令牌已经交回，再取一次只会撞 401。
    pagination.clear();
  }

  return {
    items: pagination.items,
    total: pagination.total,
    page: pagination.page,
    pageSize: pagination.pageSize,
    loading: pagination.loading,
    error: pagination.errorMessage,
    loaded,
    awaiting,
    accepted,
    rejected,
    expired,
    pendingCount,
    refresh,
    goTo: pagination.goTo,
    decide,
    reset,
  };
});
