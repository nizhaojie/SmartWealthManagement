import { createTokenStore } from "@wealth/shared";

export const { tokens, getAccessToken, getRefreshToken, setTokens, clearTokens } =
  createTokenStore("wealth-internal-auth");
