import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import AdvisoryReviewPage from "../advisory/AdvisoryReviewPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import { currentEmployee, isAuthenticated, restoreSession } from "../auth/store";
import AlertDetailPage from "../risk/AlertDetailPage.vue";
import WorkOrderDetailPage from "../risk/WorkOrderDetailPage.vue";
import ModuleView from "../shell/ModuleView.vue";
import { defaultPathFor, MODULES } from "../shell/modules";
import WorkbenchShell from "../shell/WorkbenchShell.vue";

const moduleRoutes: RouteRecordRaw[] = MODULES.map((module) => ({
  path: module.path.slice(1),
  name: module.id,
  component: ModuleView,
  meta: { moduleId: module.id },
}));

// 独立于 advisory 模块的角色门槛之外：审核页要能被客户经理直接用链接
// 打开（见 issue 04），查看范围收紧在组件与后端各自校验，不经过
// ModuleView 的按模块角色过滤，否则客户经理会被 ModuleForbidden 拦下。
const advisoryReviewRoute: RouteRecordRaw = {
  path: "advisory/reviews/:draftId",
  name: "advisory-review",
  component: AdvisoryReviewPage,
  meta: { moduleId: "advisory" },
};

// 预警详情与工单处置页各有独立 URL：风控专员要能把一条预警的链接直接发给同事
// （见 issue 04）。它们同样不经过 ModuleView 的角色过滤——能看哪一条由后端按
// 客户归属判定，组件把 403 渲染成「无权查看」。
const riskAlertRoute: RouteRecordRaw = {
  path: "risk-monitoring/alerts/:alertId",
  name: "risk-alert-detail",
  component: AlertDetailPage,
  meta: { moduleId: "risk-monitoring" },
};

const riskWorkOrderRoute: RouteRecordRaw = {
  path: "risk-monitoring/work-orders/:workOrderId",
  name: "risk-work-order-detail",
  component: WorkOrderDetailPage,
  meta: { moduleId: "risk-monitoring" },
};

const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
  {
    path: "/",
    component: WorkbenchShell,
    children: [...moduleRoutes, advisoryReviewRoute, riskAlertRoute, riskWorkOrderRoute],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

async function ensureIdentityLoaded(): Promise<void> {
  if (!currentEmployee.value) {
    await restoreSession();
  }
}

function defaultRedirect() {
  return { path: defaultPathFor(currentEmployee.value?.employee_role) };
}

router.beforeEach(async (to) => {
  if (to.meta.public) {
    if (!isAuthenticated.value) {
      return true;
    }
    await ensureIdentityLoaded();
    return isAuthenticated.value ? defaultRedirect() : true;
  }

  if (!isAuthenticated.value) {
    return { path: "/login" };
  }
  await ensureIdentityLoaded();
  if (!isAuthenticated.value) {
    return { path: "/login" };
  }
  return to.path === "/" ? defaultRedirect() : true;
});
