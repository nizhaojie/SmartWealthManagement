import { createHttpClient } from "@wealth/shared";
import { clearTokens, getAccessToken, getRefreshToken, setAccessToken } from "../auth/tokenStore";
import { forgetUsername } from "../auth/username";

/** 后端基址：http 客户端与对话流共用同一个来源，避免第二处再解析一遍 VITE_API_BASE_URL。 */
export function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
}

/** 会话失效的唯一处理点：http 客户端与对话流都挂这一个回调，避免两条 401 路径漂移。 */
export function handleExpiredSession(): void {
  clearTokens();
  // 顶栏展示名与令牌同生同灭：会话失效时一并清掉，不留过期账号。
  forgetUsername();
}

type RenewedAccessToken = {
  access_token: string;
};

// 续期请求自己走一个「不挂续期钩子、也不挂失效回调」的裸客户端：
// 否则刷新失败会递归回本模块的续期逻辑，两边互相不认时转圈。
const renewalClient = createHttpClient({
  baseUrl: apiBaseUrl(),
  fetchImpl: (input, init) => fetch(input, init),
});

/**
 * 用 refresh token 换一张新的 access token（后端 `/auth/refresh` 只发 access token）。
 *
 * 返回是否换到，**不清令牌**：续期失败只说明这条路走不通，收场方式（清令牌、送回登录页）
 * 由 http 客户端的 `onUnauthorized` 统一决定，避免两处各清一次。
 */
export async function renewSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }
  try {
    const result = await renewalClient.post<RenewedAccessToken>("/api/customer/auth/refresh", {
      refresh_token: refreshToken,
    });
    setAccessToken(result.access_token);
    return true;
  } catch {
    return false;
  }
}

// 客户身份域的 http 客户端。它与 internal 的那一份是各自独立的实例：
// 令牌来自 `wealth-customer-auth`，与 `wealth-internal-auth` 互不可见（ADR-0009 护栏 2）。
export const http = createHttpClient({
  baseUrl: apiBaseUrl(),
  getToken: getAccessToken,
  // access token 有效期 15 分钟。过期不是会话结束——先换一张再重发，
  // 换不到才交给 handleExpiredSession 送回登录页。
  renewTokens: renewSession,
  onUnauthorized: handleExpiredSession,
});
