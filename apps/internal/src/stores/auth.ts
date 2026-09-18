// 员工登录态：令牌 + 当前员工身份。
//
// 令牌的事实源仍是既有的 auth/tokenStore（localStorage key `wealth-internal-auth`，
// http 客户端从它取 Bearer）——两个应用各用各的 key，身份域隔离（ADR-0009 护栏 2）
// 不因为引入 store 而改变。
//
// 过渡说明：旧的 auth/store.ts（模块级单例）仍在被尚未重写的页面引用，
// 由 03 号 issue 的页面重写替换掉。
import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { login as loginRequest, requestLogout } from "../auth/api";
import { fetchCurrentEmployee, type EmployeeIdentity } from "../auth/identity";
import { clearTokens, setTokens, tokens as storedTokens } from "../auth/tokenStore";

export const useAuthStore = defineStore("auth", () => {
  const tokens = storedTokens;
  const currentEmployee = ref<EmployeeIdentity | null>(null);
  const isAuthenticated = computed(() => tokens.value !== null);

  function clearSession(): void {
    currentEmployee.value = null;
    clearTokens();
  }

  async function loadCurrentEmployee(): Promise<boolean> {
    try {
      currentEmployee.value = await fetchCurrentEmployee();
      return true;
    } catch {
      clearSession();
      return false;
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const result = await loginRequest(username, password);
    setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
    if (!(await loadCurrentEmployee())) {
      throw new Error("登录后加载员工信息失败");
    }
  }

  async function restoreSession(): Promise<void> {
    await loadCurrentEmployee();
  }

  function logout(): void {
    void requestLogout().catch(() => undefined);
    clearSession();
  }

  return { tokens, currentEmployee, isAuthenticated, login, restoreSession, logout };
});
