import { http } from "../api/http";

export const ADVISOR = "理财顾问";
export const RISK_OFFICER = "风控专员";
export const ACCOUNT_MANAGER = "客户经理";

export type EmployeeRole = typeof ADVISOR | typeof RISK_OFFICER | typeof ACCOUNT_MANAGER;

export type EmployeeIdentity = {
  real_name: string;
  employee_role: EmployeeRole;
};

export function fetchCurrentEmployee(): Promise<EmployeeIdentity> {
  return http.get<EmployeeIdentity>("/api/internal/auth/me");
}
