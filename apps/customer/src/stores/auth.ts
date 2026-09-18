// 客户侧登录态。
//
// 令牌的事实源仍然是既有的 auth/tokenStore（localStorage key `wealth-customer-auth`，
// http 客户端与对话流都从它取 Bearer）——Pinia 把「是否已登录 + 登录 / 登出」显式化，
// 但不另存一份令牌：同一条会话在两处内存态里各自漂移是引入 store 要消除的那类问题。
//
// 过渡说明：旧的 auth/store.ts（模块级单例）仍在被尚未重写的页面引用，
// 由 02 号 issue 的页面重写替换掉。
import { computed } from "vue";
import { defineStore } from "pinia";
import { login as loginRequest, logout as logoutRequest } from "../auth/api";
import { clearTokens, setTokens, tokens as storedTokens } from "../auth/tokenStore";

export const useAuthStore = defineStore("auth", () => {
  const tokens = storedTokens;
  const isAuthenticated = computed(() => tokens.value !== null);

  async function login(username: string, password: string): Promise<void> {
    const result = await loginRequest(username, password);
    setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest();
    } finally {
      clearTokens();
    }
  }

  /**
   * 恢复会话。客户侧没有「当前用户」接口，登录态就等于本地令牌是否存在——
   * tokenStore 在模块加载时已从 localStorage 读回，这里把结论显式交给启动时的守卫。
   */
  function restore(): boolean {
    return isAuthenticated.value;
  }

  return { tokens, isAuthenticated, login, logout, restore };
});
