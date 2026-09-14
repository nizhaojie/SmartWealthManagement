import { http } from "./http";

export type DependencyStatus = {
  ok: boolean;
};

export type HealthSnapshot = {
  status: "ok" | "degraded";
  dependencies: Record<string, DependencyStatus>;
  llm_provider: string;
};

export function fetchHealth(): Promise<HealthSnapshot> {
  return http.get<HealthSnapshot>("/api/health");
}
