import { ref } from "vue";

/**
 * 顶栏展示的当前用户名：客户登录时填写的账号。
 *
 * 客户侧没有取当前身份的接口（见 `stores/auth.ts` 的 `restore`），登录时账号就在客户端
 * 手上，就地留存即可，刷新页面也还在。它只用于显示，不参与任何鉴权判断——鉴权仍然只认
 * `tokenStore` 里的令牌。会话结束（登出或令牌失效）时与令牌一并清掉。
 */
const STORAGE_KEY = "wealth-customer-username";

function load(): string {
  return localStorage.getItem(STORAGE_KEY) ?? "";
}

export const currentUsername = ref<string>(load());

export function rememberUsername(next: string): void {
  currentUsername.value = next;
  localStorage.setItem(STORAGE_KEY, next);
}

export function forgetUsername(): void {
  currentUsername.value = "";
  localStorage.removeItem(STORAGE_KEY);
}
