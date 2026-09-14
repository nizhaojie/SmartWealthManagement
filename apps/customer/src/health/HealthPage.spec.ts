import ElementPlus from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { fetchHealth } from "../api/health";
import HealthPage from "./HealthPage.vue";

vi.mock("../api/health", () => ({
  fetchHealth: vi.fn(),
}));

describe("HealthPage", () => {
  it("renders dependency connectivity returned by the http client", async () => {
    vi.mocked(fetchHealth).mockResolvedValue({
      status: "degraded",
      llm_provider: "fake",
      dependencies: {
        mysql: { ok: true },
        redis: { ok: true },
        etcd: { ok: false },
        minio: { ok: true },
        milvus: { ok: true },
        neo4j: { ok: true },
      },
    });

    const wrapper = mount(HealthPage, {
      global: { plugins: [ElementPlus] },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("降级");
    expect(wrapper.text()).toContain("mysql");
    expect(wrapper.text()).toContain("连通");
    expect(wrapper.text()).toContain("etcd");
    expect(wrapper.text()).toContain("断开");
    expect(wrapper.text()).toContain("fake");
  });
});
