import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChunkHit } from "./types";

const { searchKnowledge } = vi.hoisted(() => ({
  searchKnowledge: vi.fn(),
}));

vi.mock("./api", () => ({ searchKnowledge }));

import RetrievalLab from "./RetrievalLab.vue";

function makeHit(overrides: Partial<ChunkHit> = {}): ChunkHit {
  return {
    knowledge_id: 1,
    knowledge_type: "FAQ",
    chunk_index: 0,
    heading_path: ["常见问题"],
    content: "示例片段",
    score: 0.5,
    title: "示例文档",
    source_file: "faq.txt",
    ...overrides,
  };
}

async function mountLab() {
  const wrapper = mount(RetrievalLab, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

async function runSearch(wrapper: Awaited<ReturnType<typeof mountLab>>, query = "赎回多久到账") {
  await wrapper.get('textarea[name="query"]').setValue(query);
  await wrapper.get('button[name="search"]').trigger("click");
  await flushPromises();
}

function hitCard(wrapper: Awaited<ReturnType<typeof mountLab>>, content: string) {
  return wrapper.findAll(".retrieval-hit").find((node) => node.text().includes(content));
}

describe("RetrievalLab", () => {
  beforeEach(() => {
    searchKnowledge.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("visually distinguishes hits below the fallback threshold from those that pass it", async () => {
    searchKnowledge.mockResolvedValue({
      score_threshold: 0.35,
      hits: [
        makeHit({
          knowledge_id: 11,
          content: "现金管理产品下一交易日到账",
          score: 0.82,
          source_file: "faq.txt",
        }),
        makeHit({
          knowledge_id: 12,
          content: "产品风险等级与风险承受等级是两套刻度",
          score: 0.3,
          source_file: "policy.md",
        }),
      ],
    });

    const wrapper = await mountLab();
    await runSearch(wrapper);

    const above = hitCard(wrapper, "现金管理产品下一交易日到账");
    const below = hitCard(wrapper, "产品风险等级与风险承受等级是两套刻度");

    expect(above).toBeDefined();
    expect(below).toBeDefined();
    expect(above!.text()).toContain("过线");
    expect(below!.text()).toContain("低于阈值");
    expect(above!.classes()).toContain("retrieval-hit--above");
    expect(below!.classes()).toContain("retrieval-hit--below");
  });

  it("marks the fallback threshold between hits that pass it and hits that do not", async () => {
    searchKnowledge.mockResolvedValue({
      score_threshold: 0.35,
      hits: [
        makeHit({ content: "过线片段全文", score: 0.41 }),
        makeHit({ content: "低于线片段全文", score: 0.2 }),
      ],
    });

    const wrapper = await mountLab();
    await runSearch(wrapper);

    const marker = wrapper.get(".retrieval-lab__threshold");
    expect(marker.text()).toContain("兜底阈值");
    expect(marker.text()).toContain("0.35");

    const ordered = wrapper.findAll(".retrieval-hit, .retrieval-lab__threshold");
    expect(ordered).toHaveLength(3);
    expect(ordered[0].text()).toContain("过线片段全文");
    expect(ordered[1].classes()).toContain("retrieval-lab__threshold");
    expect(ordered[2].text()).toContain("低于线片段全文");
  });

  it("shows each hit's full text, similarity score, and source location", async () => {
    searchKnowledge.mockResolvedValue({
      score_threshold: 0.35,
      hits: [
        makeHit({
          content: "客户开户需提供本人身份证原件与银行卡，全程在网点办理。",
          score: 0.64,
          source_file: "open-account.md",
          chunk_index: 2,
          heading_path: ["开户须知", "材料清单"],
          title: "开户须知",
        }),
      ],
    });

    const wrapper = await mountLab();
    await runSearch(wrapper);

    const card = hitCard(wrapper, "客户开户需提供本人身份证原件与银行卡，全程在网点办理。");
    expect(card).toBeDefined();
    expect(card!.text()).toContain("0.64");
    expect(card!.text()).toContain("open-account.md");
    expect(card!.text()).toContain("文档 1");
    expect(card!.text()).toContain("块 2");
    expect(card!.text()).toContain("开户须知 / 材料清单");
  });

  it("states whether this search's highest score crossed the fallback threshold", async () => {
    searchKnowledge.mockResolvedValue({
      score_threshold: 0.35,
      hits: [makeHit({ content: "未过线的最高分片段", score: 0.2 })],
    });

    const wrapper = await mountLab();
    await runSearch(wrapper);

    expect(wrapper.text()).toContain("本次最高分 0.20");
    expect(wrapper.text()).toContain("未过兜底阈值");
  });

  it("renders an empty state when a search returns no hits", async () => {
    searchKnowledge.mockResolvedValue({ score_threshold: 0.35, hits: [] });

    const wrapper = await mountLab();
    await runSearch(wrapper, "一个库里完全没有的问题");

    expect(wrapper.findAll(".retrieval-hit")).toHaveLength(0);
    expect(wrapper.text()).toContain("未命中任何知识片段");
    expect(wrapper.text()).toContain("无命中，未过兜底阈值");
  });

  it("scopes the search to the selected knowledge type", async () => {
    searchKnowledge.mockResolvedValue({ score_threshold: 0.35, hits: [] });

    const wrapper = await mountLab();
    const typeSelect = wrapper.getComponent({ name: "ElSelect" });
    await typeSelect.setValue("政策");
    await runSearch(wrapper);

    expect(searchKnowledge).toHaveBeenCalledWith(
      expect.objectContaining({ query: "赎回多久到账", knowledgeType: "政策" }),
    );
  });

  it("labels a barely-passing hit differently from a far-below-threshold hit", async () => {
    searchKnowledge.mockResolvedValue({
      score_threshold: 0.35,
      hits: [
        makeHit({ content: "现金产品赎回下一交易日到账", score: 0.36 }),
        makeHit({ content: "风险承受等级取值从 C1 到 C5", score: 0.12 }),
      ],
    });

    const wrapper = await mountLab();
    await runSearch(wrapper);

    const barely = hitCard(wrapper, "现金产品赎回下一交易日到账");
    const farBelow = hitCard(wrapper, "风险承受等级取值从 C1 到 C5");

    expect(barely!.text()).toContain("勉强过线");
    expect(farBelow!.text()).toContain("远低于线");
    expect(barely!.classes()).toContain("retrieval-hit--above");
    expect(farBelow!.classes()).toContain("retrieval-hit--below");
  });
});
