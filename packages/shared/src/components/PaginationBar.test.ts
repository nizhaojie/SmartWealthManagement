// @vitest-environment jsdom
// 分页条是纯受控件：它自己不持有页码，只把 props 交给 el-pagination，并把
// 「翻到第几页」发出去。断言因此落在两处——传给控件的三个数、以及发出的事件。
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent } from "vue";
import PaginationBar from "./PaginationBar.vue";

// shared 不依赖 element-plus：el-pagination 由应用 app.use(ElementPlus) 全局注册，
// 这里用轻量 stub 把 props 落到 data-*，并用一次点击代替真实的页码按钮。
const ElPaginationStub = defineComponent({
  name: "ElPagination",
  props: {
    total: { type: Number, default: 0 },
    currentPage: { type: Number, default: 1 },
    pageSize: { type: Number, default: 20 },
    disabled: { type: Boolean, default: false },
  },
  emits: ["current-change"],
  template: `<button
    class="el-pagination-stub"
    :data-total="total"
    :data-current-page="currentPage"
    :data-page-size="pageSize"
    :data-disabled="String(disabled)"
    @click="$emit('current-change', currentPage + 1)"
  />`,
});

function mountBar(props: {
  total: number;
  page: number;
  pageSize: number;
  disabled?: boolean;
}) {
  return mount(PaginationBar, {
    props,
    global: { stubs: { ElPagination: ElPaginationStub } },
  });
}

describe("PaginationBar", () => {
  it("shows the total that came with the page", () => {
    const wrapper = mountBar({ total: 45, page: 2, pageSize: 20 });

    expect(wrapper.get('[data-testid="pagination-total"]').text()).toBe("共 45 条");
  });

  it("hands the current page, page size and total to the pager instead of keeping its own", () => {
    const wrapper = mountBar({ total: 45, page: 2, pageSize: 20 });

    const pager = wrapper.get(".el-pagination-stub");
    expect(pager.attributes("data-total")).toBe("45");
    expect(pager.attributes("data-current-page")).toBe("2");
    expect(pager.attributes("data-page-size")).toBe("20");
  });

  it("emits the page the caller should fetch, without fetching anything itself", async () => {
    const wrapper = mountBar({ total: 45, page: 2, pageSize: 20 });

    await wrapper.get(".el-pagination-stub").trigger("click");

    expect(wrapper.emitted("update:page")).toEqual([[3]]);
  });

  it("is enabled while nothing is in flight", () => {
    const wrapper = mountBar({ total: 45, page: 2, pageSize: 20 });

    expect(wrapper.get(".el-pagination-stub").attributes("data-disabled")).toBe("false");
  });

  it("greys the pager out while a request is in flight", () => {
    const wrapper = mountBar({ total: 45, page: 2, pageSize: 20, disabled: true });

    expect(wrapper.get(".el-pagination-stub").attributes("data-disabled")).toBe("true");
  });
});
