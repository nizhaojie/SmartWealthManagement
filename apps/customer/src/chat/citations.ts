// 把回答里的 `[n]` 切成文本段与引用段。
//
// 匹配按 marker 的值精确进行，不按角标在文本里出现的顺序——后端 build_citations
// 保留的序号与 citations 数组顺序并不保证一致，按位置猜会把引用挂错论断。
import type { Citation } from "./api";

export type TextSegment = { type: "text"; value: string };

export type CitationSegment = {
  type: "citation";
  marker: string;
  citationIndex: number;
};

export type ChatSegment = TextSegment | CitationSegment;

const MARKER_PATTERN = /\[(\d+)\]/g;

export function splitCitations(text: string, citations: readonly Citation[]): ChatSegment[] {
  if (citations.length === 0) {
    return [{ type: "text", value: text }];
  }

  const segments: ChatSegment[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = MARKER_PATTERN.exec(text))) {
    if (match.index > lastIndex) {
      segments.push({ type: "text", value: text.slice(lastIndex, match.index) });
    }
    const marker = match[1];
    const citationIndex = citations.findIndex((citation) => citation.marker === Number(marker));
    if (citationIndex === -1) {
      // 没有对应引用时原样保留角标文本：宁可露出一个 `[3]`，也不能凭空造一条来源。
      segments.push({ type: "text", value: match[0] });
    } else {
      segments.push({ type: "citation", marker, citationIndex });
    }
    lastIndex = MARKER_PATTERN.lastIndex;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", value: text.slice(lastIndex) });
  }

  return segments;
}
