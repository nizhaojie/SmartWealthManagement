// 时效提示只表达「有多新」：不足一天算今天，不写「0 天前」。
import { describe, expect, it } from "vitest";
import { elapsedDays, timelinessText } from "./timeliness";

const DAY_MS = 24 * 60 * 60 * 1000;
const NOW = new Date("2026-09-19T12:00:00Z");

describe("timeliness", () => {
  it("counts whole days since the plan was released", () => {
    expect(elapsedDays(new Date(NOW.getTime() - 3 * DAY_MS).toISOString(), NOW)).toBe(3);
    expect(elapsedDays(new Date(NOW.getTime() - 5 * 60 * 60 * 1000).toISOString(), NOW)).toBe(0);
  });

  it("writes 今天 instead of 0 天前 for a plan released today", () => {
    expect(timelinessText(new Date(NOW.getTime() - 60 * 1000).toISOString(), NOW)).toContain(
      "（今天）",
    );
    expect(timelinessText(new Date(NOW.getTime() - 3 * DAY_MS).toISOString(), NOW)).toContain(
      "（3 天前）",
    );
  });

  it("does not invent an age from an unparseable timestamp", () => {
    expect(elapsedDays("", NOW)).toBe(0);
  });
});
