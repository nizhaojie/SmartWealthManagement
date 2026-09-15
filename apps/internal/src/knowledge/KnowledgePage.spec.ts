import ElementPlus, { ElMessageBox } from "element-plus";
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { KnowledgeDocument } from "./types";

const { listDocuments, uploadDocument, deleteDocument } = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
}));

vi.mock("./api", () => ({ listDocuments, uploadDocument, deleteDocument }));

import KnowledgePage from "./KnowledgePage.vue";

function makeDocument(overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    knowledge_id: 1,
    knowledge_type: "FAQ",
    title: "示例文档",
    source_file: "example.txt",
    version: "1",
    status: "active",
    chunk_count: 3,
    expire_at: null,
    create_time: "2026-01-01T00:00:00",
    stage: null,
    failure_reason: null,
    ...overrides,
  };
}

async function mountPage() {
  const wrapper = mount(KnowledgePage, { global: { plugins: [ElementPlus] } });
  await flushPromises();
  return wrapper;
}

describe("KnowledgePage", () => {
  beforeEach(() => {
    listDocuments.mockReset();
    uploadDocument.mockReset();
    deleteDocument.mockReset();
    listDocuments.mockResolvedValue([]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the required metadata columns for each document", async () => {
    listDocuments.mockResolvedValue([
      makeDocument({ knowledge_type: "政策", title: "开户须知", source_file: "policy.docx", version: "2", chunk_count: 5 }),
    ]);

    const wrapper = await mountPage();
    const text = wrapper.text();

    expect(text).toContain("政策");
    expect(text).toContain("开户须知");
    expect(text).toContain("policy.docx");
    expect(text).toContain("2");
    expect(text).toContain("5");
    expect(text).toContain("已入库");
  });

  it("passes the selected type and status filters to listDocuments", async () => {
    const wrapper = await mountPage();

    const [, typeFilterSelect] = wrapper.findAllComponents({ name: "ElSelect" });
    await typeFilterSelect.setValue("FAQ");
    await flushPromises();

    expect(listDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({ knowledgeType: "FAQ" }),
    );
  });

  it("shows the specific backend error message when upload fails instead of a generic message", async () => {
    uploadDocument.mockRejectedValue(new Error("不支持的文档格式，仅支持 txt / md / docx"));
    const wrapper = await mountPage();

    (wrapper.vm as unknown as { selectedFile: File | null }).selectedFile = new File(
      ["x"],
      "test.pdf",
    );
    await wrapper.find("button.el-button--primary").trigger("click");
    await flushPromises();

    expect(wrapper.text()).toContain("不支持的文档格式，仅支持 txt / md / docx");
  });

  it("does not delete when the confirmation dialog is cancelled", async () => {
    listDocuments.mockResolvedValue([makeDocument()]);
    vi.spyOn(ElMessageBox, "confirm").mockRejectedValue("cancel");

    const wrapper = await mountPage();
    await wrapper.find("button.el-button--danger").trigger("click");
    await flushPromises();

    expect(deleteDocument).not.toHaveBeenCalled();
  });

  it("deletes after confirmation and refreshes the list", async () => {
    listDocuments.mockResolvedValue([makeDocument()]);
    vi.spyOn(ElMessageBox, "confirm").mockResolvedValue(true as never);
    deleteDocument.mockResolvedValue(makeDocument({ status: "expired" }));

    const wrapper = await mountPage();
    await wrapper.find("button.el-button--danger").trigger("click");
    await flushPromises();

    expect(deleteDocument).toHaveBeenCalledWith(1);
    expect(listDocuments).toHaveBeenCalledTimes(2);
  });

  it("marks a document nearing its expiry date", async () => {
    const soon = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString();
    listDocuments.mockResolvedValue([makeDocument({ status: "active", expire_at: soon })]);

    const wrapper = await mountPage();

    expect(wrapper.text()).toContain("即将过期");
  });

  it("does not mark a document with a far-off expiry date", async () => {
    const farFuture = new Date(Date.now() + 200 * 24 * 60 * 60 * 1000).toISOString();
    listDocuments.mockResolvedValue([makeDocument({ status: "active", expire_at: farFuture })]);

    const wrapper = await mountPage();

    expect(wrapper.text()).not.toContain("即将过期");
  });
});
