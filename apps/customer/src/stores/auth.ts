// 客户侧登录态。
//
// 令牌的事实源仍然是 auth/tokenStore（localStorage key `wealth-customer-auth`），
// http 客户端与对话流都从它取 Bearer。Pinia 把「是否已登录 + 登录 / 登出」显式化，
// 但不另存一份令牌：同一条会话在两处内存态里各自漂移，正是引入 store 要消除的问题。
// currentUsername 是这条规则唯一的例外，它只喂顶栏那行展示文字，不参与鉴权（见 auth/username.ts）。
import { computed } from "vue";
import { defineStore } from "pinia";
import { login as loginRequest, logout as logoutRequest } from "../auth/api";
import { clearTokens, setTokens, tokens as storedTokens } from "../auth/tokenStore";
import { currentUsername, forgetUsername, rememberUsername } from "../auth/username";
import { useChatStore } from "./chat";

export const useAuthStore = defineStore("auth", () => {
  const tokens = storedTokens;
  const isAuthenticated = computed(() => tokens.value !== null);

  async function login(username: string, password: string): Promise<void> {
    const result = await loginRequest(username, password);
    setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
    // 顶栏「登出」左侧要显示当前用户名（客户登录时填写的账号），而客户侧没有取身份的接口。
    rememberUsername(username);
    // 会话不跨登录延续：上一次登录留下的消息不带进新会话。
    useChatStore().reset();
  }

  async function logout(): Promise<void> {
    try {
      await logoutRequest();
    } finally {
      clearTokens();
      forgetUsername();
      useChatStore().reset();
    }
  }

  /**
   * 恢复会话。客户侧没有「当前用户」接口，登录态就等于本地令牌是否存在——
   * tokenStore 在模块加载时已从 localStorage 读回，这里把结论显式交给启动时的守卫。
   */
  function restore(): boolean {
    return isAuthenticated.value;
  }

  return { tokens, currentUsername, isAuthenticated, login, logout, restore };
});
