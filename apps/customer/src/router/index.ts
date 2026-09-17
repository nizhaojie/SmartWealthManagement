import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import LoginPage from "../auth/LoginPage.vue";
import { isAuthenticated } from "../auth/store";
import AssetsPage from "../assets/AssetsPage.vue";
import ChatPage from "../chat/ChatPage.vue";
import ProductScreeningPage from "../products/ProductScreeningPage.vue";
import RiskAssessmentWorkspace from "../risk-assessment/RiskAssessmentWorkspace.vue";
import CustomerShell from "../shell/CustomerShell.vue";

export const routes: RouteRecordRaw[] = [
  { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
  {
    path: "/",
    component: CustomerShell,
    children: [
      { path: "", redirect: { name: "chat" } },
      { path: "chat", name: "chat", component: ChatPage },
      { path: "risk-assessment", name: "risk-assessment", component: RiskAssessmentWorkspace },
      { path: "products", name: "products", component: ProductScreeningPage },
      { path: "assets", name: "assets", component: AssetsPage },
    ],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  if (to.meta.public) {
    return isAuthenticated.value ? { name: "chat" } : true;
  }
  return isAuthenticated.value ? true : { name: "login" };
});
