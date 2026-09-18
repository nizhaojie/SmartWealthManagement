import { ACCOUNT_MANAGER, ADVISOR, RISK_OFFICER, type EmployeeRole } from "../auth/identity";

/**
 * 七个一级模块。顺序即侧栏顺序与落地页入口顺序。
 *
 * 角色可见性留在应用内（**不进 shared**）：壳层的「谁能看见什么」是内部工作台的
 * 组织事实，不是两端共用的展示件能力。
 */
export const MODULE_IDS = [
  "knowledge",
  "data-analysis",
  "profile",
  "advisory",
  "risk-monitoring",
  "work-orders",
  "customer-relations",
] as const;

export type ModuleId = (typeof MODULE_IDS)[number];

export type ModuleDefinition = {
  id: ModuleId;
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
    // （排除、升级、派生工单）只放开给风控专员——后端按角色再挡一次，界面把处置
    // 表单换成一句说明。客户经理的可见范围收紧到名下客户，与工单、审核一致。
    description: "查看风控预警与风险关注；风控专员在此处置。",
    roles: ALL_ROLES,
  },
  {
    id: "work-orders",
    path: "/work-orders",
    label: "工单管理",
    // 工单从风控监测的 tab 里拆出来成为一级模块：它可以来自预警，也可以来自客户投诉
    // 与转人工，从来不是预警的附属物。
    description: "查看与流转工单；工单可来自预警处置，也可来自客户投诉与转人工。",
    roles: ALL_ROLES,
  },
  {
    id: "customer-relations",
    path: "/customer-relations",
    label: "客户关系",
    // 「服务记录」在后端不存在（没有对应接口），模块描述不承诺它。
    description: "查看名下客户的基本信息与分层，并为新客户开户。",
    roles: [ACCOUNT_MANAGER],
  },
];

export function getModule(id: string | undefined): ModuleDefinition | undefined {
  return MODULES.find((module) => module.id === id);
}

export function visibleModules(role: EmployeeRole | null | undefined): ModuleDefinition[] {
  if (!role) return [];
  return MODULES.filter((module) => module.roles.includes(role));
}
