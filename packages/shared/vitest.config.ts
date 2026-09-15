import { defineConfig } from "vitest/config";

// scripts/ 下的边界检查用 node:test 跑，不属于 vitest 的收集范围。
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
