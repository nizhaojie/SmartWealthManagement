// 当前会话的消息列表。
//
// 会话不跨登录延续：重新登录即新会话，登录 / 登出时调用 reset()。
// 这里只存消息本身与它的增删改，不发起请求——SSE 的收发留在页面与 chat/api。
import { ref } from "vue";
import { defineStore } from "pinia";
import type { Citation, ChatStreamDone } from "../chat/api";

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  citations: Citation[];
  done: boolean;
};

export const useChatStore = defineStore("chat", () => {
  const messages = ref<ChatMessage[]>([]);
  let nextId = 1;

  function find(id: number): ChatMessage | undefined {
    return messages.value.find((message) => message.id === id);
  }

  /** 清空会话（登录 / 登出时调用，保证重新登录不会看到上一场的消息）。 */
  function reset(): void {
    messages.value = [];
    nextId = 1;
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

  return { messages, reset, beginTurn, appendDelta, finishTurn, failTurn };
});
