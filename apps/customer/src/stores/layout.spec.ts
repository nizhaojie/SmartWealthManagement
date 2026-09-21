// @vitest-environment jsdom
// layout store：折叠是浏览器级偏好，初始从 localStorage 读、缺省展开，toggle 写回。
// 登录/登出不参与——它不随身份走，所以这里不 mock auth。
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useLayoutStore } from "./layout";

const KEY = "wealth-customer-sidebar-collapsed";

let pinia: Pinia;

beforeEach(() => {
  localStorage.clear();
  // 每个用例换一个全新 pinia：store 的 setup 在首次 useLayoutStore() 时才跑，
  // 换 pinia 等价于「刷新页面」——setup 重跑、重新从 localStorage 读。
  pinia = createPinia();
  setActivePinia(pinia);
});

describe("useLayoutStore", () => {
  it("缺省展开：localStorage 无记录时 sidebarCollapsed 为 false", () => {
    expect(useLayoutStore().sidebarCollapsed).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("只认字面量 true：任何非 true 值都回落为展开", () => {
    localStorage.setItem(KEY, "false");
    setActivePinia(createPinia());

    expect(useLayoutStore().sidebarCollapsed).toBe(false);
  });

  it("toggle 翻转状态并写回 localStorage", () => {
    const store = useLayoutStore();

    store.toggleSidebar();
    expect(store.sidebarCollapsed).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("true");

    store.toggleSidebar();
    expect(store.sidebarCollapsed).toBe(false);
    expect(localStorage.getItem(KEY)).toBe("false");
  });

  it("setSidebarCollapsed 落 localStorage（v-model 的 setter 路径）", () => {
    const store = useLayoutStore();

    store.setSidebarCollapsed(true);

    expect(store.sidebarCollapsed).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("true");
  });

  it("刷新恢复：换 pinia 后从 localStorage 读回上次的折叠态", () => {
    useLayoutStore().setSidebarCollapsed(true);

    // 模拟刷新：全新 pinia 重新初始化 store。
    setActivePinia(createPinia());

    expect(useLayoutStore().sidebarCollapsed).toBe(true);
  });
});
