import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER, type EmployeeRole } from "../auth/identity";

export type ModuleDefinition = {
  id: string;
  path: string;
  label: string;
  description: string;
  roles: EmployeeRole[];
};

const ALL_ROLES: EmployeeRole[] = [ADVISOR, RISK_OFFICER, ACCOUNT_MANAGER];

export const MODULES: ModuleDefinition[] = [
  {
    id: "knowledge",
    path: "/knowledge",
    label: "知识库管理",
    description: "上传与维护 FAQ、产品资料与政策文档，试验检索质量。",
    roles: ALL_ROLES,
  },
  {
    id: "data-analysis",
    path: "/data-analysis",
    label: "数据分析",
    description: "用自然语言提出数据问题，得到受限查询与解读结果。",
    roles: ALL_ROLES,
  },
  {
    id: "profile",
    path: "/profile",
    label: "客户画像",
    description: "查看客户的风险承受等级、投资经验、资产规模、目标配置与产品偏好。",
    roles: [ADVISOR],
  },
  {
    id: "advisory",
    path: "/advisory",
    label: "投顾助手",
    description: "生成客户画像分析、产品推荐与配置方案，并审核放行投顾内容。",
    roles: [ADVISOR],
  },
  {
    id: "risk-monitoring",
    path: "/risk-monitoring",
    label: "风控监测",
    // 三个角色都能进：理财顾问与客户经理要看得见自己客户的预警状态，而处置
    // （排除、升级、工单流转）只放开给风控专员——后端按角色再挡一次，界面把
    // 处置表单换成一句说明。客户经理的可见范围收紧到名下客户，与工单、审核一致。
    description: "查看风控预警与工单；风控专员在此处置。",
    roles: ALL_ROLES,
  },
  {
    id: "customer-relations",
    path: "/customer-relations",
    label: "客户关系",
    description: "查看归属客户的基本信息与服务记录。",
    roles: [ACCOUNT_MANAGER],
  },
];

export function getModule(id: string | undefined): ModuleDefinition | undefined {
  return MODULES.find((module) => module.id === id);
}

export function visibleModules(role: EmployeeRole): ModuleDefinition[] {
  return MODULES.filter((module) => module.roles.includes(role));
}

export function defaultPathFor(role: EmployeeRole | null | undefined): string {
  if (!role) {
    return "/login";
  }
  return visibleModules(role)[0]?.path ?? "/login";
}
