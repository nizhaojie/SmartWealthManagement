import type { ModuleId } from "../shell/modules";

// 路由 meta 只承载「壳读得懂」的两件事：这属于哪个模块、当前页面叫什么。
// 角色门控不进 meta —— 它由 ModuleView 按 modules.ts 的 roles 判定，只有一处事实源。
declare module "vue-router" {
  interface RouteMeta {
    /** public 路由不需要登录（只有登录页）。 */
    public?: boolean;
    /** 所属模块，决定侧栏激活项与面包屑的第一段。 */
    moduleId?: ModuleId;
    /** 面包屑的第二段（详情页用；模块首页省略）。 */
    pageLabel?: string;
  }
}

export {};
