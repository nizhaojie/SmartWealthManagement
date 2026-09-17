import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5174,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    // 组件测试要挂载真实的 Element Plus 组件（多个页面还带表格与日期选择器），
    // 单文件并发跑时一次挂载可能超过默认的 5 秒。放宽上限只是给慢机器留出余量，
    // 不会让断言变松——这里没有轮询式的等待。
    testTimeout: 15000,
  },
});
