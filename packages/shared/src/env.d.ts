// packages/shared 的 tsc 不解析 .vue 单文件组件（那是各应用 vue-tsc 的事），
// 这里给出组件的类型占位，让 tsc 能顺着 index.ts 走完整张依赖图。
declare module "*.vue" {
  import type { DefineComponent } from "vue";

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}

// Vite 的 ?raw 后缀：以字符串形式导入文件原文（如令牌测试读取 tokens.css）。
declare module "*?raw" {
  const content: string;
  export default content;
}
