import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { login as loginRequest, logout as logoutRequest } from "../auth/api";
import { fetchCurrentEmployee, type EmployeeIdentity } from "../auth/identity";
import { clearTokens, setTokens, tokens as storedTokens } from "../auth/tokenStore";
import { useCurrentCustomerStore } from "./currentCustomer";

/**
 * 内部工作台的登录态。
 *
 * 令牌的事实源仍然是 `auth/tokenStore`（localStorage key `wealth-internal-auth`），
 * store 不另存一份令牌——同一条会话在两处内存态里各自漂移，正是引入 store 要消除的问题。
 * store 把「我是谁 + 是否已登录 + 登录 / 登出 / 恢复」显式化。
 */
export const useAuthStore = defineStore("auth", () => {
  const tokens = storedTokens;
  const currentEmployee = ref<EmployeeIdentity | null>(null);
  const isAuthenticated = computed(() => tokens.value !== null);

  /**
   * 取当前员工身份。拿不到（请求失败，或后端给了个空壳）都算这一轮登录失败——
   * 「我是谁」决定了整个工作台可见什么，缺了它留在页面上也做不了任何事。
   */
  async function loadIdentity(): Promise<EmployeeIdentity> {
    const identity = await fetchCurrentEmployee();
    if (!identity || !identity.employee_role) {
      throw new Error("未能取得员工身份");
    }
    return identity;
  }

  /**
   * 登录 = 换令牌 + 拿到身份。`GET /api/internal/auth/me` 失败视为登录失败：
   * 留着令牌进不了任何页面，不如就地清掉，让人重新登录。
   */
  async function login(username: string, password: string): Promise<void> {
    const result = await loginRequest(username, password);
    setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
    try {
      currentEmployee.value = await loadIdentity();
    } catch (error) {
      currentEmployee.value = null;
      clearTokens();
      throw error;
    }
  }

  /** 刷新页面后恢复会话：有令牌就把身份重新取回来，取不到就当没登录。 */
  async function restoreSession(): Promise<boolean> {
    if (!isAuthenticated.value) {
      currentEmployee.value = null;
      return false;
    }
    if (currentEmployee.value) {
      return true;
    }
    try {
      currentEmployee.value = await loadIdentity();
      return true;
    } catch {
      currentEmployee.value = null;
      clearTokens();
      return false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest();
    } catch {
      // 登出请求失败也要清本地：把人留在原页面只会让他看着一个必然报错的界面。
    } finally {
      clearTokens();
      currentEmployee.value = null;
      // 当前客户是上一条会话的上下文，不跨登录延续。
      useCurrentCustomerStore().clear();
    }
  }

  return { tokens, currentEmployee, isAuthenticated, login, restoreSession, logout };
});
