import { createHttpClient } from "@wealth/shared";
import { clearTokens, getAccessToken, getRefreshToken, setAccessToken } from "../auth/tokenStore";

type RenewedAccessToken = {
  access_token: string;
};

// 续期请求自己走一个「不挂续期钩子、也不挂失效回调」的裸客户端：
// 否则刷新失败会递归回本模块的续期逻辑，两边互相不认时转圈。
const renewalClient = createHttpClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  fetchImpl: (input, init) => fetch(input, init),
});

/**
 * 用 refresh token 换一张新的 access token（后端 `/auth/refresh` 只发 access token）。
 *
 * 返回是否换到，**不清令牌**：续期失败只说明这条路走不通，收场方式由 http 客户端的
 * `onUnauthorized` 统一决定，避免两处各清一次。
 */
export async function renewSession(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    return false;
  }
  try {
    const result = await renewalClient.post<RenewedAccessToken>("/api/internal/auth/refresh", {
      refresh_token: refreshToken,
    });
    setAccessToken(result.access_token);
    return true;
  } catch {
    return false;
  }
}

// 内部员工身份域的 http 客户端。它与 customer 的那一份是各自独立的实例：
// 令牌来自 `wealth-internal-auth`，与 `wealth-customer-auth` 互不可见（ADR-0009 护栏 2）。
export const http = createHttpClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  // fetch 在调用时取全局那一份：模块加载时按值捕获会让运行时替换（测试替身、
  // 拦截层）失效——共享包的 createHttpClient 保留按值捕获是为了让调用方显式注入。
  fetchImpl: (input, init) => fetch(input, init),
  getToken: getAccessToken,
  // access token 有效期 15 分钟。过期不是会话结束——先换一张再重发（深链进来时
  // 守卫里的 /auth/me 也走这条路），换不到才清令牌送回登录页。
  renewTokens: renewSession,
  // 会话失效的唯一处理点：清掉令牌 → auth store 的 isAuthenticated 变假 → App.vue 送回登录页。
  onUnauthorized: clearTokens,
});
