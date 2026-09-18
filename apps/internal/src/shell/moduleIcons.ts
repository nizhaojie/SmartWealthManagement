import type { Component } from "vue";
import {
  Avatar,
  Collection,
  DataAnalysis,
  MagicStick,
  Tickets,
  User,
  Warning,
} from "@element-plus/icons-vue";
import type { ModuleId } from "./modules";

const MODULE_ICONS: Record<ModuleId, Component> = {
  knowledge: Collection,
  "data-analysis": DataAnalysis,
  profile: User,
  advisory: MagicStick,
  "risk-monitoring": Warning,
  "work-orders": Tickets,
  "customer-relations": Avatar,
};

export function iconForModule(id: ModuleId): Component {
  return MODULE_ICONS[id];
}
