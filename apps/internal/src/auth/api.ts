import { http } from "../api/http";

export type LoginResult = {
  access_token: string;
  refresh_token: string;
};

export function login(username: string, password: string): Promise<LoginResult> {
  return http.post<LoginResult>("/api/internal/auth/login", { username, password });
}
