// 侧栏折叠偏好。
//
// 折叠是浏览器级偏好，不随身份走：localStorage key 沿用 customer 既有前缀
// （tokenStore 的 `wealth-customer-auth`、username 的 `wealth-customer-username`），
// 登录 / 登出都不清空它——客户下次在同一浏览器打开时，侧栏还是上次收起的那个状态。
//
// 状态事实源是这里的一个布尔；`AppShell` 只认受控 prop（`sidebarCollapsed`）并 emit
// `update:sidebarCollapsed`，`CustomerShell` 用 v-model 把它接回这里写回 localStorage。
import { ref } from "vue";
import { defineStore } from "pinia";

const STORAGE_KEY = "wealth-customer-sidebar-collapsed";

function load(): boolean {
  // 只认字面量 "true"；缺省（无记录或任何其它值）一律展开。
  return localStorage.getItem(STORAGE_KEY) === "true";
}

export const useLayoutStore = defineStore("layout", () => {
  const sidebarCollapsed = ref<boolean>(load());

  /** 写回并持久化。v-model 的 setter 走这里，落 localStorage 的只有这一处。 */
  function setSidebarCollapsed(next: boolean): void {
    sidebarCollapsed.value = next;
    localStorage.setItem(STORAGE_KEY, String(next));
  }

  function toggleSidebar(): void {
    setSidebarCollapsed(!sidebarCollapsed.value);
  }

  return { sidebarCollapsed, setSidebarCollapsed, toggleSidebar };
});
