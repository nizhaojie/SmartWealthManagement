// 规则管理页签：列表分页 + 规则编辑器。
//
// 分页那几条要盯的是分页与写操作的配合：启停失败后重取的是**当前这一页**（回到第 1 页
// 会让人以为规则变少了），以及总数说的是全部规则而不是本页条数。
//
// 编辑器那几条盯的是「前端禁掉的选项与后端拒掉的组合不会漂移」的前端一侧：算子的可选项
// 随字段收敛、阈值输入随算子变形、窗长只对时间窗算子出现、判定形状在编辑态只读（阈值
// 可在编辑对话框里改，保存时阈值有变化就单独走调阈值接口）。选项全部来自 `GET /schema`，
// 所以夹具就是那份载荷的形状。
//
// 「理由」走 `ElMessageBox.prompt`：真实浮层在 jsdom 里只有时序、没有行为，这里换成替身，
// 钉住的是我们交出去的那份契约（`inputValidator` 拒绝空理由、取消不写数据）。
import ElementPlus, { ElMessage } from "element-plus";
import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, type PageQuery } from "@wealth/shared";
import { ADVISOR, RISK_OFFICER } from "../auth/identity";
import { useAuthStore } from "../stores/auth";
import type { RiskRule, RiskRuleSchema } from "./types";

const {
  listRiskRules,
  setRiskRuleEnabled,
  setRiskRuleThreshold,
  getRiskRuleSchema,
  createRiskRule,
  updateRiskRule,
  deleteRiskRule,
  listRiskRuleChanges,
} = vi.hoisted(() => ({
  listRiskRules: vi.fn(),
  setRiskRuleEnabled: vi.fn(),
  setRiskRuleThreshold: vi.fn(),
  getRiskRuleSchema: vi.fn(),
  createRiskRule: vi.fn(),
  updateRiskRule: vi.fn(),
  deleteRiskRule: vi.fn(),
  listRiskRuleChanges: vi.fn(),
}));

const prompt = vi.hoisted(() => vi.fn());

vi.mock("./api", () => ({
  listRiskRules,
  setRiskRuleEnabled,
  setRiskRuleThreshold,
  getRiskRuleSchema,
  createRiskRule,
  updateRiskRule,
  deleteRiskRule,
  listRiskRuleChanges,
}));

vi.mock("element-plus", async (importOriginal) => {
  const actual = await importOriginal<typeof import("element-plus")>();
  return { ...actual, ElMessageBox: { ...actual.ElMessageBox, prompt } };
});

import RiskRulesTab from "./RiskRulesTab.vue";

const PAGE_SIZE = 10;
const TOTAL = 25;

// 后端 `GET /schema` 的形状：字段带着它允许的算子与阈值值域，算子带着自己的阈值键与作用域。
const SCHEMA: RiskRuleSchema = {
  categories: ["大额交易", "频繁交易", "快进快出", "拆分规避", "异常时段", "资产错配", "适当性"],
  fields: [
    {
      key: "amount",
      label: "交易金额",
      description: "本笔交易的成交金额",
      allowed_operators: ["gte", "between", "window_count_gte"],
      value_range: { min: "0", max: null, min_inclusive: false, max_inclusive: true, text: "> 0" },
    },
    {
      key: "product_id",
      label: "产品标识",
      description: "交易对应的产品标识",
      allowed_operators: ["window_distinct_count_gte"],
      value_range: null,
    },
  ],
  operators: [
    { key: "gte", label: "大于等于", symbol: "≥", scope: "single", threshold_keys: ["value"] },
    { key: "between", label: "落在区间内", symbol: "∈", scope: "single", threshold_keys: ["min", "max"] },
    {
      key: "window_count_gte",
      label: "时间窗内计数",
      symbol: "≥",
      scope: "window",
      threshold_keys: ["value"],
    },
    {
      key: "window_distinct_count_gte",
      label: "时间窗内去重计数",
      symbol: "≥",
      scope: "window",
      threshold_keys: ["value"],
    },
  ],
};

function makeRule(overrides: Partial<RiskRule> = {}): RiskRule {
  return {
    id: 1,
    rule_code: "R001",
    rule_name: "单笔大额交易",
    category: "大额交易",
    description: "单笔交易金额达到阈值",
    field: "amount",
    field_label: "交易金额",
    operator: "gte",
    operator_label: "大于等于",
    threshold: { value: "50000" },
    threshold_text: "50000",
    window_hours: null,
    alert_level: "轻度",
    weight: 1,
    enabled: true,
    deleted_at: null,
    ...overrides,
  };
}

function makePage(
  items: RiskRule[],
  total: number,
  query: PageQuery = { page: 1, page_size: PAGE_SIZE },
) {
  return { items, total, page: query.page, page_size: query.page_size };
}

let activeWrapper: VueWrapper | null = null;

const successSpy = vi.spyOn(ElMessage, "success").mockReturnValue(undefined as never);

async function mountTab(role: string = RISK_OFFICER): Promise<VueWrapper> {
  const pinia = createPinia();
  setActivePinia(pinia);
  useAuthStore().currentEmployee = { real_name: "周风控", employee_role: role as never };

  activeWrapper = mount(RiskRulesTab, { global: { plugins: [ElementPlus, pinia] } });
  await flushPromises();
  return activeWrapper;
}

/** 每一次取数请求的两个参数：分页，以及状态 / 判定字段。 */
function listCalls(): [PageQuery, { status?: string; field?: string }][] {
  return listRiskRules.mock.calls as [PageQuery, { status?: string; field?: string }][];
}

function lastQuery(): PageQuery {
  return listCalls().at(-1)![0];
}

/** 某个 el-select 自己那几个选项目前的取值（下拉是 teleport 到 body 的，只能走组件树）。 */
function optionValues(wrapper: VueWrapper, testid: string): string[] {
  return wrapper
    .findComponent(`[data-testid="${testid}"]`)
    .findAllComponents({ name: "ElOption" })
    .map((option) => String(option.props("value")));
}

/** 点开一个 el-select 的下拉：选项在浮层里，浮层不展开时组件树上还没有 el-option。 */
async function openOptions(wrapper: VueWrapper, testid: string): Promise<void> {
  await wrapper.get(`[data-testid="${testid}"] .el-select__wrapper`).trigger("click");
  await flushPromises();
}

/** 选一个取值：el-select 的 v-model 走 `update:modelValue`，直接发给组件即可。 */
async function chooseSelect(wrapper: VueWrapper, testid: string, value: string): Promise<void> {
  await wrapper.findComponent(`[data-testid="${testid}"]`).setValue(value);
  // 换字段之后算子的收敛由 watcher 完成，等它跑完。
  await flushPromises();
}

/** 往 el-input 里写字：`data-testid` 透到了真正的输入框上（外壳上再兜一层）。 */
async function typeInto(wrapper: VueWrapper, testid: string, value: string): Promise<void> {
  const control = wrapper.get(`[data-testid="${testid}"]`);
  const target = control.element.matches("input, textarea") ? control : control.get("input, textarea");
  await target.setValue(value);
  await flushPromises();
}

/** 阈值输入框的键名（`gte` 一个、`between` 两个）。 */
function thresholdInputKeys(wrapper: VueWrapper): string[] {
  return wrapper
    .findAll('[data-testid^="editor-threshold-"]')
    .map((input) => String(input.attributes("data-testid")).replace("editor-threshold-", ""));
}

/** 一个控件要读的那几样：`get` 交出来的是没有 `exists` 的那一份包装，用结构类型收得住。 */
type ControlWrapper = Pick<DOMWrapper<Element>, "attributes" | "classes" | "find">;

/**
 * 一个控件是不是禁用（传进来的就是 `data-testid` 所在的那一层）。
 *
 * 三条路都读一遍，是因为 `data-testid` 的落点跟着组件走：el-input 把它透到原生输入框上
 * （禁用就是那个属性），el-select 留在根元素上、禁用在它内层 wrapper 的类上。
 */
function isDisabled(control: ControlWrapper): boolean {
  return (
    control.attributes("disabled") !== undefined ||
    control.classes().includes("is-disabled") ||
    control.find(".is-disabled").exists()
  );
}

/**
 * 规则表正文的每一行。
 *
 * 每一列都在 `el-table` 的隐藏区里另渲染一份模板（供它算列宽），全局找 `data-testid`
 * 会先撞上那个副本、而副本里的 `row` 是个空对象——点它等于点了个空行。行内查找才落在
 * 真正的数据行上。
 */
function bodyRows(wrapper: VueWrapper): DOMWrapper<Element>[] {
  return wrapper.findAll(".el-table__body tr");
}

/** 第 `index` 行里那个控件；行里没有就当场说清楚，别让断言去猜。 */
function rowControl(wrapper: VueWrapper, index: number, testid: string): DOMWrapper<Element> {
  const control = bodyRows(wrapper)[index]?.find(`[data-testid="${testid}"]`);
  if (!control || !control.exists()) {
    throw new Error(`第 ${index + 1} 行没有 ${testid}`);
  }
  return control;
}

function rowHas(wrapper: VueWrapper, index: number, testid: string): boolean {
  return bodyRows(wrapper)[index]?.find(`[data-testid="${testid}"]`).exists() ?? false;
}

async function openCreate(wrapper: VueWrapper): Promise<void> {
  await wrapper.get('[data-testid="create-rule"]').trigger("click");
  await flushPromises();
}

/** 新建表单填到「只差理由」：分类 → 字段 → 算子 → 阈值 → 等级。 */
async function fillCreateForm(wrapper: VueWrapper): Promise<void> {
  await typeInto(wrapper, "editor-name", "本地大额转账");
  await chooseSelect(wrapper, "editor-category", "大额交易");
  await chooseSelect(wrapper, "editor-field", "amount");
  await chooseSelect(wrapper, "editor-operator", "gte");
  await typeInto(wrapper, "editor-threshold-value", "300000");
  await chooseSelect(wrapper, "editor-alert-level", "中度");
}

describe("RiskRulesTab 的分页", () => {
  beforeEach(() => {
    listRiskRules.mockReset();
    setRiskRuleEnabled.mockReset();
    prompt.mockReset();
    successSpy.mockClear();
    getRiskRuleSchema.mockReset();
    getRiskRuleSchema.mockResolvedValue(SCHEMA);
    listRiskRules.mockResolvedValue(makePage([], 0));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("asks for the first page and shows how many rules there are in total", async () => {
    listRiskRules.mockResolvedValue(makePage([makeRule()], TOTAL));
    const wrapper = await mountTab();

    // 默认是「全部」且不限判定字段：两个筛选都不传，由服务端按未删除的规则返回。
    expect(listRiskRules).toHaveBeenCalledWith({ page: 1, page_size: PAGE_SIZE }, {});
    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 25 条");
  });

  it("turns the page and shows the rules of the page it landed on", async () => {
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(
        makePage(
          [makeRule({ rule_code: query.page === 1 ? "R001" : "R021" })],
          TOTAL,
          query,
        ),
      ),
    );
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R001");

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(lastQuery().page).toBe(2);
    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R021");
    expect(wrapper.get('[data-testid="rules-table"]').text()).not.toContain("R001");
  });

  it("re-reads the page it is on when toggling a rule fails", async () => {
    // 失败后回到第 1 页，人看到的会是另一批规则——像是规则变少了，而不是这次没改成。
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(makePage([makeRule()], TOTAL, query)),
    );
    setRiskRuleEnabled.mockRejectedValue(
      new ApiError({ code: 500, message: "服务内部错误", data: null, trace_id: "t-1" }),
    );
    prompt.mockResolvedValue({ value: "演示需要" });
    const wrapper = await mountTab();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    await rowControl(wrapper, 0, "rule-enabled").trigger("click");
    await flushPromises();

    expect(setRiskRuleEnabled).toHaveBeenCalledWith(1, false, "演示需要");
    expect(lastQuery().page).toBe(2);
    // 失败原因要留在页面上：随后的重取若把它清掉，人就只看到一个退回去的开关。
    expect(wrapper.get('[data-testid="rule-error"]').text()).toContain("服务内部错误");
  });

  it("keeps an explanation and the pager on a page that turned out to be empty", async () => {
    listRiskRules.mockImplementation((query: PageQuery) =>
      Promise.resolve(makePage(query.page === 1 ? [makeRule()] : [], TOTAL, query)),
    );
    const wrapper = await mountTab();

    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();

    expect(wrapper.find('[data-testid="rules-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(true);
  });

  it("筛选已启用与判定字段后，摘要只报筛后的总数", async () => {
    listRiskRules.mockImplementation((query: PageQuery, filters: { status?: string; field?: string } = {}) =>
      Promise.resolve(
        makePage(
          filters.status === "已启用" && filters.field === "amount" ? [makeRule()] : [makeRule(), makeRule({ id: 2, rule_code: "R002" })],
          filters.status === "已启用" && filters.field === "amount" ? 12 : TOTAL,
          query,
        ),
      ),
    );
    const wrapper = await mountTab();

    await chooseSelect(wrapper, "rule-status-filter", "已启用");
    await chooseSelect(wrapper, "rule-field-filter", "amount");

    expect(listCalls().at(-1)).toEqual([
      { page: 1, page_size: PAGE_SIZE },
      { status: "已启用", field: "amount" },
    ]);
    const summaries = wrapper.emitted("summary");
    expect(summaries!.at(-1)![0]).toMatchObject({
      headline: "共 12 条已启用规则 · 判定字段：交易金额",
      count: 12,
    });
  });

  it("有筛选但没有命中时说明是筛选为空", async () => {
    listRiskRules.mockResolvedValue(makePage([], 0));
    const wrapper = await mountTab();

    expect(wrapper.get(".rules__empty").text()).toBe("还没有风控规则。");

    await chooseSelect(wrapper, "rule-status-filter", "已停用");

    expect(wrapper.get(".rules__empty").text()).toBe("没有符合筛选的规则。");
  });

  it("停用后不再符合「已启用」时这一行消失，空页退回上一页", async () => {
    let stopped = false;
    listRiskRules.mockImplementation((query: PageQuery, filters: { status?: string } = {}) => {
      if (filters.status === "已启用" && stopped && query.page > 1) {
        return Promise.resolve(makePage([], 1, query));
      }
      if (query.page === 1) {
        return Promise.resolve(makePage([makeRule({ rule_code: "R001" })], stopped ? 1 : 11, query));
      }
      return Promise.resolve(makePage([makeRule({ id: 11, rule_code: "R011" })], 11, query));
    });
    setRiskRuleEnabled.mockImplementation(async () => {
      stopped = true;
      return makeRule({ id: 11, rule_code: "R011", enabled: false });
    });
    prompt.mockResolvedValue({ value: "先停掉" });
    const wrapper = await mountTab();

    await chooseSelect(wrapper, "rule-status-filter", "已启用");
    await wrapper.get(".pagination-bar .btn-next").trigger("click");
    await flushPromises();
    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R011");

    await rowControl(wrapper, 0, "rule-enabled").trigger("click");
    await flushPromises();

    expect(lastQuery().page).toBe(1);
    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("R001");
    expect(wrapper.get('[data-testid="rules-table"]').text()).not.toContain("R011");
  });

  it("leaves the reason on screen when the load fails", async () => {
    listRiskRules.mockRejectedValue(new Error("boom"));
    const wrapper = await mountTab();

    expect(wrapper.get('[data-testid="rule-error"]').text()).toContain("规则列表加载失败");
    expect(wrapper.find('[data-testid="rules-table"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="pagination-bar"]').exists()).toBe(false);
  });
});

describe("规则编辑器", () => {
  beforeEach(() => {
    listRiskRules.mockReset();
    setRiskRuleEnabled.mockReset();
    setRiskRuleThreshold.mockReset();
    createRiskRule.mockReset();
    updateRiskRule.mockReset();
    successSpy.mockClear();
    prompt.mockReset();
    getRiskRuleSchema.mockReset();
    getRiskRuleSchema.mockResolvedValue(SCHEMA);
    listRiskRules.mockResolvedValue(makePage([makeRule()], 1));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("选完字段后算子下拉只剩该字段允许的那几个", async () => {
    const wrapper = await mountTab();
    await openCreate(wrapper);

    await chooseSelect(wrapper, "editor-field", "amount");
    await openOptions(wrapper, "editor-operator");
    expect(optionValues(wrapper, "editor-operator")).toEqual(["gte", "between", "window_count_gte"]);

    // 标识类字段只配得上「去重计数」：拿产品标识比大小、求和都没有含义。
    await chooseSelect(wrapper, "editor-field", "product_id");
    await openOptions(wrapper, "editor-operator");
    expect(optionValues(wrapper, "editor-operator")).toEqual(["window_distinct_count_gte"]);
  });

  it("阈值输入框的数量与键名随算子变形（gte 一个、between 两个）", async () => {
    const wrapper = await mountTab();
    await openCreate(wrapper);
    await chooseSelect(wrapper, "editor-field", "amount");

    await chooseSelect(wrapper, "editor-operator", "gte");
    expect(thresholdInputKeys(wrapper)).toEqual(["value"]);

    await chooseSelect(wrapper, "editor-operator", "between");
    expect(thresholdInputKeys(wrapper)).toEqual(["min", "max"]);
  });

  it("窗长只在时间窗算子出现", async () => {
    const wrapper = await mountTab();
    await openCreate(wrapper);
    await chooseSelect(wrapper, "editor-field", "amount");

    await chooseSelect(wrapper, "editor-operator", "gte");
    expect(wrapper.find('[data-testid="editor-window"]').exists()).toBe(false);

    await chooseSelect(wrapper, "editor-operator", "window_count_gte");
    expect(wrapper.find('[data-testid="editor-window"]').exists()).toBe(true);
  });

  it("编辑态的判定形状只读、阈值可改，基本信息仍可改", async () => {
    listRiskRules.mockResolvedValue(
      makePage([makeRule({ operator: "window_count_gte", operator_label: "时间窗内计数", window_hours: 24 })], 1),
    );
    const wrapper = await mountTab();

    await rowControl(wrapper, 0, "edit-rule").trigger("click");
    await flushPromises();

    // 编号与判定形状（字段 / 算子 / 窗长）只读：改形状等于换一条规则；阈值可直接改。
    expect(isDisabled(wrapper.get('[data-testid="editor-code"]'))).toBe(true);
    expect(isDisabled(wrapper.get('[data-testid="editor-field"]'))).toBe(true);
    expect(isDisabled(wrapper.get('[data-testid="editor-operator"]'))).toBe(true);
    expect(isDisabled(wrapper.get('[data-testid="editor-window"]'))).toBe(true);
    expect(isDisabled(wrapper.get('[data-testid="editor-threshold-value"]'))).toBe(false);
    expect(wrapper.get('[data-testid="shape-note"]').text()).toContain(
      "要改判定形状请删除后重建，阈值可在上方直接调整",
    );

    // 可改的那几项要留着：编辑器只锁判定形状，不锁名称、规则分类、描述、预警等级与规则权重。
    expect(isDisabled(wrapper.get('[data-testid="editor-name"]'))).toBe(false);
    expect(isDisabled(wrapper.get('[data-testid="editor-category"]'))).toBe(false);
    expect(isDisabled(wrapper.get('[data-testid="editor-description"]'))).toBe(false);
    expect(isDisabled(wrapper.get('[data-testid="editor-alert-level"]'))).toBe(false);
    expect(isDisabled(wrapper.get('[data-testid="editor-weight"]'))).toBe(false);
  });

  it("创建理由为空就不提交，写了才带着它发出去", async () => {
    const wrapper = await mountTab();
    await chooseSelect(wrapper, "rule-status-filter", "已停用");
    await openCreate(wrapper);
    await fillCreateForm(wrapper);

    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="editor-error"]').text()).toBe("创建理由不能为空");
    expect(createRiskRule).not.toHaveBeenCalled();

    await typeInto(wrapper, "editor-reason", "本地口径：单笔转账 30 万");
    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(createRiskRule).toHaveBeenCalledWith({
      rule_name: "本地大额转账",
      category: "大额交易",
      description: "",
      field: "amount",
      operator: "gte",
      threshold: { value: "300000" },
      window_hours: null,
      alert_level: "中度",
      // 规则权重是数字（新建时默认 1.00），空值表示「用默认的」。
      weight: 1,
      enabled: true,
      reason: "本地口径：单笔转账 30 万",
    });
    // 「不回算」是这条 slice 认下的代价：新建完预警列表里什么都不会发生，提示必须说清楚。
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining("从下一笔交易起生效"));
    expect(successSpy).toHaveBeenCalledWith(expect.stringContaining("历史交易不会被重新判定"));
    // 新建默认已启用，当前停在「已停用」时筛选不动，人自己改筛选去找。
    expect(listCalls().at(-1)?.[1]).toEqual({ status: "已停用" });
  });

  it("时间窗算子没填窗长就不提交，填了才带着它发出去", async () => {
    const wrapper = await mountTab();
    await openCreate(wrapper);
    await typeInto(wrapper, "editor-name", "窗内密集成交");
    await chooseSelect(wrapper, "editor-category", "频繁交易");
    await chooseSelect(wrapper, "editor-field", "amount");
    await chooseSelect(wrapper, "editor-operator", "window_count_gte");
    await typeInto(wrapper, "editor-threshold-value", "10");
    await chooseSelect(wrapper, "editor-alert-level", "中度");
    await typeInto(wrapper, "editor-reason", "本地口径");

    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="editor-error"]').text()).toBe("时间窗必须是正整数小时");
    expect(createRiskRule).not.toHaveBeenCalled();

    await typeInto(wrapper, "editor-window", "24");
    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(createRiskRule).toHaveBeenCalledWith(
      expect.objectContaining({ window_hours: 24, threshold: { value: "10" } }),
    );
  });

  it("编辑保存走基本信息入口，判定形状一个字段都不带", async () => {
    updateRiskRule.mockResolvedValue(makeRule({ rule_name: "改过的名字" }));
    const wrapper = await mountTab();

    await rowControl(wrapper, 0, "edit-rule").trigger("click");
    await flushPromises();
    await typeInto(wrapper, "editor-name", "改过的名字");
    await typeInto(wrapper, "editor-reason", "口径表述跟不上业务了");

    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(updateRiskRule).toHaveBeenCalledWith(1, {
      rule_name: "改过的名字",
      category: "大额交易",
      description: "单笔交易金额达到阈值",
      alert_level: "轻度",
      weight: 1,
      reason: "口径表述跟不上业务了",
    });
    // 阈值没动就不多发一次调阈值请求。
    expect(setRiskRuleThreshold).not.toHaveBeenCalled();
  });

  it("编辑对话框里改阈值，保存时带着同一条理由单独走调阈值接口", async () => {
    setRiskRuleThreshold.mockResolvedValue(
      makeRule({ threshold: { value: "80000" }, threshold_text: "80000" }),
    );
    const wrapper = await mountTab();

    await rowControl(wrapper, 0, "edit-rule").trigger("click");
    await flushPromises();
    await typeInto(wrapper, "editor-threshold-value", "80000");
    await typeInto(wrapper, "editor-reason", "监管口径调整");

    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    // 只动了阈值就不发 update：后端 update 即使内容没变也会留一条变更记录。
    expect(updateRiskRule).not.toHaveBeenCalled();
    expect(setRiskRuleThreshold).toHaveBeenCalledWith(1, { value: "80000" }, "监管口径调整");
    // 行上换成了调阈值接口返回的那份规则（带新阈值）。
    expect(wrapper.get('[data-testid="rules-table"]').text()).toContain("80000");
  });

  it("什么都没改就保存，不发任何请求并就地说明", async () => {
    const wrapper = await mountTab();

    await rowControl(wrapper, 0, "edit-rule").trigger("click");
    await flushPromises();
    await typeInto(wrapper, "editor-reason", "手滑点了保存");

    await wrapper.get('[data-testid="save-rule"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="editor-error"]').text()).toBe("没有要修改的内容");
    expect(updateRiskRule).not.toHaveBeenCalled();
    expect(setRiskRuleThreshold).not.toHaveBeenCalled();
  });
});

describe("理由与已删除", () => {
  beforeEach(() => {
    listRiskRules.mockReset();
    setRiskRuleEnabled.mockReset();
    setRiskRuleThreshold.mockReset();
    deleteRiskRule.mockReset();
    listRiskRuleChanges.mockReset();
    listRiskRuleChanges.mockResolvedValue([]);
    successSpy.mockClear();
    prompt.mockReset();
    getRiskRuleSchema.mockReset();
    getRiskRuleSchema.mockResolvedValue(SCHEMA);
    listRiskRules.mockResolvedValue(makePage([makeRule()], 1));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("删除要先写理由：理由为空就不提交，写了才带着它发出去", async () => {
    const wrapper = await mountTab();

    prompt.mockResolvedValueOnce({ value: "   " });
    // 理由为空时什么都不做：`ElMessageBox` 拿返回的那句话就地提示、弹框不关。
    await rowControl(wrapper, 0, "delete-rule").trigger("click");
    await flushPromises();
    expect(deleteRiskRule).not.toHaveBeenCalled();

    prompt.mockResolvedValueOnce({ value: "口径已废止" });
    await rowControl(wrapper, 0, "delete-rule").trigger("click");
    await flushPromises();
    expect(deleteRiskRule).toHaveBeenCalledWith(1, "口径已废止");
  });

  it("删除的校验器就地拒绝空理由、放行非空理由", async () => {
    const wrapper = await mountTab();

    prompt.mockRejectedValueOnce(new Error("cancel"));
    await rowControl(wrapper, 0, "delete-rule").trigger("click");
    await flushPromises();

    // 取消不是失败：不发请求，也不留错误文案。
    expect(deleteRiskRule).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="rule-error"]').exists()).toBe(false);

    const options = prompt.mock.calls[0]?.[2] as { inputValidator: (value: string) => unknown };
    expect(options.inputValidator("")).toBe("理由不能为空");
    expect(options.inputValidator("  ")).toBe("理由不能为空");
    expect(options.inputValidator("口径已废止")).toBe(true);
  });

  it("开关点一下先要一条理由，取消则开关不动", async () => {
    setRiskRuleEnabled.mockResolvedValue(makeRule({ enabled: false }));
    const wrapper = await mountTab();

    prompt.mockRejectedValueOnce(new Error("cancel"));
    await rowControl(wrapper, 0, "rule-enabled").trigger("click");
    await flushPromises();
    expect(setRiskRuleEnabled).not.toHaveBeenCalled();

    prompt.mockResolvedValueOnce({ value: "演示需要" });
    await rowControl(wrapper, 0, "rule-enabled").trigger("click");
    await flushPromises();
    expect(setRiskRuleEnabled).toHaveBeenCalledWith(1, false, "演示需要");
  });

  it("状态选「已删除」是服务端参数：重取后已删行只留变更记录", async () => {
    listRiskRules.mockImplementation((query: PageQuery, filters: { status?: string } = {}) =>
      Promise.resolve(
        makePage(
          filters.status === "已删除"
            ? [makeRule({ id: 2, rule_code: "R002", rule_name: "已删规则", deleted_at: "2026-09-24T10:00:00" })]
            : [makeRule()],
          1,
          query,
        ),
      ),
    );
    const wrapper = await mountTab();
    expect(bodyRows(wrapper)).toHaveLength(1);
    expect(wrapper.find("tr.rules__row--deleted").exists()).toBe(false);

    await chooseSelect(wrapper, "rule-status-filter", "已删除");

    expect(listCalls().at(-1)).toEqual([{ page: 1, page_size: PAGE_SIZE }, { status: "已删除" }]);
    // 已删除的行置灰只读：编辑 / 调阈值 / 启停都不出现，只留一个能打开的变更记录。
    expect(bodyRows(wrapper)).toHaveLength(1);
    expect(bodyRows(wrapper)[0]!.classes()).toContain("rules__row--deleted");
    expect(bodyRows(wrapper)[0]!.text()).toContain("已删除");
    expect(rowHas(wrapper, 0, "edit-rule")).toBe(false);
    expect(rowHas(wrapper, 0, "delete-rule")).toBe(false);
    expect(rowHas(wrapper, 0, "rule-enabled")).toBe(false);
    expect(rowHas(wrapper, 0, "view-changes")).toBe(true);

    // 已删行也要能打开变更记录（删除这件事本身也可查）。
    await rowControl(wrapper, 0, "view-changes").trigger("click");
    await flushPromises();
    expect(listRiskRuleChanges).toHaveBeenCalledWith(2);
  });

  it("变更记录对话框渲染出 old_value → new_value", async () => {
    listRiskRuleChanges.mockResolvedValue([
      {
        id: 7,
        rule_code: "R001",
        change_type: "阈值调整",
        old_value: { threshold: { value: "50000" } },
        new_value: { threshold: { value: "80000" } },
        changed_by: 9,
        changed_by_name: "周风控",
        reason: "监管口径调整",
        changed_at: "2026-09-24T10:00:00",
      },
    ]);
    const wrapper = await mountTab();

    await rowControl(wrapper, 0, "view-changes").trigger("click");
    await flushPromises();

    expect(listRiskRuleChanges).toHaveBeenCalledWith(1);
    const diff = wrapper.get('[data-testid="change-diff"]').text();
    expect(diff).toContain("50000");
    expect(diff).toContain("→");
    expect(diff).toContain("80000");
    expect(wrapper.get('[data-testid="rule-changes"]').text()).toContain("监管口径调整");
  });
});

describe("非风控专员", () => {
  beforeEach(() => {
    listRiskRules.mockReset();
    prompt.mockReset();
    getRiskRuleSchema.mockReset();
    getRiskRuleSchema.mockResolvedValue(SCHEMA);
    listRiskRules.mockResolvedValue(makePage([makeRule()], 1));
  });

  afterEach(() => {
    activeWrapper?.unmount();
    activeWrapper = null;
  });

  it("看不到任何写入口，也不会去取编辑器的选项", async () => {
    const wrapper = await mountTab(ADVISOR);

    expect(wrapper.get('[data-testid="create-rule"]').attributes("disabled")).toBeDefined();
    expect(rowHas(wrapper, 0, "edit-rule")).toBe(false);
    expect(rowHas(wrapper, 0, "delete-rule")).toBe(false);
    expect(rowHas(wrapper, 0, "view-changes")).toBe(true);
    expect(isDisabled(rowControl(wrapper, 0, "rule-enabled"))).toBe(true);
    // 只读提示沿用既有的那句话。
    expect(wrapper.get('[data-testid="rule-read-only"]').text()).toBe(
      "当前角色只能查看规则；启停与阈值调整由风控专员完成。",
    );
    // 判定字段的选项来自字段名录，只读角色也要筛，所以照样取。
    expect(getRiskRuleSchema).toHaveBeenCalled();
  });
});
