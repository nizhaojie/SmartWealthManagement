/**
 * 数据分析的问答线程：一轮问答在这里累积，活过刷新，登出即清。
 *
 * 为什么不放在页面里：线程要活过页面重挂载（切模块、刷新），而页面组件的局部状态活不过；
 * `sessionStorage` 是它的持久层——浏览器标签页关掉即消失，寿命与后端 Redis 短期记忆同构。
 *
 * 它不是 **历史记录**：那是客户本人对已结束会话的只读回看，进归档；这条线程是当前会话的
 * 上下文载体，不进任何归档，也不与留痕合并（留痕是逐次查询的合规记录，界面动作碰不到它）。
 *
 * 两个清空动作别混：「清空对话」（`discardContext`）是换话题，只丢上下文、不结束会话；
 * `reset` 是会话边界，登出与重新登录都走它——`CONTEXT.md` 的 **会话** 里，唯一能结束
 * 会话的事仍然是重新登录。
 *
 * 持久化键按 `real_name` 分：员工身份里没有更稳定的标识（`app/api/auth.py` 只发
 * 姓名与角色），同名同角色的人共用一份线程是认下的代价——`sessionStorage` 本身就只活在
 * 这一个标签页里。
 *
 * 一个前提：读回存储发生在 store 首次实例化时，那时身份必须已经到手（路由守卫先
 * `restoreSession` 再渲染页面）。登录路径上确实有一处更早的实例化（`stores/auth.ts`
 * 的 `reset`），但它同时会清掉存储，所以不存在「读不回来」的线程。
 */
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { useAuthStore } from "../stores/auth";
import type { AnalyticsQueryResponse } from "./types";

/** 一轮结果的行数上限，与后端 `settings.analytics_max_rows` 对齐：线程要落盘，留更多行只会撞配额。 */
export const MAX_RESULT_ROWS = 200;

/** 线程只保留最近 20 轮，更早的整轮移出本页（并记账，界面上要说明，见 `droppedRounds`）。 */
export const MAX_ROUNDS = 20;

/** 持久化键前缀：按员工隔离，沿用 internal 既有 `wealth-internal-` 前缀风格。 */
const STORAGE_PREFIX = "wealth-internal-analytics-thread";

/** 存储格式版本：读回一份不认识的数据时当它不存在，而不是把页面挂掉。 */
const STORAGE_VERSION = 1;

/** 一轮里助手那一侧的状态：在途 / 已作答 / 没问成。 */
export type RoundStatus = "pending" | "answered" | "failed";

/**
 * 这一轮为什么没问成。业务码（1101–1105）与后端写下的那句话都留下：
 * 码决定呈现文案，原文用来诊断——只留一句话会把可诊断的信息丢掉。
 */
export type RoundFailure = {
  code: number | null;
  message: string;
};

export type UserMessage = {
  id: string;
  role: "user";
  question: string;
};

export type AssistantMessage = {
  id: string;
  role: "assistant";
  status: RoundStatus;
  /** 作答成功时的整包产物；在途与失败时为 null。 */
  result: AnalyticsQueryResponse | null;
  failure: RoundFailure | null;
};

/** 线程里的一条消息。一轮 = 一条 `user` + 紧跟的一条 `assistant`。 */
export type ThreadMessage = UserMessage | AssistantMessage;

type StoredThread = {
  version: number;
  messages: ThreadMessage[];
  droppedRounds: number;
  sessionId: string | null;
};

function isStoredThread(value: unknown): value is StoredThread {
  if (typeof value !== "object" || value === null) return false;
  const stored = value as Partial<StoredThread>;
  return (
    stored.version === STORAGE_VERSION &&
    Array.isArray(stored.messages) &&
    typeof stored.droppedRounds === "number" &&
    (stored.sessionId === null || typeof stored.sessionId === "string")
  );
}

export const useAnalyticsThreadStore = defineStore("analyticsThread", () => {
  const auth = useAuthStore();

  const messages = ref<ThreadMessage[]>([]);
  /** 因为超出上限而被移出本页的轮数：不静默丢，界面上要说明。 */
  const droppedRounds = ref(0);
  /**
   * 覆盖凭证会话的标识。`null` 表示不带——会话由登录凭证承载，同一次登录的追问因此
   * 共用一个上下文。只有「清空对话」之后才带一个新的，用它把上下文甩开。
   */
  const sessionId = ref<string | null>(null);

  const isEmpty = computed(() => messages.value.length === 0);

  /** 按员工隔离的持久化键；身份还没到手时无从归属，也就不落盘。 */
  function storageKey(): string | null {
    const name = auth.currentEmployee?.real_name;
    return name ? `${STORAGE_PREFIX}:${name}` : null;
  }

  function persist(): void {
    const key = storageKey();
    if (!key) return;
    const stored: StoredThread = {
      version: STORAGE_VERSION,
      messages: messages.value,
      droppedRounds: droppedRounds.value,
      sessionId: sessionId.value,
    };
    try {
      sessionStorage.setItem(key, JSON.stringify(stored));
    } catch {
      // 配额满了也不抛回调用方：线程在内存里仍然成立，页面不该因为存不下而报错。
    }
  }

  function hydrate(): void {
    const key = storageKey();
    if (!key) return;
    const raw = sessionStorage.getItem(key);
    if (!raw) return;
    let stored: unknown;
    try {
      stored = JSON.parse(raw);
    } catch {
      sessionStorage.removeItem(key);
      return;
    }
    if (!isStoredThread(stored)) {
      // 版本不认识或形状不对：当它不存在。一条读不回来的线程不该让页面进不去。
      sessionStorage.removeItem(key);
      return;
    }
    messages.value = stored.messages;
    droppedRounds.value = stored.droppedRounds;
    sessionId.value = stored.sessionId;
  }

  /**
   * 只留最近 `MAX_ROUNDS` 轮。一轮是两条消息（问题 + 回答），所以按消息条数裁剪——
   * 从最早的整轮开始移，不会留下一半。移掉多少轮记进 `droppedRounds`。
   */
  function trim(): void {
    const keep = MAX_ROUNDS * 2;
    if (messages.value.length <= keep) return;
    const removed = messages.value.length - keep;
    messages.value = messages.value.slice(removed);
    droppedRounds.value += removed / 2;
  }

  function patchAssistant(id: string, patch: Partial<AssistantMessage>): void {
    messages.value = messages.value.map((message) =>
      message.id === id && message.role === "assistant" ? { ...message, ...patch } : message,
    );
  }

  /** 结果行按后端上限收一次：`row_count` 与 `truncated` 说的是后端返回了什么，原样留着。 */
  function capRows(result: AnalyticsQueryResponse): AnalyticsQueryResponse {
    if (result.rows.length <= MAX_RESULT_ROWS) return result;
    return { ...result, rows: result.rows.slice(0, MAX_RESULT_ROWS) };
  }

  /** 开启一轮：问题与「正在查询」的助手位一起入线程，返回这一轮的标识（助手消息的 id）。 */
  function beginRound(question: string): string {
    const answerId = crypto.randomUUID();
    messages.value = [
      ...messages.value,
      { id: crypto.randomUUID(), role: "user", question },
      { id: answerId, role: "assistant", status: "pending", result: null, failure: null },
    ];
    trim();
    persist();
    return answerId;
  }

  /** 写入结果：这一轮作答成功。 */
  function settleRound(id: string, result: AnalyticsQueryResponse): void {
    patchAssistant(id, { status: "answered", result: capRows(result), failure: null });
    persist();
  }

  /**
   * 失败收尾。被拒绝的尝试也留在线程里——它确实问过，界面上要看得见为什么没成
   * （后端对失败同样留痕，见 `backend/app/analytics/service.py`）。
   */
  function failRound(id: string, failure: RoundFailure): void {
    patchAssistant(id, { status: "failed", result: null, failure });
    persist();
  }

  /**
   * 「清空对话」：丢弃上下文，不是结束会话。清线程与持久层，并换一个新的会话标识随请求
   * 覆盖——被丢弃的那一段记忆仍留在后端 Redis 里直到 TTL 过期，靠新标识把它甩开。
   *
   * 被移出本页的那几轮也一笔勾销：清空之后主区是空态，摆一句「更早的一轮已从本页移除」
   * 只会让人以为还有东西在。留痕一个字不动。
   */
  function discardContext(): void {
    messages.value = [];
    droppedRounds.value = 0;
    sessionId.value = crypto.randomUUID();
    persist();
  }

  /** 清掉本浏览器里所有员工的线程：登出那一刻身份可能已经交回，按前缀清不依赖身份。 */
  function removeStoredThreads(): void {
    const keys: string[] = [];
    for (let index = 0; index < sessionStorage.length; index += 1) {
      const key = sessionStorage.key(index);
      if (key?.startsWith(STORAGE_PREFIX)) keys.push(key);
    }
    keys.forEach((key) => sessionStorage.removeItem(key));
  }

  /** 会话边界（登出与重新登录）：内存与存储一起清，标识也一并作废——不跨登录延续。 */
  function reset(): void {
    messages.value = [];
    droppedRounds.value = 0;
    sessionId.value = null;
    removeStoredThreads();
  }

  hydrate();

  return {
    messages,
    droppedRounds,
    sessionId,
    isEmpty,
    beginRound,
    settleRound,
    failRound,
    discardContext,
    reset,
  };
});
