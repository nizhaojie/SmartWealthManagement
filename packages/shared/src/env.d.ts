// packages/shared 的 tsc 不解析 .vue 单文件组件（那是各应用 vue-tsc 的事），
// 这里给出组件的类型占位，让 tsc 能顺着 index.ts 走完整张依赖图。
declare module "*.vue" {
  import type { DefineComponent } from "vue";

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}
