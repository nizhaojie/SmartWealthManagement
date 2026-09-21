// 「投顾助手」的队列与待办计数：两段列表只在这里取一次。
//
// 「同源」指的是这一条，不是两处碰巧相等：显示「还有几件在等」的地方（页面的卡片标题、
// 导航角标）都读这里算出的计数，不自己数列表。页面自己拉一份、别处再拉一份的话，
// 「说 3、点进去是 2」就只是时间问题。
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { ApiError } from "@wealth/shared";
import { getQueue } from "./api";
import type { AdvisoryQueue, PendingRequest, PendingReview } from "./types";

/** 空队列：初始值，也是取数失败与清空之后的样子。 */
const emptyQueue = (): AdvisoryQueue => ({ pending_requests: [], pending_reviews: [] });

/** 这一轮取数的结果：还没取 / 取到了 / 取失败了。 */
type LoadState = "idle" | "loaded" | "failed";

export const useAdvisoryQueueStore = defineStore("advisoryQueue", () => {
  const queue = ref<AdvisoryQueue>(emptyQueue());
  // 三个状态写在一个字段里而不是几个布尔：两张记号表迟早会各说各话。
  const status = ref<LoadState>("idle");
  const error = ref("");

  const pendingRequests = computed<PendingRequest[]>(() => queue.value.pending_requests);

  /**
   * 待审内容。口径 = 队列接口给的 `pending_reviews`，因此**含**「待审」与「处理中」两个状态
   * （`backend/app/advisory/queue.py` 的 `_PENDING_STATUSES`），前端不再按 status 过滤——
   * 显示出来的数字必须等于点进去看到的条数。
   */
  const pendingReviews = computed<PendingReview[]>(() => queue.value.pending_reviews);

  const failed = computed(() => status.value === "failed");

  /**
   * 计数只在取到数时有值。没取到时（还没取 / 取失败）是 `undefined` 而不是 `0`：`0` 是一句
   * 断言（「没有待办」），而这时我们并不知道有几件。
   */
  function knownCount(value: number): number | undefined {
    return status.value === "loaded" ? value : undefined;
  }

  const pendingReviewCount = computed(() => knownCount(pendingReviews.value.length));
  /** 待生成的方案请求条数：页面那张卡仍要显示它，口径同样只有接口一个来源。 */
  const pendingRequestCount = computed(() => knownCount(pendingRequests.value.length));

  async function refresh(): Promise<void> {
    error.value = "";
    try {
      queue.value = await getQueue();
      status.value = "loaded";
    } catch (caught) {
      // 失败时不留上一轮的列表：留着它，页面会照旧渲染一批已经不知道新鲜与否的行，
      // 而这次取数恰恰没能证明它们还对。计数也随之退回 undefined。
      queue.value = emptyQueue();
      status.value = "failed";
      error.value = caught instanceof ApiError ? caught.message : "投顾队列加载失败";
    }
  }

  /** 清空（登录 / 登出时调用）：计数不跨会话延续，新会话不带着上一位员工的数字。 */
  function reset(): void {
    queue.value = emptyQueue();
    status.value = "idle";
    error.value = "";
  }

  return {
    pendingRequests,
    pendingReviews,
    failed,
    error,
    pendingRequestCount,
    pendingReviewCount,
    refresh,
    reset,
  };
});
