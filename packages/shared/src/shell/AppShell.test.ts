// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { defineComponent, nextTick } from "vue";
import { describe, expect, it } from "vitest";
import AppShell from "./AppShell.vue";
import type { AppShellNavItem } from "./nav";

const StubIcon = defineComponent({
  name: "StubIcon",
  template: "<svg data-testid='stub-icon' />",
});

// shared 不依赖 element-plus：el-tooltip 在应用里由 app.use(ElementPlus) 全局注册，
// 这里用轻量 stub 透传默认插槽，并把 content / disabled 落到 data-* 供断言。
const ElTooltipStub = defineComponent({
  name: "ElTooltip",
  props: {
    content: { type: String, default: "" },
    disabled: { type: Boolean, default: false },
  },
  template:
    '<span class="el-tooltip-stub" :data-content="content" :data-disabled="String(disabled)"><slot /></span>',
});

const navItems: AppShellNavItem[] = [
  { key: "home", label: "首页", name: "nav-home", icon: StubIcon },
  { key: "settings", label: "设置" },
];

function mountShell(
  props: {
    activeKey?: string;
    brandSubtitle?: string;
    sidebarCollapsed?: boolean;
    inspectorCollapsed?: boolean;
  } = {},
  slots: Record<string, string> = {},
) {
  return mount(AppShell, {
    props: { navItems, ...props },
    slots: {
      brand: "<b>某系统</b>",
      "topbar-left": "<div data-testid='topbar-left-slot' />",
      "topbar-right": "<span data-testid='topbar-right-slot'>某人</span>",
      default: "<div data-testid='content-slot' />",
      ...slots,
    },
    global: { stubs: { ElTooltip: ElTooltipStub } },
  });
}

describe("AppShell", () => {
  it("renders one nav entry per item with its label and anchor name", () => {
    const wrapper = mountShell();

    const home = wrapper.find('button[name="nav-home"]');
    expect(home.exists()).toBe(true);
    expect(home.text()).toContain("首页");
    expect(wrapper.text()).toContain("设置");
  });

  it("renders the icon of a nav entry when provided", () => {
    const wrapper = mountShell();

    expect(wrapper.find('[data-testid="stub-icon"]').exists()).toBe(true);
  });

  it("marks only the active nav entry and emits select with its key on click", async () => {
    const wrapper = mountShell({ activeKey: "settings" });

    const entries = wrapper.findAll(".app-shell__nav-item");
    expect(entries[0].attributes("aria-current")).toBeUndefined();
    expect(entries[1].attributes("aria-current")).toBe("page");

    await entries[0].trigger("click");
    expect(wrapper.emitted("select")).toEqual([["home"]]);
  });

  it("renders the badge of a nav entry without interpreting it", () => {
    const wrapper = mount(AppShell, {
      props: {
        navItems: [{ key: "alerts", label: "风控", badge: 3 }, { key: "plain", label: "无徽标" }],
      },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    });

    const badges = wrapper.findAll(".app-shell__nav-badge");
    expect(badges).toHaveLength(1);
    expect(badges[0].text()).toBe("3");
  });

  it("always renders the logout entry and emits logout on click", async () => {
    const wrapper = mountShell();

    const logout = wrapper.find('button[name="logout"]');
    expect(logout.exists()).toBe(true);
    await logout.trigger("click");
    expect(wrapper.emitted("logout")).toHaveLength(1);
  });

  it("keeps the logout entry rendered for an empty navigation", () => {
    const wrapper = mount(AppShell, {
      props: { navItems: [] },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    });

    expect(wrapper.find('button[name="logout"]').exists()).toBe(true);
  });

  it("renders every named slot, including the optional sidebar footer", async () => {
    const wrapper = mountShell(
      { brandSubtitle: "Copilot" },
      { "sidebar-footer": "<div data-testid='sidebar-footer-slot' />" },
    );
    await nextTick();

    expect(wrapper.text()).toContain("某系统");
    expect(wrapper.text()).toContain("Copilot");
    expect(wrapper.find('[data-testid="topbar-left-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="topbar-right-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="content-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="sidebar-footer-slot"]').exists()).toBe(true);
  });

  it("omits the sidebar footer container when the slot is not provided", () => {
    const wrapper = mountShell();

    expect(wrapper.find(".app-shell__sidebar-footer").exists()).toBe(false);
  });

  it("stays two-column when no inspector slot is provided", () => {
    const wrapper = mountShell();

    expect(wrapper.classes()).not.toContain("app-shell--with-inspector");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(false);
  });

  it("takes the three-column shape from the inspector slot alone, with no variant prop", () => {
    const wrapper = mountShell({}, { inspector: "<div data-testid='inspector-slot' />" });

    expect(wrapper.classes()).toContain("app-shell--with-inspector");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(true);
    expect(wrapper.find('[data-testid="inspector-slot"]').exists()).toBe(true);
  });
});

describe("AppShell 折叠", () => {
  it("hangs the sidebar-collapsed class and shows the brand initial square instead of full text", async () => {
    const wrapper = mountShell({ sidebarCollapsed: true, brandSubtitle: "Copilot" });
    await nextTick();

    expect(wrapper.classes()).toContain("app-shell--sidebar-collapsed");
    // 品牌首字符方块：'某系统' 的首字符 '某'，subtitle 隐藏
    expect(wrapper.find(".app-shell__brand-initial").text()).toBe("某");
    expect(wrapper.find(".app-shell__brand-subtitle").exists()).toBe(false);
  });

  it("hides nav labels, shows only icons, and feeds the label to the hover tooltip", async () => {
    const wrapper = mountShell({ sidebarCollapsed: true });
    await nextTick();

    // label 隐藏：只剩图标
    expect(wrapper.find(".app-shell__nav-label").exists()).toBe(false);
    expect(wrapper.find('[data-testid="stub-icon"]').exists()).toBe(true);

    // hover 图标出 tooltip：content 是 label，且未禁用
    const tooltip = wrapper.find(".el-tooltip-stub");
    expect(tooltip.attributes("data-content")).toBe("首页");
    expect(tooltip.attributes("data-disabled")).toBe("false");
  });

  it("turns the nav badge into a corner dot when collapsed", async () => {
    const wrapper = mount(AppShell, {
      props: {
        navItems: [{ key: "alerts", label: "风控", badge: 3, icon: StubIcon }],
        sidebarCollapsed: true,
      },
      global: { stubs: { ElTooltip: ElTooltipStub } },
    });
    await nextTick();

    // 数字徽标不再渲染，换成图标右上角小圆点
    expect(wrapper.find(".app-shell__nav-badge").exists()).toBe(false);
    expect(wrapper.find(".app-shell__nav-badge-dot").exists()).toBe(true);
  });

  it("emits update:sidebarCollapsed from the trigger bar with aria-expanded", async () => {
    const wrapper = mountShell();

    const toggle = wrapper.find(".app-shell__collapse-toggle");
    expect(toggle.attributes("aria-expanded")).toBe("true");
    expect(toggle.attributes("aria-label")).toBe("折叠侧栏");

    await toggle.trigger("click");
    expect(wrapper.emitted("update:sidebarCollapsed")).toEqual([[true]]);
  });

  it("reflects the collapsed state in aria-expanded and emits false when re-expanding", async () => {
    const wrapper = mountShell({ sidebarCollapsed: true });
    await nextTick();

    const toggle = wrapper.find(".app-shell__collapse-toggle");
    expect(toggle.attributes("aria-expanded")).toBe("false");
    expect(toggle.attributes("aria-label")).toBe("展开侧栏");

    await toggle.trigger("click");
    expect(wrapper.emitted("update:sidebarCollapsed")).toEqual([[false]]);
  });

  it("keeps the sidebar footer rendered when collapsed", async () => {
    const wrapper = mountShell(
      { sidebarCollapsed: true },
      { "sidebar-footer": "<div data-testid='sidebar-footer-slot' />" },
    );
    await nextTick();

    expect(wrapper.find(".app-shell__sidebar-footer").exists()).toBe(true);
    expect(wrapper.find('[data-testid="sidebar-footer-slot"]').exists()).toBe(true);
  });
});

describe("AppShell 检查器折叠", () => {
  it("drops the third column even when the inspector slot exists", async () => {
    const wrapper = mountShell(
      { inspectorCollapsed: true },
      { inspector: "<div data-testid='inspector-slot' />" },
    );
    await nextTick();

    expect(wrapper.classes()).toContain("app-shell--inspector-collapsed");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(false);
    expect(wrapper.find('[data-testid="inspector-slot"]').exists()).toBe(false);
  });

  it("does not render the inspector collapsed class unless the prop is set", () => {
    const wrapper = mountShell({}, { inspector: "<div data-testid='inspector-slot' />" });

    expect(wrapper.classes()).not.toContain("app-shell--inspector-collapsed");
    expect(wrapper.find(".app-shell__inspector").exists()).toBe(true);
  });
});
