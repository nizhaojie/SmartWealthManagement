// 当前会话的消息列表。
//
// 会话不跨登录延续：重新登录即新会话，登录与登出都会调用 reset()。
// 这里只存消息本身与它的增删改，不发起请求——SSE 的收发留在页面与 chat/api；
// 刷新页面后的补水也一样，读回来的动作在对话页（`chat/history.ts` 取数），
// store 只负责把结果落成列表。
import { ref } from "vue";
import { defineStore } from "pinia";
import type { ChatStreamDone, Citation, DataAnswer } from "../chat/api";

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  // 数据查询「有行」时这一轮的结果表（ADR-0028）；其余轮次没有它，气泡据此不渲染空表壳。
  dataAnswer?: DataAnswer | null;
  done: boolean;
};

/** 消息的 `id` 由 store 发号，读回来的消息因此不带它。 */
export type RestoredMessage = Omit<ChatMessage, "id">;

export const useChatStore = defineStore("chat", () => {
  const messages = ref<ChatMessage[]>([]);
  // 这一场登录会话是否已经补过水（刷新后把当前会话读回来）。
  const restored = ref(false);
  let nextId = 1;

  function find(id: number): ChatMessage | undefined {
    return messages.value.find((message) => message.id === id);
  }

  /** 清空会话（登录 / 登出时调用，保证重新登录不会看到上一场的消息）。 */
  function reset(): void {
    messages.value = [];
    restored.value = false;
    nextId = 1;
  }

  /**
   * 用后端读回的当前会话消息重建列表：刷新页面后，Pinia 随页面重建、消息随之清空，
   * 而这一场登录会话的归档还在——这就是把它补回对话框的那一步。
   *
   * 只补一次：补过之后切走再切回不会重来（现场可能有刚发出、归档里还没有的那一轮）。
   * 读回来的消息都是定案状态（`done`）——归档里没有「正在生成」这回事。
   */
  function restore(archived: RestoredMessage[]): void {
    if (restored.value) {
      return;
    }
    messages.value = archived.map((message, index) => ({ ...message, id: index + 1 }));
    nextId = messages.value.length + 1;
    restored.value = true;
  }

  /** 追加用户提问，并开一条待填充的回答消息；返回回答消息的 id 供流式增量写入。 */
  function beginTurn(question: string): number {
    messages.value.push({
      id: nextId++,
      role: "user",
      text: question,
      citations: [],
      done: true,
    });
    const assistantId = nextId++;
    messages.value.push({
      id: assistantId,
      role: "assistant",
      text: "",
      citations: [],
      done: false,
    });
    return assistantId;
  }

  function appendDelta(id: number, delta: string): void {
    const message = find(id);
    if (message) {
      message.text += delta;
    }
  }

  /** 定案：整段答案与引用一起落定（推流过程本身不做任何决策）。 */
  function finishTurn(id: number, payload: ChatStreamDone): void {
    const message = find(id);
    if (!message) {
      return;
    }
    message.text = payload.answer;
    message.citations = payload.citations;
    // 结果表与引用走同一条路径：随 `done` 帧一次落定，不在增量里出现。
    message.dataAnswer = payload.data_answer ?? null;
    message.done = true;
  }

  /**
   * 收尾一条失败的回答。没收到任何增量时才使用调用方给的兜底话术
   * （话术由页面决定：它属于对外文案，store 不发明合规说明）。
   */
  function failTurn(id: number, fallbackText: string): void {
    const message = find(id);
    if (!message) {
      return;
    }
    if (!message.text) {
      message.text = fallbackText;
    }
    message.done = true;
  }

  return { messages, restored, reset, restore, beginTurn, appendDelta, finishTurn, failTurn };
});
