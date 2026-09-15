import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Questionnaire } from "./types";

const { getQuestionnaire, saveDraft, submitAssessment } = vi.hoisted(() => ({
  getQuestionnaire: vi.fn(),
  saveDraft: vi.fn(),
  submitAssessment: vi.fn(),
}));

vi.mock("./api", () => ({ getQuestionnaire, saveDraft, submitAssessment }));

import QuestionnairePage from "./QuestionnairePage.vue";

function makeQuestionnaire(overrides: Partial<Questionnaire> = {}): Questionnaire {
  return {
    questions: [
      {
        id: "q01",
        dimension: "收入",
        prompt: "您目前的年收入大致处于哪个区间？",
        options: [
          { id: "A", label: "10 万以下" },
          { id: "B", label: "10 万（含）至 30 万" },
          { id: "C", label: "30 万（含）至 50 万" },
          { id: "D", label: "50 万及以上" },
        ],
      },
      {
        id: "q09",
        dimension: "风险承受力",
        prompt: "如果持有的产品在半年内下跌 20%，您更可能怎么做？",
        options: [
          { id: "A", label: "全部赎回" },
          { id: "B", label: "赎回一部分" },
          { id: "C", label: "继续持有" },
          { id: "D", label: "加仓" },
        ],
      },
    ],
    answers: {},
    ...overrides,
  };
}

async function mountPage() {
  const wrapper = mount(QuestionnairePage, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

describe("QuestionnairePage", () => {
  beforeEach(() => {
    getQuestionnaire.mockReset();
    saveDraft.mockReset();
    submitAssessment.mockReset();
    getQuestionnaire.mockResolvedValue(makeQuestionnaire());
    saveDraft.mockResolvedValue({ answers: { q01: "B" } });
    submitAssessment.mockResolvedValue({ risk_level: "C2", valid_until: "2027-09-15" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("restores previously saved answers when the page is entered again", async () => {
    getQuestionnaire.mockResolvedValueOnce(makeQuestionnaire());
    const firstVisit = await mountPage();

    await firstVisit.get('input[name="q01"][value="B"]').setValue(true);
    await firstVisit.get('button[name="save"]').trigger("click");
    await flushPromises();

    expect(saveDraft).toHaveBeenCalledWith({ q01: "B" });
    firstVisit.unmount();

    getQuestionnaire.mockResolvedValueOnce(makeQuestionnaire({ answers: { q01: "B" } }));
    const secondVisit = await mountPage();

    const selected = secondVisit.get('input[name="q01"][value="B"]').element as HTMLInputElement;
    expect(selected.checked).toBe(true);
  });
});
