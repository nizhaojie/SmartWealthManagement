import type { Component } from "vue";
import { Avatar, Collection, DataAnalysis, MagicStick, User, Warning } from "@element-plus/icons-vue";
import type { ModuleId } from "./modules";

// 模块 id → 图标。侧边导航与落地页入口卡片共用同一份映射；
// 键收窄为 MODULES 的字面量 id 联合，新增模块漏配图标会直接编译失败。
export const MODULE_ICONS: Record<ModuleId, Component> = {
  knowledge: Collection,
  "data-analysis": DataAnalysis,
  profile: User,
  advisory: MagicStick,
  "risk-monitoring": Warning,
  "customer-relations": Avatar,
};

export function iconForModule(id: string): Component | undefined {
  return MODULE_ICONS[id as ModuleId];
}
