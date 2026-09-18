import { http } from "../api/http";

export const ADVISOR = "理财顾问";
export const RISK_OFFICER = "风控专员";
export const ACCOUNT_MANAGER = "客户经理";

export const ALL_ROLES = [ADVISOR, RISK_OFFICER, ACCOUNT_MANAGER] as const;

export type EmployeeRole = (typeof ALL_ROLES)[number];

export type EmployeeIdentity = {
  real_name: string;
  employee_role: EmployeeRole;
};

/**
 * 当前员工身份。登录成功之后必须能拿到它——拿不到就当这次登录失败，
 * 因为「我是谁」决定了整个工作台可见什么。
 */
export function fetchCurrentEmployee(): Promise<EmployeeIdentity> {
  return http.get<EmployeeIdentity>("/api/internal/auth/me");
}
