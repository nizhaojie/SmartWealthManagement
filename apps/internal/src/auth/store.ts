import { computed, ref } from "vue";
import { login as loginRequest, requestLogout } from "./api";
import { fetchCurrentEmployee, type EmployeeIdentity } from "./identity";
import { clearTokens, setTokens, tokens } from "./tokenStore";

export const isAuthenticated = computed(() => tokens.value !== null);
export const currentEmployee = ref<EmployeeIdentity | null>(null);

function clearSession(): void {
  currentEmployee.value = null;
  clearTokens();
}

async function loadCurrentEmployee(): Promise<boolean> {
  try {
    currentEmployee.value = await fetchCurrentEmployee();
    return true;
  } catch {
    clearSession();
    return false;
  }
}

export async function login(username: string, password: string): Promise<void> {
  const result = await loginRequest(username, password);
  setTokens({ accessToken: result.access_token, refreshToken: result.refresh_token });
  const loaded = await loadCurrentEmployee();
  if (!loaded) {
    throw new Error("登录后加载员工信息失败");
  }
}

export async function restoreSession(): Promise<void> {
  await loadCurrentEmployee();
}

export function logout(): void {
  void requestLogout().catch(() => undefined);
  clearSession();
}
