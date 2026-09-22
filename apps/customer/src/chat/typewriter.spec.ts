// 打字机限速器：逐字节奏、end 排队定案、flush 立即收尾、停表重启。
// 只测限速语义，不测页面渲染。
import { describe, expect, it, vi } from "vitest";
import { createTypewriter } from "./typewriter";

describe("createTypewriter", () => {
  it("forwards buffered text one character per interval tick", () => {
    vi.useFakeTimers();
    try {
      const chars: string[] = [];
      const typewriter = createTypewriter(30, (char) => chars.push(char));

      typewriter.push("你好");

      expect(chars).toEqual([]);
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["你"]);
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["你", "好"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("runs the end callback only after the buffer drains", () => {
    vi.useFakeTimers();
    try {
      const chars: string[] = [];
      const settled = vi.fn();
      const typewriter = createTypewriter(30, (char) => chars.push(char));

      typewriter.push("你好");
      typewriter.end(settled);

      // done 到达不等于定案：缓冲还没吐完，回调不得提前执行。
      expect(settled).not.toHaveBeenCalled();
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["你"]);
      expect(settled).not.toHaveBeenCalled();

      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["你", "好"]);
      expect(settled).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("runs the end callback immediately when the buffer is already empty", () => {
    vi.useFakeTimers();
    try {
      const settled = vi.fn();
      const typewriter = createTypewriter(30, () => {});

      typewriter.end(settled);
      expect(settled).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("flushes the remaining buffer at once and stops ticking", () => {
    vi.useFakeTimers();
    try {
      const chars: string[] = [];
      const typewriter = createTypewriter(30, (char) => chars.push(char));

      typewriter.push("你好世界");
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["你"]);

      typewriter.flush();
      expect(chars).toEqual(["你", "好世界"]);

      vi.advanceTimersByTime(1000);
      expect(chars).toEqual(["你", "好世界"]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops the timer when the buffer drains and resumes on the next push", () => {
    vi.useFakeTimers();
    try {
      const chars: string[] = [];
      const typewriter = createTypewriter(30, (char) => chars.push(char));

      typewriter.push("好");
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["好"]);

      vi.advanceTimersByTime(1000);
      expect(chars).toEqual(["好"]);

      typewriter.push("啊");
      vi.advanceTimersByTime(30);
      expect(chars).toEqual(["好", "啊"]);
    } finally {
      vi.useRealTimers();
    }
  });
});
