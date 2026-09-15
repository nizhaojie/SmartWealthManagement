import { createHttpClient } from "@wealth/shared";
import { clearTokens, getAccessToken } from "../auth/tokenStore";

export const http = createHttpClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  getToken: getAccessToken,
  onUnauthorized: clearTokens,
});
