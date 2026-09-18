import { createHttpClient } from "@wealth/shared";
import { clearTokens, getAccessToken } from "../auth/tokenStore";

/** 后端基址：http 客户端与对话流共用同一个来源，避免第二处再解析一遍 VITE_API_BASE_URL。 */
export function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
}

/** 会话失效的唯一处理点：http 客户端与对话流都挂这一个回调，避免两条 401 路径漂移。 */
export function handleExpiredSession(): void {
  clearTokens();
}

// 客户身份域的 http 客户端。它与 internal 的那一份是各自独立的实例：
// 令牌来自 `wealth-customer-auth`，与 `wealth-internal-auth` 互不可见（ADR-0009 护栏 2）。
export const http = createHttpClient({
  baseUrl: apiBaseUrl(),
  getToken: getAccessToken,
  onUnauthorized: handleExpiredSession,
});
