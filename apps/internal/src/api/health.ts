import { http } from "./http";

export type HealthSnapshot = {
  status: "ok" | "degraded";
  dependencies: Record<string, { ok: boolean }>;
  llm_provider: string;
};

export function fetchHealth(): Promise<HealthSnapshot> {
  return http.get<HealthSnapshot>("/api/health");
}
