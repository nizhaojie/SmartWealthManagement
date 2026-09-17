import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// scripts/ 下的边界检查用 node:test 跑，不属于 vitest 的收集范围。
// 组件测试（AppShell）需要 vue 插件编译 SFC；纯函数测试保持 node 环境不受影响，
// 需要浏览器环境的测试文件用 // @vitest-environment jsdom 单独声明。
export default defineConfig({
  plugins: [vue()],
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
    // 默认会把手头的 CSS 导入换成空模块，tokens.css?raw 也会被拦成空串；
    // 令牌测试需要读到 CSS 原文，这里开启真实处理。
    css: true,
  },
});
