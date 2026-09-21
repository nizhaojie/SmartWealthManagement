// 路由守卫与登出的门控测试：未登录重定向、深链、后退键、登出清 store。
// 逐页「挂载后断言文案出现」的用例不再复制（Q8）。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";
import { listAdvisoryRequests, listReleasedPlans } from "./advisory/api";
import App from "./App.vue";
import { getAssets, listTransactions } from "./assets/api";
import { login as loginRequest, logout as logoutRequest } from "./auth/api";
import { clearTokens, getAccessToken } from "./auth/tokenStore";
import { forgetUsername } from "./auth/username";
import { getFundingAccount } from "./funding/api";
import { listMyAdvice } from "./operation-advice/api";
import type { OperationAdvice } from "./operation-advice/types";
import { getCandidatePool, listProducts } from "./products/api";
import { getCurrentAssessment } from "./risk-assessment/api";
import { router, routes } from "./router";
import { useAuthStore } from "./stores/auth";
import { useChatStore } from "./stores/chat";

vi.mock("./auth/api", () => ({ login: vi.fn(), logout: vi.fn() }));
vi.mock("./assets/api", () => ({
  getAssets: vi.fn(),
  listTransactions: vi.fn(),
  getHoldingLookThrough: vi.fn(),
}));
vi.mock("./funding/api", () => ({ getFundingAccount: vi.fn() }));
vi.mock("./operation-advice/api", () => ({ listMyAdvice: vi.fn(), decideAdvice: vi.fn() }));
vi.mock("./risk-assessment/api", () => ({
  getCurrentAssessment: vi.fn(),
  getQuestionnaire: vi.fn(),
  saveDraft: vi.fn(),
  submitAssessment: vi.fn(),
}));
vi.mock("./products/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./products/api")>()),
  listProducts: vi.fn(),
  getProduct: vi.fn(),
  getCandidatePool: vi.fn(),
}));
vi.mock("./advisory/api", () => ({
  listAdvisoryRequests: vi.fn(),
  submitAdvisoryRequest: vi.fn(),
  listReleasedPlans: vi.fn(),
  getReleasedPlan: vi.fn(),
}));

let pinia: Pinia;
let activeWrapper: VueWrapper | null = null;

function mountApp(): VueWrapper {
  activeWrapper = mount(App, {
    global: { plugins: [pinia, ElementPlus, router] },
  }) as VueWrapper;
  return activeWrapper;
}

async function submitLogin(wrapper: VueWrapper, username: string, password: string): Promise<void> {
  await wrapper.find('input[name="username"]').setValue(username);
  await wrapper.find('input[name="password"]').setValue(password);
  await wrapper.find("form").trigger("submit.prevent");
  await flushPromises();
}

function mockSuccessfulLogin(): void {
  vi.mocked(loginRequest).mockResolvedValue({
    access_token: "access-token",
    refresh_token: "refresh-token",
  });
}

describe("客户应用·门控与路由", () => {
  beforeEach(async () => {
    clearTokens();
    forgetUsername();
    pinia = createPinia();
    setActivePinia(pinia);

    vi.mocked(loginRequest).mockReset();
    vi.mocked(logoutRequest).mockReset();
    vi.mocked(getCurrentAssessment).mockReset();
    vi.mocked(getAssets).mockReset();
    vi.mocked(listTransactions).mockReset();
    vi.mocked(listProducts).mockReset();
    vi.mocked(getCandidatePool).mockReset();
    vi.mocked(listAdvisoryRequests).mockReset();
    vi.mocked(listReleasedPlans).mockReset();
    vi.mocked(listMyAdvice).mockReset();
    vi.mocked(getFundingAccount).mockReset();

    vi.mocked(getCurrentAssessment).mockResolvedValue({ risk_level: "C1", valid_until: "2027-03-15" });
    vi.mocked(getAssets).mockResolvedValue({
      risk_level: "C1",
      risk_level_valid_until: "2027-03-15",
      total_market_value: "20420.00",
      holding_count: 1,
      holdings: [],
    });
    vi.mocked(listTransactions).mockResolvedValue({ transactions: [] });
    vi.mocked(listProducts).mockResolvedValue({ products: [] });
    vi.mocked(getCandidatePool).mockResolvedValue({
      assessment_id: 1,
      customer_risk_level: "C4",
      allowed_product_risk_levels: ["R1", "R2", "R3", "R4"],
      products: [],
    });
    vi.mocked(listAdvisoryRequests).mockResolvedValue({ requests: [] });
    vi.mocked(listReleasedPlans).mockResolvedValue({ plans: [] });
    vi.mocked(listMyAdvice).mockResolvedValue({ advice: [] });
    vi.mocked(getFundingAccount).mockResolvedValue({ available_balance: "100000.00" });

    await router.push("/login");
    await router.isReady();
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("redirects a deep link to the login page when not authenticated", async () => {
    await router.push("/products");
    const wrapper = mountApp();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.text()).toContain("客户登录");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(false);
  });

  it("enters the chat view after a successful login", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();

    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(router.currentRoute.value.path).toBe("/chat");
    expect(wrapper.find('input[name="chat-message"]').exists()).toBe(true);
  });

  it("sends an already authenticated visitor from /login to /chat", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    await router.push("/login");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/chat");
  });

  it("keeps the view after a refresh-style remount at the same URL", async () => {
    mockSuccessfulLogin();
    const first = mountApp();
    await submitLogin(first, "wangc1", "Test@1234");
    await router.push("/products");
    await flushPromises();
    first.unmount();

    const remounted = mountApp();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/products");
    expect(remounted.text()).toContain("这是符合条件的产品清单，不是推荐");
  });

  // 顶栏「登出」左侧要有当前用户名（客户登录时填写的账号）：登录后出现，登出后消失。
  it("shows the current username next to the logout button", async () => {
    mockSuccessfulLogin();
    vi.mocked(logoutRequest).mockResolvedValue(null);
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(wrapper.get('[data-testid="current-customer"]').text()).toBe("wangc1");

    await wrapper.get('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
    expect(wrapper.find('[data-testid="current-customer"]').exists()).toBe(false);
  });

  it("leaves the session and the conversation behind on logout", async () => {
    mockSuccessfulLogin();
    vi.mocked(logoutRequest).mockResolvedValue(null);
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    const chat = useChatStore();
    chat.beginTurn("上一场会话里的一句话");
    expect(chat.messages).toHaveLength(2);

    await wrapper.get('button[name="logout"]').trigger("click");
    await flushPromises();

    expect(logoutRequest).toHaveBeenCalled();
    expect(router.currentRoute.value.path).toBe("/login");
    expect(getAccessToken()).toBeNull();
    expect(useAuthStore().isAuthenticated).toBe(false);
    // 会话不跨登录延续：重新登录看到的是新会话。
    expect(chat.messages).toHaveLength(0);
  });

  it("sends the customer back to login when the session expires mid-session", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");
    expect(router.currentRoute.value.path).toBe("/chat");

    // 任一接口回 401 时 http 客户端会清掉令牌；人不该被留在必然报错的页面上。
    clearTokens();
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/login");
  });

  it("renders each view at its own URL and navigates from the shell nav", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    for (const name of [
      "risk-assessment",
      "products",
      "assets",
      "trading",
      "operation-advice",
      "advisory",
      "chat",
    ] as const) {
      await wrapper.get(`button[name="nav-${name}"]`).trigger("click");
      await flushPromises();
      expect(router.currentRoute.value.path).toBe(`/${name}`);
    }

    await router.push("/risk-assessment");
    await flushPromises();
    expect(wrapper.text()).toContain("保守型");

    await router.push("/products");
    await flushPromises();
    expect(wrapper.text()).toContain("这是符合条件的产品清单，不是推荐");

    await router.push("/assets");
    await flushPromises();
    expect(wrapper.get('[data-testid="asset-summary"]').text()).toContain("20420.00");
  });

  // 投顾内容的送达面有固定入口：「我的方案」是资料库，「我的建议」是收件箱，两者不合并。
  it("exposes 我的方案 as its own nav item and lands on its page", async () => {
    mockSuccessfulLogin();
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");

    expect(wrapper.findAll(".app-shell__nav-item")).toHaveLength(7);

    await wrapper.get('button[name="nav-advisory"]').trigger("click");
    await flushPromises();

    expect(router.currentRoute.value.path).toBe("/advisory");
    expect(wrapper.text()).toContain("还没有提交过方案请求");
  });

  // 待客户决定的建议不能等客户点进「我的建议」才被发现：侧栏角标要在首屏就出现。
  it("shows the pending badge on 我的建议 and drops it when nothing is pending", async () => {
    mockSuccessfulLogin();
    const pending: OperationAdvice = {
      id: 1,
      product_code: "F000002",
      product_name: "天玑债券基金",
      direction: "申购",
      amount: "50000.00",
      reason: "你的债券配置偏低",
      status: "待客户决定",
      released_at: "2026-09-21T09:00:00",
      expires_at: "2026-09-28T09:00:00",
      decision: null,
      decided_at: null,
      disclaimer: null,
    };
    vi.mocked(listMyAdvice).mockResolvedValue({ advice: [pending] });
    const wrapper = mountApp();
    await submitLogin(wrapper, "wangc1", "Test@1234");
    await flushPromises();

    expect(wrapper.get('button[name="nav-operation-advice"]').get(".app-shell__nav-badge").text()).toBe(
      "1",
    );

    // 没有待决定项时不渲染角标：0 与「还没加载」都不该显示一个数字。
    vi.mocked(listMyAdvice).mockResolvedValue({ advice: [] });
    await router.push("/operation-advice");
    await flushPromises();

    expect(wrapper.find(".app-shell__nav-badge").exists()).toBe(false);
  });

  it("returns to the previous view with the browser back button", async () => {
    // jsdom 不投递真实 history 遍历的 popstate，后退行为本身由 vue-router 负责，
    // 这里用同一份路由表 + memory history 验证路由表下的后退语义。
    mockSuccessfulLogin();
    const testRouter = createRouter({ history: createMemoryHistory(), routes });
    await testRouter.push("/login");
    await testRouter.isReady();
    const wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, testRouter] } });
    await submitLogin(wrapper, "wangc1", "Test@1234");
    expect(testRouter.currentRoute.value.path).toBe("/chat");

    await testRouter.push("/assets");
    await flushPromises();
    expect(testRouter.currentRoute.value.path).toBe("/assets");

    testRouter.back();
    await flushPromises();
    expect(testRouter.currentRoute.value.path).toBe("/chat");
    wrapper.unmount();
  });
});
