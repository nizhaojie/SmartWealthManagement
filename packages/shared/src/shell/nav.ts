import type { Component } from "vue";

/** 侧边导航项。key 是应用内的稳定标识，name 是留给测试与走查定位的 DOM 锚点。 */
export type AppShellNavItem = {
  key: string;
  label: string;
  name?: string;
  icon?: Component;
  /**
   * 导航徽标上的数字（02 的 `.nav-item em`）。壳只负责按 02 的样式渲染它，
   * 值由应用从真实接口算出后注入——壳不认识这个数字的业务含义。
   * 缺省与 0 都不渲染徽标。
   */
  badge?: number;
};
