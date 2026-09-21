// layout store：折叠是浏览器级偏好，两个布尔各自独立持久化，初始从 localStorage 读、
// 缺省展开，toggle 写回。登录/登出不参与——它不随身份走，所以这里不 mock auth。
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { useLayoutStore } from "./layout";

const SIDEBAR_KEY = "wealth-internal-sidebar-collapsed";
const INSPECTOR_KEY = "wealth-internal-inspector-collapsed";

let pinia: Pinia;

beforeEach(() => {
  localStorage.clear();
  // 每个用例换一个全新 pinia：store 的 setup 在首次 useLayoutStore() 时才跑，
  // 换 pinia 等价于「刷新页面」——setup 重跑、重新从 localStorage 读。
  pinia = createPinia();
  setActivePinia(pinia);
});

describe("useLayoutStore", () => {
  it("缺省展开：localStorage 无记录时两个布尔都为 false", () => {
    const store = useLayoutStore();
    expect(store.sidebarCollapsed).toBe(false);
    expect(store.inspectorCollapsed).toBe(false);
    expect(localStorage.getItem(SIDEBAR_KEY)).toBeNull();
    expect(localStorage.getItem(INSPECTOR_KEY)).toBeNull();
  });

  it("只认字面量 true：任何非 true 值都回落为展开", () => {
    localStorage.setItem(SIDEBAR_KEY, "false");
    localStorage.setItem(INSPECTOR_KEY, "yes");
    setActivePinia(createPinia());

    const store = useLayoutStore();
    expect(store.sidebarCollapsed).toBe(false);
    expect(store.inspectorCollapsed).toBe(false);
  });

  it("toggleSidebar 翻转并写回 localStorage", () => {
    const store = useLayoutStore();

    store.toggleSidebar();
    expect(store.sidebarCollapsed).toBe(true);
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe("true");

    store.toggleSidebar();
    expect(store.sidebarCollapsed).toBe(false);
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe("false");
  });

  it("toggleInspector 翻转并写回 localStorage", () => {
    const store = useLayoutStore();

    store.toggleInspector();
    expect(store.inspectorCollapsed).toBe(true);
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe("true");

    store.toggleInspector();
    expect(store.inspectorCollapsed).toBe(false);
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe("false");
  });

  it("两个布尔各自独立持久化：折侧栏不动检查器、折检查器不动侧栏", () => {
    const store = useLayoutStore();

    store.setSidebarCollapsed(true);
    expect(store.inspectorCollapsed).toBe(false);
    expect(localStorage.getItem(INSPECTOR_KEY)).toBeNull();

    store.setInspectorCollapsed(true);
    expect(store.sidebarCollapsed).toBe(true);
    expect(localStorage.getItem(SIDEBAR_KEY)).toBe("true");
    expect(localStorage.getItem(INSPECTOR_KEY)).toBe("true");
  });

  it("刷新恢复：换 pinia 后两个布尔各自从 localStorage 读回", () => {
    const store = useLayoutStore();
    store.setSidebarCollapsed(true);
    store.setInspectorCollapsed(true);

    // 模拟刷新：全新 pinia 重新初始化 store。
    setActivePinia(createPinia());

    const restored = useLayoutStore();
    expect(restored.sidebarCollapsed).toBe(true);
    expect(restored.inspectorCollapsed).toBe(true);
  });
});
