// 对话页的合规呈现面：引用角标可点可定位；检索不到依据时的兜底话术与人工热线原样保留。
// 只测这些，不测排版。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "./ChatPage.vue";
import { streamChatMessage, type ChatStreamHandlers } from "./api";

vi.mock("./api", () => ({
  streamChatMessage: vi.fn(),
}));

function mockStreamOnce(run: (handlers: ChatStreamHandlers) => void) {
  vi.mocked(streamChatMessage).mockImplementationOnce(async (_message, handlers) => {
    run(handlers);
  });
}

async function ask(wrapper: VueWrapper, message: string) {
  await wrapper.find('input[name="chat-message"]').setValue(message);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
}

function mountPage(pinia: Pinia): VueWrapper {
  return mount(ChatPage, { global: { plugins: [pinia, ElementPlus] } });
}

const CITATION = {
  knowledge_id: 42,
  chunk_index: 0,
  title: "产品说明书",
  source_file: "product.txt",
  heading_path: ["赎回规则"],
  marker: 1,
};

describe("ChatPage", () => {
  let pinia: Pinia;

  beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    vi.mocked(streamChatMessage).mockReset();
  });

  it("streams deltas into the assistant bubble before the final answer arrives", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDelta("你");
      handlers.onDelta("好");
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "你好");

    expect(wrapper.text()).toContain("你好");
    expect(wrapper.findAll(".msg")).toHaveLength(2);
  });

  it("renders a clickable citation badge that locates the source on click", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "本产品最短持有期为九十天[1]。",
        citations: [CITATION],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "最短持有期是多久");

    const badge = wrapper.find("button.cite-chip");
    expect(badge.exists()).toBe(true);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);

    await badge.trigger("click");

    const panel = wrapper.find('[role="dialog"]');
    expect(panel.exists()).toBe(true);
    expect(panel.text()).toContain("产品说明书");
    expect(panel.text()).toContain("product.txt");
    expect(panel.text()).toContain("赎回规则");
  });

  it("wires the badge to its panel through aria-controls", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "管理费率为百分之一点二[1]。",
        citations: [{ ...CITATION, knowledge_id: 7, title: "费率说明", source_file: "fee.txt", heading_path: [] }],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "管理费率是多少");

    const badge = wrapper.find("button.cite-chip");
    expect(badge.attributes("aria-expanded")).toBe("false");
    const controlsId = badge.attributes("aria-controls");
    expect(controlsId).toBeTruthy();

    await badge.trigger("click");

    expect(badge.attributes("aria-expanded")).toBe("true");
    const panel = wrapper.find(`#${controlsId}`);
    expect(panel.exists()).toBe(true);
    expect(panel.attributes("aria-label")).toContain("费率说明");
  });

  it("matches each badge to its citation by marker value, not by text order", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        // 文本里先出现 [2] 再出现 [1]，citations 数组顺序与之相反——
        // 角标必须按 marker 精确匹配，不能按「文本里第几个出现」猜。
        answer: "赎回期为九十天[2]，管理费率为百分之一点二[1]。",
        citations: [
          { ...CITATION, marker: 1, title: "费率说明", source_file: "fee.txt", heading_path: [] },
          { ...CITATION, knowledge_id: 2, marker: 2, title: "赎回规则", source_file: "redemption.txt", heading_path: [] },
        ],
        intent: "产品咨询",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "赎回期和管理费率分别是多少");

    const badges = wrapper.findAll("button.cite-chip");
    expect(badges).toHaveLength(2);

    await badges[0].trigger("click");
    expect(wrapper.find('[role="dialog"]').text()).toContain("赎回规则");

    await badges[0].trigger("click");
    await badges[1].trigger("click");
    expect(wrapper.find('[role="dialog"]').text()).toContain("费率说明");
  });

  it("keeps the no-evidence answer with the human channel and without badges", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "很抱歉，我在知识库里没有找到能支撑这个问题的依据。建议您拨打人工客服热线 95588。",
        citations: [],
        intent: "FAQ",
        content_classification: "事实性内容",
      });
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "阿尔法半人马座恒星系统的行星编号列表是什么");

    expect(wrapper.text()).toContain("95588");
    expect(wrapper.find("button.cite-chip").exists()).toBe(false);
  });

  it("renders a degraded answer without citations and without breaking", async () => {
    mockStreamOnce((handlers) => {
      handlers.onDone({
        answer: "抱歉，智能回答服务暂时不可用，请稍后重试。如需帮助可拨打人工客服热线 95588，由人工为您核实。",
        citations: [],
        intent: "产品咨询",
        content_classification: "事实性内容",
        trace_id: "trace-degraded-1",
        degraded: true,
      });
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "最短持有期是多久");

    expect(wrapper.text()).toContain("智能回答服务暂时不可用");
    expect(wrapper.find("button.cite-chip").exists()).toBe(false);
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false);
  });

  it("keeps a human channel when the stream breaks", async () => {
    mockStreamOnce((handlers) => {
      handlers.onError(new Error("boom"));
    });

    const wrapper = mountPage(pinia);
    await ask(wrapper, "最短持有期是多久");

    expect(wrapper.text()).toContain("人工客服热线");
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

    const wrapper = mountPage(pinia);
    const listElement = wrapper.find('[data-testid="chat-list"]').element as HTMLElement;
    Object.defineProperty(listElement, "scrollHeight", { value: 900, configurable: true });

    await ask(wrapper, "你好");

    expect(listElement.scrollTop).toBe(900);
  });
});
