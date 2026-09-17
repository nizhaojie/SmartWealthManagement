import type { Component } from "vue";

/** 侧边导航项。key 是应用内的稳定标识，name 是留给测试与走查定位的 DOM 锚点。 */
export type AppShellNavItem = {
  key: string;
  label: string;
  name?: string;
  icon?: Component;
};
