import { http } from "../api/http";

export type LoginResult = {
  access_token: string;
  refresh_token: string;
};

export function login(username: string, password: string): Promise<LoginResult> {
  return http.post<LoginResult>("/api/customer/auth/login", { username, password });
}

export function logout(): Promise<null> {
  return http.post<null>("/api/customer/auth/logout");
}
