import { describe, expect, it } from "vitest";
import { splitCitations } from "./citations";
import type { Citation } from "./api";

function citation(overrides: Partial<Citation> = {}): Citation {
  return {
    knowledge_id: 1,
    chunk_index: 0,
    title: "文档",
    source_file: "doc.txt",
    heading_path: [],
    marker: 1,
    ...overrides,
  };
}

describe("splitCitations", () => {
  it("leaves answers without citations as a single text segment", () => {
    expect(splitCitations("没有依据时我不作答。", [])).toEqual([
      { type: "text", value: "没有依据时我不作答。" },
    ]);
  });

  it("keeps a marker as plain text when no citation carries it", () => {
    // 宁可露出一个 `[3]`，也不能凭空造一条来源。
    expect(splitCitations("见[3]。", [citation({ marker: 1 })])).toEqual([
      { type: "text", value: "见" },
      { type: "text", value: "[3]" },
      { type: "text", value: "。" },
    ]);
  });

  it("resolves markers by value regardless of their order in the text", () => {
    const segments = splitCitations("先[2]后[1]。", [
      citation({ marker: 1, title: "费率说明" }),
      citation({ knowledge_id: 2, marker: 2, title: "赎回规则" }),
    ]);

    expect(segments).toEqual([
      { type: "text", value: "先" },
      { type: "citation", marker: "2", citationIndex: 1 },
      { type: "text", value: "后" },
      { type: "citation", marker: "1", citationIndex: 0 },
      { type: "text", value: "。" },
    ]);
  });
});
