import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";
import AdvisoryPlanDetailPage from "../advisory/AdvisoryPlanDetailPage.vue";
import AdvisoryPlanPage from "../advisory/AdvisoryPlanPage.vue";
import AssetsPage from "../assets/AssetsPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import ChatPage from "../chat/ChatPage.vue";
import ProductScreeningPage from "../products/ProductScreeningPage.vue";
import RiskAssessmentWorkspace from "../risk-assessment/RiskAssessmentWorkspace.vue";
import CustomerShell from "../shell/CustomerShell.vue";
import { useAuthStore } from "../stores/auth";

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
      { path: "advisory", name: "advisory", component: AdvisoryPlanPage },
      // 一份方案有自己的地址：列表与详情是两个可后退的页面，不是一个页面里的展开区。
      {
        path: "advisory/plans/:finalId",
        name: "advisory-plan",
        component: AdvisoryPlanDetailPage,
      },
    ],
  },
];

export const router = createRouter({
  history: createWebHistory(),
  routes,
});

// 门控只有两条：非 public 且未登录去登录页；已登录访问 public 回对话页。
// 登录态的结论由 auth store 的 restore() 给出——客户侧没有「当前用户」接口，
// 这就是 tokenStore 从 localStorage 读回的那份结论。
router.beforeEach((to) => {
  const authenticated = useAuthStore().restore();
  if (to.meta.public) {
    return authenticated ? { name: "chat" } : true;
  }
  return authenticated ? true : { name: "login" };
});
