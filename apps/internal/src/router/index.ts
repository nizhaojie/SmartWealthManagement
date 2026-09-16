import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import AdvisoryReviewPage from "../advisory/AdvisoryReviewPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import { currentEmployee, isAuthenticated, restoreSession } from "../auth/store";
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

const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
  {
    path: "/",
    component: WorkbenchShell,
    children: [...moduleRoutes, advisoryReviewRoute],
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
