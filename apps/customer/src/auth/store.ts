import { computed } from "vue";
import { login as loginRequest, logout as logoutRequest } from "./api";
import { clearTokens, setTokens, tokens } from "./tokenStore";

export const isAuthenticated = computed(() => tokens.value !== null);

export async function login(username: string, password: string): Promise<void> {
  const result = await loginRequest(username, password);
  setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
}

export async function logout(): Promise<void> {
  try {
    await logoutRequest();
  } finally {
    clearTokens();
  }
}
