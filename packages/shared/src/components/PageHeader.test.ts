// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import PageHeader from "./PageHeader.vue";

describe("PageHeader", () => {
  it("renders the page title", () => {
    const wrapper = mount(PageHeader, { props: { title: "页面标题" } });

    expect(wrapper.find('[data-testid="page-header"]').exists()).toBe(true);
    expect(wrapper.get("h1").text()).toBe("页面标题");
  });

  it("renders the breadcrumb in order and marks the last segment as current", () => {
    const wrapper = mount(PageHeader, {
      props: { title: "页面标题", breadcrumb: ["当前模块", "当前页面"] },
    });

    const crumbs = wrapper.findAll(".page-header__crumb, .page-header__crumb-current");
    expect(crumbs.map((crumb) => crumb.text())).toEqual(["当前模块", "当前页面"]);
    expect(wrapper.find(".page-header__crumb-current").text()).toBe("当前页面");
    expect(wrapper.find(".page-header__breadcrumb").attributes("aria-label")).toBe("面包屑");
  });

  it("omits the breadcrumb entirely when no segment is given", () => {
    const wrapper = mount(PageHeader, { props: { title: "页面标题" } });

    expect(wrapper.find(".page-header__breadcrumb").exists()).toBe(false);
  });

  it("renders the actions slot next to the title", () => {
    const wrapper = mount(PageHeader, {
      props: { title: "页面标题" },
      slots: { actions: "<button data-testid='page-action'>操作</button>" },
    });

    expect(wrapper.find('[data-testid="page-action"]').exists()).toBe(true);
  });

  it("omits the actions container when the slot is not provided", () => {
    const wrapper = mount(PageHeader, { props: { title: "页面标题" } });

    expect(wrapper.find(".page-header__actions").exists()).toBe(false);
  });
});
