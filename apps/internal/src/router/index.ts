import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import AdvisoryReviewPage from "../advisory/AdvisoryReviewPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import AlertDetailPage from "../risk/AlertDetailPage.vue";
import LandingPage from "../shell/LandingPage.vue";
import AdviceReviewPage from "../operation-advice/AdviceReviewPage.vue";
import ModuleView from "../shell/ModuleView.vue";
import WorkbenchShell from "../shell/WorkbenchShell.vue";
import { MODULES } from "../shell/modules";
import { useAuthStore } from "../stores/auth";
import WorkOrderDetailPage from "../work-orders/WorkOrderDetailPage.vue";
import "./routeMeta";

/** 七个模块各自一条 index 路由，主区统一由 ModuleView 按角色裁量。 */
const moduleRoutes: RouteRecordRaw[] = MODULES.map((module) => ({
  path: module.path.slice(1),
  name: module.id,
  component: ModuleView,
  meta: { moduleId: module.id },
}));

/**
 * 详情页绕过 ModuleView 的角色过滤：能不能看由后端 403 决定，页面把处置动作
 * 按角色门控。硬在前端拦住它们只会让「客户经理能看但不能审」这类既有行为消失。
 */
const detailRoutes: RouteRecordRaw[] = [
  {
    path: "advisory/reviews/:draftId",
    name: "advisory-review",
    component: AdvisoryReviewPage,
    meta: { moduleId: "advisory", pageLabel: "审核" },
  },
  {
    // 操作建议的审核页：与方案审核页并列，载荷不同所以不是同一个组件（ADR-0020）。
    // 客户经理也从这里打开它（入口在客户关系模块的进度表），因此它同样绕过
    // ModuleView 的角色过滤，能不能看由后端 403 决定。
    path: "advisory/operation-advice/:adviceId",
    name: "operation-advice-review",
    component: AdviceReviewPage,
    meta: { moduleId: "advisory", pageLabel: "操作建议审核" },
  },
  {
    path: "risk-monitoring/alerts/:alertId",
    name: "risk-alert-detail",
    component: AlertDetailPage,
    meta: { moduleId: "risk-monitoring", pageLabel: "预警详情" },
  },
  {
    path: "work-orders/:workOrderId",
    name: "work-order-detail",
    component: WorkOrderDetailPage,
    meta: { moduleId: "work-orders", pageLabel: "工单详情" },
  },
];

export const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
  {
    path: "/",
    component: WorkbenchShell,
    children: [
      { path: "", name: "landing", component: LandingPage, meta: { pageLabel: "工作台" } },
      ...moduleRoutes,
      ...detailRoutes,
    ],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

// 门控只有两条：非 public 且未登录去登录页；已登录访问 login 回落地页。
// 深链进来时先恢复会话（拿一次 /auth/me），恢复不了就当没登录。
router.beforeEach(async (to) => {
  const auth = useAuthStore();

  if (to.meta.public) {
    if (!auth.isAuthenticated) {
      return true;
    }
    const restored = await auth.restoreSession();
    return restored ? { path: "/" } : true;
  }

  if (!auth.isAuthenticated) {
    return { name: "login" };
  }

  const restored = await auth.restoreSession();
  return restored ? true : { name: "login" };
});
