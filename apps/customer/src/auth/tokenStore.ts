import { createTokenStore } from "@wealth/shared";

// localStorage key 是客户身份域的边界：internal 用另一个 key，两边的令牌互不通用。
export const { tokens, getAccessToken, getRefreshToken, setTokens, setAccessToken, clearTokens } =
  createTokenStore("wealth-customer-auth");
