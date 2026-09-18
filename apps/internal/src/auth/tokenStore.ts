import { createTokenStore } from "@wealth/shared";

// localStorage key 是身份域隔离的一半：internal 与 customer 各存各的，互不可见。
export const { tokens, getAccessToken, getRefreshToken, setTokens, clearTokens } =
  createTokenStore("wealth-internal-auth");
