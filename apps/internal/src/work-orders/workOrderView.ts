import { RISK_OFFICER, type EmployeeRole } from "../auth/identity";
import type { WorkOrderStatus } from "./types";

/**
 * 工单能流转的两个状态，以及唯一能流转它的角色。
 *
 * 终态（已完成 / 已关闭）没有下一步——这与后端 `NEXT_STATUSES` 是同一张表，
 * 界面据此把处置表单换成一句说明，而不是让按钮点下去才报 409。
 */
export function canHandleWorkOrder(
  employeeRole: EmployeeRole | undefined,
  status: WorkOrderStatus,
): boolean {
  return employeeRole === RISK_OFFICER && (status === "待处理" || status === "处理中");
}

/** 外部建单同样只放开给风控专员（后端 `POST /work-orders` 的角色门槛）。 */
export function canCreateWorkOrder(employeeRole: EmployeeRole | undefined): boolean {
  return employeeRole === RISK_OFFICER;
}

export function workOrderTagType(
  status: WorkOrderStatus,
): "warning" | "primary" | "success" | "info" {
  if (status === "处理中") return "primary";
  if (status === "已完成") return "success";
  if (status === "已关闭") return "info";
  return "warning";
}

/** 流转留痕里「从哪来」：建单那一跳没有来源状态。 */
export function transitionFromLabel(from: WorkOrderStatus | null): string {
  return from ?? "建单";
}
