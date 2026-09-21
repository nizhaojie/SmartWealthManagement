// 顾问的待审角标：数字钉在「投顾助手」导航项上，值来自 queueStore——与审核页卡片标题
// 读的是同一份取数，不是两处碰巧相等。
//
// 0 与取数失败都不渲染角标（AppShell 的 v-if 一并覆盖，不能改成恒显）：`0` 是一句断言
// （「没有待办」），而失败时我们并不知道有几件。角标跟着模块可见性走，不新增角色判断。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { useAdvisoryQueueStore } from "../advisory/queueStore";
import type { PendingReview } from "../advisory/types";
import { ACCOUNT_MANAGER, ADVISOR, type EmployeeRole } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { apiError, stubApiFetch } from "../testing";

const NAV_ADVISORY = 'button[name="nav-advisory"]';
const BADGE = `${NAV_ADVISORY} .app-shell__nav-badge`;

function pendingReview(id: number, overrides: Partial<PendingReview> = {}): PendingReview {
  return {
    content_type: "方案",
    content_ref: id,
    draft_id: id,
    customer_id: 9,
    customer_name: "王小明",
    status: "待审",
    tilt: "均衡",
    generated_at: "2026-09-18T10:00:00",
    waiting_seconds: 90,
    ...overrides,
  };
}

function queueOf(reviews: PendingReview[]) {
  return { pending_requests: [], pending_reviews: reviews };
}

/** 只认队列接口的 responder，其余 URL 走 testing 的默认响应。 */
function queueResponder(reviews: PendingReview[]) {
  return (url: string) =>
    url.includes("/api/internal/advisory/queue") ? queueOf(reviews) : undefined;
}

const DRAFT = {
  id: 7,
  customer_id: 9,
  advisor_id: 2,
  tilt: "均衡",
  content_classification: "投顾内容",
  candidates: [],
  allocation_suggestion: {},
  warnings: [],
  profile_computed_at: "2026-09-18T09:00:00",
  candidate_pool_snapshot: {},
  generated_at: "2026-09-18T10:00:00",
  advisory_request_id: null,
  disclaimer: "本方案为投顾内容，须经审核后送达。",
};

const FINAL = {
  id: 1,
  draft_id: 7,
  customer_id: 9,
  advisor_id: 2,
  advisor_name: "张顾问",
  content_classification: "投顾内容",
  candidates: [],
  allocation_suggestion: {},
  warnings: [],
  released_at: "2026-09-18T11:00:00",
  disclaimer: "本方案为投顾内容，须经审核后送达。",
};

const ADVICE = {
  id: 21,
  customer_id: 9,
  manager_id: 4,
  product_code: "F000001",
  product_name: "稳健增利一号",
  direction: "申购",
  amount: "200000.00",
  reason: "客户现金持仓偏高，且这只产品的期限与他的流动性安排一致。",
  content_classification: "投顾内容",
  generated_at: "2026-09-18T09:00:00",
  disclaimer: "本内容为投顾内容，须经审核后送达。",
};

// 审核页会把「当前客户」钉给检查器，检查器随后拉画像与资产。这两条不 stub 的话会落到
// testing 的 `/api/internal/customers` 默认值（空数组）上——数组是「取到了」，渲染随即打穿。
const PROFILE = {
  customer_id: 9,
  real_name: "王小明",
  computed_at: "2026-09-18T09:00:00",
  tags: [],
  conflict_records: [],
  judgement: {
    circuit_break: false,
    reasons: [],
    risk_level: "C3",
    dimension_scores: null,
    weighted_score: null,
  },
};

const ASSETS = {
  risk_level: "C3",
  risk_level_valid_until: null,
  total_market_value: "1000000.00",
  holding_count: 0,
  holdings: [],
};

let pinia: Pinia;
let wrapper: VueWrapper | null = null;

async function mountApp(respond: (url: string) => unknown, role: EmployeeRole = ADVISOR): Promise<VueWrapper> {
  stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: role };
    }
    if (url.includes("/customers/9/profile")) return PROFILE;
    if (url.includes("/customers/9/assets")) return ASSETS;
    return respond(url);
  });

  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, { global: { plugins: [pinia, ElementPlus, router] } });
  await flushPromises();
  return wrapper;
}

function navBadge(app: VueWrapper) {
  return app.find(BADGE);
}

beforeEach(() => {
  localStorage.clear();
  clearTokens();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  clearTokens();
});

describe("投顾助手的待审角标", () => {
  it("待审内容非空时角标出现，且值等于队列条数", async () => {
    const app = await mountApp(queueResponder([pendingReview(7), pendingReview(8)]));

    expect(navBadge(app).text()).toBe("2");
    // 角标只挂在投顾助手那一项上，不是一处全局计数。
    expect(app.findAll(".app-shell__nav-badge")).toHaveLength(1);
  });

  it("计数为 0 时不渲染角标", async () => {
    const app = await mountApp(queueResponder([]));

    expect(navBadge(app).exists()).toBe(false);
    expect(app.findAll(".app-shell__nav-badge")).toHaveLength(0);
    // 没有待办只让角标缺席，导航项本身照旧。
    expect(app.find(NAV_ADVISORY).exists()).toBe(true);
  });

  it("队列接口失败时不渲染角标，也不渲染 0", async () => {
    const app = await mountApp((url) =>
      url.includes("/api/internal/advisory/queue") ? apiError(500, "投顾队列加载失败") : undefined,
    );

    expect(app.find(BADGE).exists()).toBe(false);
    expect(app.get(NAV_ADVISORY).text()).not.toContain("0");
    // 「不知道」被计入 store 的失败态，角标只是它的一个读法。
    expect(useAdvisoryQueueStore(pinia).failed).toBe(true);
  });

  it("角标与审核页卡片标题同源：只 stub 一次接口，两处同时反映它", async () => {
    const app = await mountApp(queueResponder([pendingReview(7), pendingReview(8)]));

    await router.push("/advisory");
    await flushPromises();

    expect(app.get('[data-testid="pending-reviews-table"]').findAll("tbody tr")).toHaveLength(2);
    expect(app.text()).toContain("待审核（2）");
    expect(navBadge(app).text()).toBe("2");
  });

  it("放行成功后角标减一", async () => {
    let reviews = [pendingReview(7), pendingReview(8)];
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/advisory/queue")) return queueOf(reviews);
      if (url.includes("/drafts/7/release")) {
        reviews = [pendingReview(8)];
        return FINAL;
      }
      if (url.includes("/drafts/7/review")) return { draft_id: 7, status: "待审" };
      if (url.includes("/drafts/7/comments")) return { comments: [] };
      if (url.includes("/drafts/7")) return DRAFT;
      return undefined;
    });

    expect(navBadge(app).text()).toBe("2");

    await router.push("/advisory/reviews/7");
    await flushPromises();
    await app.get('[data-testid="release"]').trigger("click");
    await flushPromises();

    expect(navBadge(app).text()).toBe("1");
  });

  it("驳回成功后角标减一", async () => {
    let reviews = [pendingReview(7), pendingReview(8)];
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/advisory/queue")) return queueOf(reviews);
      if (url.includes("/drafts/7/reject")) {
        reviews = [pendingReview(8)];
        return { draft_id: 7, status: "已驳回", reason: "标的过于集中" };
      }
      if (url.includes("/drafts/7/review")) return { draft_id: 7, status: "待审" };
      if (url.includes("/drafts/7/comments")) return { comments: [] };
      if (url.includes("/drafts/7")) return DRAFT;
      return undefined;
    });

    expect(navBadge(app).text()).toBe("2");

    await router.push("/advisory/reviews/7");
    await flushPromises();
    await app.get('[data-testid="reject-reason"]').setValue("标的过于集中");
    await app.get('[data-testid="reject"]').trigger("click");
    await flushPromises();

    expect(navBadge(app).text()).toBe("1");
  });

  // 队列里两类内容共用一个数字（ADR-0020），因此操作建议侧的放行与驳回同样要让角标动。
  it("操作建议的放行也让角标减一", async () => {
    let reviews = [pendingReview(21, { content_type: "操作建议" }), pendingReview(22)];
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/advisory/queue")) return queueOf(reviews);
      if (url.includes("/operation-advice/21/release")) {
        reviews = [pendingReview(22)];
        return { id: 21, status: "已放行" };
      }
      if (url.includes("/operation-advice/21/review")) return { advice_id: 21, status: "待审" };
      if (url.includes("/operation-advice/21/comments")) return { comments: [] };
      if (url.includes("/operation-advice/21")) return ADVICE;
      return undefined;
    });

    expect(navBadge(app).text()).toBe("2");

    await router.push("/advisory/operation-advice/21");
    await flushPromises();
    await app.get('[data-testid="release"]').trigger("click");
    await flushPromises();

    expect(navBadge(app).text()).toBe("1");
  });

  it("操作建议的驳回也让角标减一", async () => {
    let reviews = [pendingReview(21, { content_type: "操作建议" }), pendingReview(22)];
    const app = await mountApp((url) => {
      if (url.includes("/api/internal/advisory/queue")) return queueOf(reviews);
      if (url.includes("/operation-advice/21/reject")) {
        reviews = [pendingReview(22)];
        return { id: 21, status: "已驳回", reason: "金额与客户流动性不符" };
      }
      if (url.includes("/operation-advice/21/review")) return { advice_id: 21, status: "待审" };
      if (url.includes("/operation-advice/21/comments")) return { comments: [] };
      if (url.includes("/operation-advice/21")) return ADVICE;
      return undefined;
    });

    expect(navBadge(app).text()).toBe("2");

    await router.push("/advisory/operation-advice/21");
    await flushPromises();
    await app.get('[data-testid="reject-reason"]').setValue("金额与客户流动性不符");
    await app.get('[data-testid="reject"]').trigger("click");
    await flushPromises();

    expect(navBadge(app).text()).toBe("1");
  });

  it("客户经理的导航里没有投顾助手项，因而没有角标", async () => {
    // 队列照旧有内容：角标不出现靠的是模块可见性，而不是多发一个角色判断。
    const app = await mountApp(queueResponder([pendingReview(7)]), ACCOUNT_MANAGER);

    expect(app.find(NAV_ADVISORY).exists()).toBe(false);
    expect(app.findAll(".app-shell__nav-badge")).toHaveLength(0);
  });
});
