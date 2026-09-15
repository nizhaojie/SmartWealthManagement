import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import ChatPage from "./ChatPage.vue";
import { streamChatMessage, type ChatStreamHandlers } from "./api";

vi.mock("./api", () => ({
  streamChatMessage: vi.fn(),
}));

async function ask(wrapper: ReturnType<typeof mount>, message: string) {
  await wrapper.find('input[name="chat-message"]').setValue(message);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
}

function mockStreamOnce(run: (handlers: ChatStreamHandlers) => void) {
  vi.mocked(streamChatMessage).mockImplementationOnce(async (_message, handlers) => {
    run(handlers);
  });
}

describe("ChatPage", () => {
  it("streams deltas into the assistant bubble before the final answer arrives", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDelta("你");
      handlers.onDelta("好");
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "你好");

    expect(wrapper.text()).toContain("你好");
    expect(wrapper.findAll(".message")).toHaveLength(2);
  });

  it("renders a clickable citation badge and reveals source info on click", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "本产品最短持有期为九十天[1]。",
        citations: [
          {
            knowledge_id: 42,
            chunk_index: 0,
            title: "产品说明书",
            source_file: "product.txt",
            heading_path: ["赎回规则"],
            marker: 1,
          },
        ],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "最短持有期是多久");

    const badge = wrapper.find("button.citation-badge");
    expect(badge.exists()).toBe(true);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await badge.trigger("click");

    const panel = wrapper.find('[role="dialog"]');
    expect(panel.exists()).toBe(true);
    expect(panel.text()).toContain("产品说明书");
    expect(panel.text()).toContain("product.txt");
    expect(panel.text()).toContain("赎回规则");
  });

  it("keeps the citation panel's own ARIA wiring intact", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "管理费率为百分之一点二[1]。",
        citations: [
          {
            knowledge_id: 7,
            chunk_index: 0,
            title: "费率说明",
            source_file: "fee.txt",
            heading_path: [],
            marker: 1,
          },
        ],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "管理费率是多少");

    const badge = wrapper.find("button.citation-badge");
    expect(badge.attributes("aria-expanded")).toBe("false");
    const controlsId = badge.attributes("aria-controls");
    expect(controlsId).toBeTruthy();

    await badge.trigger("click");

    expect(badge.attributes("aria-expanded")).toBe("true");
    const panel = wrapper.find(`#${controlsId}`);
    expect(panel.exists()).toBe(true);
    expect(panel.attributes("role")).toBe("dialog");
    expect(panel.attributes("aria-label")).toContain("费率说明");
  });

  it("matches each badge to its citation by marker value, not by text order", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        // 文本里先出现 [2] 再出现 [1]，citations 数组顺序与之相反——
        // 角标必须按 marker 精确匹配，不能按“文本里第几个出现”猜测。
        answer: "赎回期为九十天[2]，管理费率为百分之一点二[1]。",
        citations: [
          {
            knowledge_id: 1,
            chunk_index: 0,
            title: "费率说明",
            source_file: "fee.txt",
            heading_path: [],
            marker: 1,
          },
          {
            knowledge_id: 2,
            chunk_index: 0,
            title: "赎回规则",
            source_file: "redemption.txt",
            heading_path: [],
            marker: 2,
          },
        ],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "赎回期和管理费率分别是多少");

    const badges = wrapper.findAll("button.citation-badge");
    expect(badges).toHaveLength(2);

    await badges[0].trigger("click");
    expect(wrapper.find('[role="dialog"]').text()).toContain("赎回规则");

    await badges[0].trigger("click");
    await badges[1].trigger("click");
    expect(wrapper.find('[role="dialog"]').text()).toContain("费率说明");
  });

  it("renders a fallback answer with the human channel and no citation badges", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "很抱歉，我在知识库里没有找到能支撑这个问题的依据。建议您拨打人工客服热线 95588。",
        citations: [],
        intent: "FAQ",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "阿尔法半人马座恒星系统的行星编号列表是什么");

    expect(wrapper.text()).toContain("95588");
    expect(wrapper.find("button.citation-badge").exists()).toBe(false);
  });

  it("renders multiple turns of the conversation", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "早上好",
        citations: [],
        intent: "闲聊",
        content_classification: "事实性内容",
      });
    });
    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    await ask(wrapper, "你好");

    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "再见",
        citations: [],
        intent: "闲聊",
        content_classification: "事实性内容",
      });
    });
    await ask(wrapper, "拜拜");

    expect(wrapper.findAll(".message")).toHaveLength(4);
    expect(wrapper.text()).toContain("你好");
    expect(wrapper.text()).toContain("早上好");
    expect(wrapper.text()).toContain("拜拜");
    expect(wrapper.text()).toContain("再见");
  });

  it("scrolls the message list to the bottom as new content arrives", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "早上好",
        citations: [],
        intent: "闲聊",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mount(ChatPage, { global: { plugins: [ElementPlus] } });
    const listElement = wrapper.find(".message-list").element as HTMLElement;
    Object.defineProperty(listElement, "scrollHeight", { value: 900, configurable: true });

    await ask(wrapper, "你好");

    expect(listElement.scrollTop).toBe(900);
  });
});
