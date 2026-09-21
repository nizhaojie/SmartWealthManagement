// 「我的建议」的数据源，同时喂侧栏的待决定角标。
//
// 两处读同一份列表：页面按状态分组渲染，壳只数「待客户决定」的条数。如果页面自己拿一份，
// 壳再拿一份，客户在接受之后角标要等下一次谁去刷新才掉——一份数据、两处读，角标不可能
// 落后于页面。
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { ApiError } from "@wealth/shared";
import { decideAdvice, listMyAdvice } from "../operation-advice/api";
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
  const advice = ref<OperationAdvice[]>([]);
  const loading = ref(false);
  // 「拉取成功」与「一条都没有」要分得开：接口故障不该被说成「还没有建议」。
  const loaded = ref(false);
  const error = ref("");

  const group = (status: AdviceStatus) =>
    computed(() => advice.value.filter((item) => item.status === status));

  const awaiting = group(ADVICE_AWAITING);
  const accepted = group(ADVICE_ACCEPTED);
  const rejected = group(ADVICE_REJECTED);
  const expired = group(ADVICE_EXPIRED);

  /** 侧栏角标：待客户决定的条数。0 与「还没加载」都不渲染角标。 */
  const pendingCount = computed(() => awaiting.value.length);

  async function refresh(): Promise<void> {
    loading.value = true;
    error.value = "";
    try {
      advice.value = (await listMyAdvice()).advice;
      loaded.value = true;
    } catch (caught) {
      advice.value = [];
      error.value = caught instanceof ApiError ? caught.message : "操作建议加载失败";
    } finally {
      loading.value = false;
    }
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
    advice.value = [];
    loaded.value = false;
    loading.value = false;
    error.value = "";
  }

  return {
    advice,
    loading,
    loaded,
    error,
    awaiting,
    accepted,
    rejected,
    expired,
    pendingCount,
    refresh,
    decide,
    reset,
  };
});
