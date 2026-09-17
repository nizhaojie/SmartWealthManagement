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

const navItems: AppShellNavItem[] = [
  { key: "home", label: "首页", name: "nav-home", icon: StubIcon },
  { key: "settings", label: "设置" },
];

function mountShell(props: { activeKey?: string } = {}) {
  return mount(AppShell, {
    props: { navItems, ...props },
    slots: {
      brand: "测试品牌",
      topbar: "<div data-testid='topbar-slot' />",
      user: "<span data-testid='user-slot'>某人</span>",
      default: "<div data-testid='content-slot' />",
    },
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

  it("always renders the logout entry and emits logout on click", async () => {
    const wrapper = mountShell();

    const logout = wrapper.find('button[name="logout"]');
    expect(logout.exists()).toBe(true);
    await logout.trigger("click");
    expect(wrapper.emitted("logout")).toHaveLength(1);
  });

  it("keeps the logout entry rendered for an empty navigation", () => {
    const wrapper = mount(AppShell, { props: { navItems: [] } });

    expect(wrapper.find('button[name="logout"]').exists()).toBe(true);
  });

  it("renders brand, topbar, user and default slots", async () => {
    const wrapper = mountShell();
    await nextTick();

    expect(wrapper.text()).toContain("测试品牌");
    expect(wrapper.find('[data-testid="topbar-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="user-slot"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="content-slot"]').exists()).toBe(true);
  });
});
