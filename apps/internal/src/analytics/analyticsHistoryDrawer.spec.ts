// 历史查询抽屉（ticket 05）：留痕从右栏搬进顶栏的抽屉，右栏因此塌成两栏。
//
// 挂 `App.vue` 而不是单挂工作区，是因为两件事只有在这一层才成立：顶栏那个入口是壳转发
// 页面级操作渲染出来的，第三栏在不在也由壳裁定。抽屉自己的行为（列记录、SQL 行内展开、
// 「再问一次」、分页走服务端）同样在真实壳里验——免得「搬进抽屉了」只对了一半。
//
// 旧文件（`analyticsHistoryRail.spec.ts`）的前提是「证明这张卡真的在第三栏」，那个前提
// 已经不存在：这里不是给它打补丁，是换一组问题。
import ElementPlus from "element-plus";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.vue";
import { ADVISOR } from "../auth/identity";
import { clearTokens, setTokens } from "../auth/tokenStore";
import { router } from "../router";
import { apiError, requestedUrls, stubApiFetch } from "../testing";

const HISTORY_ITEMS = [
  {
    id: 7,
    question: "上个月各风险等级的客户分布",
    sql: "SELECT risk_level, count(*) FROM v_customer GROUP BY risk_level",
    status: "成功",
    row_count: 5,
    truncated: false,
    error_code: null,
    create_time: "2026-09-18T10:00:00",
  },
  {
    id: 6,
    question: "查一下这个月的交易笔数",
    sql: "SELECT count(*) FROM v_transaction",
    status: "校验拒绝",
    row_count: null,
    truncated: false,
    error_code: 1103,
    create_time: "2026-09-17T09:00:00",
  },
  {
    id: 5,
    question: "查一下全部客户的持仓明细",
    sql: "SELECT * FROM v_holding",
    status: "成功",
    row_count: 200,
    truncated: true,
    error_code: null,
    create_time: "2026-09-16T08:00:00",
  },
];

/** 历史查询接口的一页（ADR-0024）：形状恒为 `{items, total, page, page_size}`。 */
function historyPage(
  items: unknown[] = HISTORY_ITEMS,
  overrides: Record<string, unknown> = {},
) {
  return { items, total: items.length, page: 1, page_size: 10, ...overrides };
}

const EXAMPLE = "上个月各风险等级的客户分布";

const ANSWER = {
  question: "这个月新增了几个客户",
  sql: "SELECT count(*) FROM v_customer",
  columns: ["count"],
  rows: [[3]],
  row_count: 1,
  truncated: false,
  views: ["v_customer"],
  interpretation: "这个月新增 3 位客户。",
  content_classification: "事实性",
  disclaimer: null,
};

let pinia: Pinia;
let wrapper: VueWrapper | null = null;
let fetchMock: ReturnType<typeof stubApiFetch>;

async function mountAnalysis(
  options: { history?: unknown; historyResponder?: (url: string) => unknown } = {},
): Promise<VueWrapper> {
  fetchMock = stubApiFetch((url) => {
    if (url.includes("/api/internal/auth/me")) {
      return { real_name: "测试员工", employee_role: ADVISOR };
    }
    if (url.includes("/api/internal/analytics/history")) {
      if (options.historyResponder) {
        return options.historyResponder(url);
      }
      return options.history ?? historyPage();
    }
    if (url.includes("/api/internal/analytics/examples")) {
      return [{ question: EXAMPLE }];
    }
    if (url.includes("/api/internal/analytics/query")) {
      return ANSWER;
    }
    return undefined;
  });

  pinia = createPinia();
  setActivePinia(pinia);
  setTokens({ accessToken: "access-token", refreshToken: "refresh-token" });
  await router.push("/");
  await router.isReady();
  wrapper = mount(App, {
    global: {
      plugins: [pinia, ElementPlus, router],
      // 抽屉默认挂到 body 上（`append-to-body`）：就地渲染，用例才不用去 document 里翻。
      stubs: { teleport: true },
    },
  });
  await flushPromises();
  await router.push("/data-analysis");
  await flushPromises();
  return wrapper;
}

/** 顶栏那个入口：抽屉的唯一入口（页头的「清空对话」是另一件事）。 */
async function openHistory(app: VueWrapper): Promise<void> {
  await app.get('[data-testid="open-history"]').trigger("click");
  await flushPromises();
}

function historyItem(app: VueWrapper, id: number) {
  return app.get(`[data-testid="history-item-${id}"]`);
}

/** 人从抽屉那一侧关上它：这个入口关掉之后必须还能再打开（见用例「每次打开都从第一页重取」）。 */
async function closeDrawer(app: VueWrapper): Promise<void> {
  await app.get(".el-drawer__close-btn").trigger("click");
  await flushPromises();
}

/**
 * 提问框是多行输入（`el-input type="textarea"`，见 `MessageComposer.vue`）。
 * 「再问一次」把问题送回的就是它，形态再变一次时只需改这一行。
 */
function questionText(app: VueWrapper): string {
  return (app.get("textarea[name='question']").element as HTMLTextAreaElement).value;
}

/** 这次请求带的页码：抽屉底的翻页控件交给服务端的就是这个数。 */
function requestedPage(url: string): number {
  const query = new URLSearchParams(url.split("?")[1] ?? "");
  return Number(query.get("page") ?? 1);
}

/** 最后一次历史查询请求的页码：抽屉每次打开都从第一页重取，看的就是它。 */
function lastRequestedPage(): number {
  const urls = requestedUrls(fetchMock, "/api/internal/analytics/history");
  return requestedPage(urls[urls.length - 1] ?? "");
}

beforeEach(() => {
  localStorage.clear();
  // 线程（ticket 02 起）落在 sessionStorage 里：不清掉，上一用例问过的那一轮会跟着进下一条用例。
  sessionStorage.clear();
  clearTokens();
});

afterEach(() => {
  wrapper?.unmount();
  wrapper = null;
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  clearTokens();
});

describe("数据分析页的两栏形态", () => {
  it("这一页不再渲染第三栏，历史查询的入口改挂顶栏", async () => {
    const app = await mountAnalysis();

    // 不再注入检查器，壳据此自动塌成两栏——这一页的右栏没有别的东西要放。
    expect(app.classes()).not.toContain("app-shell--with-inspector");
    expect(app.find(".app-shell__inspector").exists()).toBe(false);

    // 入口在顶栏（壳转发出来的页面级操作），页面上没有常驻的历史查询。
    expect(app.find(".app-shell__topbar-end [data-testid='open-history']").exists()).toBe(true);
    expect(app.find('[data-testid="history-drawer"]').exists()).toBe(false);

    await openHistory(app);

    // 打开之后它仍然是两栏：抽屉不是第三栏。
    expect(app.find('[data-testid="history-drawer"]').exists()).toBe(true);
    expect(app.find(".app-shell__inspector").exists()).toBe(false);
  });
});

describe("历史查询抽屉", () => {
  it("一条记录里自带问题、状态、时间、返回行数、截断标记与错误码", async () => {
    const app = await mountAnalysis();
    await openHistory(app);

    const succeeded = historyItem(app, 7);
    expect(succeeded.text()).toContain("上个月各风险等级的客户分布");
    expect(succeeded.text()).toContain("成功");
    expect(succeeded.text()).toContain("2026-09-18");
    expect(succeeded.text()).toContain("返回 5 行");

    // 被拒绝的那一次没有行数可给：留痕里就是 null，不拿 0 冒充（0 行是一次成功的空结果）。
    const rejected = historyItem(app, 6);
    expect(rejected.text()).toContain("校验拒绝");
    expect(rejected.text()).toContain("返回行数 —");
    expect(rejected.text()).toContain("错误码 1103");

    // 截断是一次成功但只回了前 200 行的查询：标记跟着留痕的 truncated 走。
    const truncated = historyItem(app, 5);
    expect(truncated.text()).toContain("返回 200 行");
    expect(truncated.text()).toContain("已截断");
    // 没截断的那条不挂这个标记：它不是「可能不全」，它就是全量。
    expect(succeeded.text()).not.toContain("已截断");

    // 脚注从详情组件搬过来：留痕里没有结果集这件事，抽屉自己要说清楚。
    expect(app.get('[data-testid="history-note"]').text()).toContain("不保存结果集");
  });

  it("SQL 在行内折叠展开", async () => {
    const app = await mountAnalysis();
    await openHistory(app);

    // 默认折叠：一句话的凭证不该抢在问题与状态前面。
    expect(app.find('[data-testid="history-sql-7"]').exists()).toBe(false);

    await app.get('[data-testid="history-sql-toggle-7"]').trigger("click");
    expect(app.get('[data-testid="history-sql-7"]').text()).toContain("GROUP BY risk_level");

    await app.get('[data-testid="history-sql-toggle-7"]').trigger("click");
    expect(app.find('[data-testid="history-sql-7"]').exists()).toBe(false);
  });

  it("「再问一次」把问题送回输入框，不自动发送，并关上抽屉", async () => {
    const app = await mountAnalysis();
    await openHistory(app);

    await app.get('[data-testid="history-reuse-6"]').trigger("click");
    await flushPromises();

    expect(questionText(app)).toBe("查一下这个月的交易笔数");
    // 送回输入框不等于替人发问：这一下没有打出去任何查询。
    expect(requestedUrls(fetchMock, "/api/internal/analytics/query")).toHaveLength(0);
    // 抽屉关上，问题留在输入框里等人自己按发送。
    expect(app.get('[data-testid="history-drawer"]').isVisible()).toBe(false);
  });

  it("拉取失败时抽屉里说明原因，而不是给一份空历史", async () => {
    const app = await mountAnalysis({ history: apiError(500, "服务内部错误") });
    await openHistory(app);

    expect(app.get('[data-testid="history-error"]').text()).toContain("服务内部错误");
    expect(app.find('[data-testid="history-empty"]').exists()).toBe(false);
    expect(app.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("从没问过时说「还没有历史查询」，也不给分页条", async () => {
    const app = await mountAnalysis({ history: historyPage([], { total: 0 }) });
    await openHistory(app);

    expect(app.get('[data-testid="history-empty"]').text()).toContain("还没有历史查询");
    expect(app.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });

  it("把空页与「从没问过」分开", async () => {
    // 越界页：一条也拿不到，但总数说这个人问过 21 次——那是页码的事。
    const app = await mountAnalysis({ history: historyPage([], { total: 21, page: 99 }) });
    await openHistory(app);

    expect(app.get('[data-testid="history-page-empty"]').text()).toContain("前面几页");
    expect(app.find('[data-testid="history-empty"]').exists()).toBe(false);
    // 分页条仍在：人得靠它翻回去。
    expect(app.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });
});

describe("历史查询抽屉的分页", () => {
  it("展示过滤后的总数，翻页取的是服务端的下一页", async () => {
    const app = await mountAnalysis({
      historyResponder: (url) =>
        requestedPage(url) === 1
          ? historyPage([HISTORY_ITEMS[0]], { total: 21 })
          : historyPage([HISTORY_ITEMS[1]], { total: 21, page: 2 }),
    });
    await openHistory(app);

    expect(app.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
    expect(app.find('[data-testid="history-item-7"]').exists()).toBe(true);

    await app.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    // 第 2 页的内容来自服务端，而不是把已有的几条切一半。
    expect(app.find('[data-testid="history-item-6"]').exists()).toBe(true);
    expect(app.find('[data-testid="history-item-7"]').exists()).toBe(false);
    // 总数不随翻页变：它是过滤后的总数，不是本页条数。
    expect(app.get('[data-testid="pagination-total"]').text()).toBe("共 21 条");
  });

  it("每次打开抽屉都从第一页重取", async () => {
    const app = await mountAnalysis({
      historyResponder: (url) =>
        historyPage([HISTORY_ITEMS[0]], { total: 21, page: requestedPage(url) }),
    });
    await openHistory(app);
    await app.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(lastRequestedPage()).toBe(2);

    await closeDrawer(app);
    expect(app.get('[data-testid="history-drawer"]').isVisible()).toBe(false);
    await openHistory(app);
    expect(app.get('[data-testid="history-drawer"]').isVisible()).toBe(true);

    // 上次停在第 2 页不该带到这一次来（与客服的历史抽屉同口径）。
    expect(lastRequestedPage()).toBe(1);
  });
});
