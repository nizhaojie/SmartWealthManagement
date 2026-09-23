// @vitest-environment jsdom
// CustomerShell 与 layout store 的接线：v-model:sidebar-collapsed 把 AppShell 的受控
// update:sidebarCollapsed 事件接回 store 写回 localStorage。customer 无检查器，不传
// inspectorCollapsed——这里只断这一条边界，不重复 AppShell 自身的折叠渲染（shared 已测）。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { AppShell } from "@wealth/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { h } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { countAwaitingAdvice, listMyAdvice } from "../operation-advice/api";
import { useLayoutStore } from "../stores/layout";
import CustomerShell from "./CustomerShell.vue";

vi.mock("../operation-advice/api", () => ({
  listMyAdvice: vi.fn(),
  countAwaitingAdvice: vi.fn(),
  decideAdvice: vi.fn(),
}));

const StubView = {
  name: "StubView",
  render: () => h("div", { "data-testid": "stub-view" }),
};

let pinia: Pinia;
let router: Router;
let wrapper: VueWrapper | null = null;

/** 列表接口的一页（ADR-0024）：形状恒为 `{items, total, page, page_size}`。 */
function emptyPage() {
  return { items: [], total: 0, page: 1, page_size: 20 };
}

beforeEach(async () => {
  localStorage.clear();
  pinia = createPinia();
  setActivePinia(pinia);
  vi.mocked(listMyAdvice).mockResolvedValue(emptyPage());
  vi.mocked(countAwaitingAdvice).mockResolvedValue(0);
  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: "/",
        component: CustomerShell,
        children: [{ path: "", component: StubView }],
      },
    ],
  });
  await router.push("/");
  await router.isReady();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
});

function mountShell(): VueWrapper {
  wrapper = mount(CustomerShell, { global: { plugins: [pinia, ElementPlus, router] } });
  return wrapper;
}

describe("CustomerShell 折叠接线", () => {
  it("挂载后把 store 的折叠态交给 AppShell，且不传 inspectorCollapsed", async () => {
    const shell = mountShell();
    await flushPromises();

    const appShell = shell.findComponent(AppShell);
    expect(appShell.props("sidebarCollapsed")).toBe(false);
    // 无检查器：customer 不传 inspectorCollapsed，落到布尔默认值 false，壳保持两栏。
    expect(appShell.props("inspectorCollapsed")).toBe(false);
    expect(appShell.classes()).not.toContain("app-shell--inspector-collapsed");
    expect(appShell.find(".app-shell__inspector").exists()).toBe(false);
  });

  it("store 折叠态变化同步到 AppShell", async () => {
    const shell = mountShell();
    await flushPromises();

    useLayoutStore().setSidebarCollapsed(true);
    await flushPromises();

    expect(shell.findComponent(AppShell).props("sidebarCollapsed")).toBe(true);
  });

  it("点击 AppShell 触发条，store 写回并持久化", async () => {
    const shell = mountShell();
    await flushPromises();

    await shell.find(".app-shell__collapse-toggle").trigger("click");
    await flushPromises();

    expect(useLayoutStore().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem("wealth-customer-sidebar-collapsed")).toBe("true");
    expect(shell.findComponent(AppShell).props("sidebarCollapsed")).toBe(true);
  });
});
