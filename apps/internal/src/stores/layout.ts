// 侧栏与检查器的折叠偏好。
//
// 折叠是浏览器级偏好，不随身份走：localStorage key 沿用 internal 既有前缀
// （tokenStore 的 `wealth-internal-auth`），登录 / 登出都不清空它——员工下次在
// 同一浏览器打开时，侧栏还是上次收起的那个状态。两个布尔各自独立持久化，互不串值。
//
// 状态事实源是这里的两个布尔；`AppShell` 只认受控 prop（`sidebarCollapsed` /
// `inspectorCollapsed`）并 emit `update:sidebarCollapsed`，`WorkbenchShell` 用
// v-model 把侧栏接回这里写回 localStorage；检查器开关则直接调 toggleInspector。
import { ref } from "vue";
import { defineStore } from "pinia";

const SIDEBAR_KEY = "wealth-internal-sidebar-collapsed";
const INSPECTOR_KEY = "wealth-internal-inspector-collapsed";

function load(key: string): boolean {
  // 只认字面量 "true"；缺省（无记录或任何其它值）一律展开。
  return localStorage.getItem(key) === "true";
}

export const useLayoutStore = defineStore("layout", () => {
  const sidebarCollapsed = ref<boolean>(load(SIDEBAR_KEY));
  const inspectorCollapsed = ref<boolean>(load(INSPECTOR_KEY));

  /** 写回并持久化。v-model 的 setter 走这里，落 localStorage 的只有这一处。 */
  function setSidebarCollapsed(next: boolean): void {
    sidebarCollapsed.value = next;
    localStorage.setItem(SIDEBAR_KEY, String(next));
  }

  function setInspectorCollapsed(next: boolean): void {
    inspectorCollapsed.value = next;
    localStorage.setItem(INSPECTOR_KEY, String(next));
  }

  function toggleSidebar(): void {
    setSidebarCollapsed(!sidebarCollapsed.value);
  }

  function toggleInspector(): void {
    setInspectorCollapsed(!inspectorCollapsed.value);
  }

  return {
    sidebarCollapsed,
    inspectorCollapsed,
    setSidebarCollapsed,
    setInspectorCollapsed,
    toggleSidebar,
    toggleInspector,
  };
});
