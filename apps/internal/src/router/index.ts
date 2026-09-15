import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
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

const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
  {
    path: "/",
    component: WorkbenchShell,
    children: moduleRoutes,
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
