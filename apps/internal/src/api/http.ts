import { createHttpClient } from "@wealth/shared";
import { clearTokens, getAccessToken } from "../auth/tokenStore";

// 内部员工身份域的 http 客户端。它与 customer 的那一份是各自独立的实例：
// 令牌来自 `wealth-internal-auth`，与 `wealth-customer-auth` 互不可见（ADR-0009 护栏 2）。
export const http = createHttpClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  // fetch 在调用时取全局那一份：模块加载时按值捕获会让运行时替换（测试替身、
  // 拦截层）失效——共享包的 createHttpClient 保留按值捕获是为了让调用方显式注入。
  fetchImpl: (input, init) => fetch(input, init),
  getToken: getAccessToken,
  // 会话失效的唯一处理点：清掉令牌 → auth store 的 isAuthenticated 变假 → App.vue 送回登录页。
  onUnauthorized: clearTokens,
});
