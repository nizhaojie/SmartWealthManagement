// 「投顾助手」的待审队列与待办计数：这一段列表只在这里取一次。
//
// 「同源」指的是这一条，不是两处碰巧相等：显示「还有几件在等」的地方（页面的卡片标题、
// 导航角标）都读这里算出的计数，不自己数列表。页面自己拉一份、别处再拉一份的话，
// 「说 3、点进去是 2」就只是时间问题。
//
// 状态为什么放在 store 而不是页面里：角标在壳上，与页面不是同一棵树，两边只能读同一份。
// 分页本身仍交给 `usePagination`（ADR-0024）——页长钳制、窗口以服务端回传为准、翻页不
// 重复取同一页，这些口径只有那一个实现，store 不自写一遍。
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { usePagination } from "@wealth/shared";
import { getQueue } from "./api";

export const useAdvisoryQueueStore = defineStore("advisoryQueue", () => {
  const pagination = usePagination((query) => getQueue(query), {
    failureMessage: "投顾队列加载失败",
  });

  // 「取过没有」单独记一笔：`usePagination` 里「还没取」与「取到空」长得一样（空列表、
  // 无错误），而角标在还没取时不能写 0——`0` 是一句断言（「没有待办」），那时我们并不知道
  // 有几件。取失败同样退回「不知道」。
  const loaded = ref(false);

  /**
   * 待审内容（当前页）。口径 = 队列接口给的 `items`，因此**含**「待审」与「处理中」
   * 两个状态（`backend/app/advisory/queue.py` 的 `_PENDING_STATUSES`），前端不再按
   * status 过滤——显示出来的数字必须等于点进去看到的条数。
   */
  const pendingReviews = computed(() => pagination.items.value);

  /** 待办计数取服务端的 `total`，不是本页条数：翻页不该让「还有几件在等」变少。 */
  const pendingReviewCount = computed(() =>
    loaded.value ? pagination.total.value : undefined,
  );

  const failed = computed(() => pagination.errorMessage.value !== "");

  async function refresh(): Promise<void> {
    await pagination.refresh();
    loaded.value = !failed.value;
  }

  /** 翻到某一页并取回来。页码不变时不动——el-pagination 会重复发同一页。 */
  async function goTo(next: number): Promise<void> {
    await pagination.goTo(next);
    loaded.value = !failed.value;
  }

  /** 清空（登录 / 登出时调用）：计数不跨会话延续，新会话不带着上一位员工的数字。 */
  function reset(): void {
    loaded.value = false;
    // 只清不发请求：登出那一刻令牌已经交回，再取一次只会撞 401。
    pagination.clear();
  }

  return {
    pendingReviews,
    pendingReviewCount,
    failed,
    error: pagination.errorMessage,
    loading: pagination.loading,
    page: pagination.page,
    pageSize: pagination.pageSize,
    refresh,
    goTo,
    reset,
  };
});
