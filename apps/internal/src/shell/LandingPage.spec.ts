import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ADVISOR } from "../auth/identity";
import { currentEmployee } from "../auth/store";
import { visibleModules } from "./modules";
import LandingPage from "./LandingPage.vue";

vi.mock("./modules", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./modules")>();
  return { ...actual, visibleModules: vi.fn(actual.visibleModules) };
});

async function mountLanding() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/", component: LandingPage }],
  });
  await router.push("/");
  await router.isReady();
  const wrapper = mount(LandingPage, { global: { plugins: [ElementPlus, router] } });
  await flushPromises();
  return { wrapper, router };
}

describe("LandingPage", () => {
  afterEach(() => {
    currentEmployee.value = null;
    vi.clearAllMocks();
  });

  it("renders one entry card per visible module with icon, label and description", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR as never };
    const { wrapper } = await mountLanding();

    const cards = wrapper.findAll(".module-entry");
    expect(cards.length).toBe(visibleModules(ADVISOR).length);
    expect(wrapper.text()).toContain("知识库管理");
    expect(wrapper.text()).toContain("投顾助手");
    expect(wrapper.text()).toContain("生成客户画像分析、产品推荐与配置方案");
    expect(wrapper.find("svg").exists()).toBe(true);
  });

  it("navigates to the module path when its entry card is clicked", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR as never };
    const { wrapper, router } = await mountLanding();

    const knowledgeCard = wrapper
      .findAll(".module-entry")
      .find((card) => card.text().includes("知识库管理"));
    expect(knowledgeCard).toBeDefined();
    await knowledgeCard!.trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/knowledge");
  });

  it("shows an explanatory empty state instead of an error for a role without visible modules", async () => {
    currentEmployee.value = { real_name: "陈顾问", employee_role: ADVISOR as never };
    vi.mocked(visibleModules).mockReturnValue([]);
    const { wrapper } = await mountLanding();

    expect(wrapper.findAll(".module-entry").length).toBe(0);
    expect(wrapper.text()).toContain("没有可见模块");
  });
});
