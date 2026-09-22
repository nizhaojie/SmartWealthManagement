import { describe, expect, it } from "vitest";
import { formatDateTime } from "./datetime";

describe("formatDateTime", () => {
  it("renders a timestamp as YYYY-MM-DD HH:mm:ss", () => {
    expect(formatDateTime("2022-04-10T10:30:00")).toBe("2022-04-10 10:30:00");
  });

  it("zero-pads every part", () => {
    expect(formatDateTime("2022-01-02T03:04:05")).toBe("2022-01-02 03:04:05");
  });

  it("keeps the original value when it cannot be parsed", () => {
    expect(formatDateTime("不是时间")).toBe("不是时间");
  });
});
