// 令牌纪律的回归闸门：shared 的展示件（壳、卡片、KPI、进度条、页面头、图表壳）
// 不允许出现任何裸十六进制色值——着色只能经 --wm-* 令牌。
// 这是对 review 纪律的机器化：把「硬编码值全部替换为令牌」钉进测试。

import { describe, expect, it } from "vitest";
import appShellSource from "../shell/AppShell.vue?raw";
import chartFrameSource from "../chart/ChartFrame.vue?raw";
import tokensCssSource from "../theme/tokens.css?raw";
import meterBarSource from "./MeterBar.vue?raw";
import pageHeaderSource from "./PageHeader.vue?raw";
import paginationBarSource from "./PaginationBar.vue?raw";
import panelCardSource from "./PanelCard.vue?raw";
import statCardSource from "./StatCard.vue?raw";

const COMPONENT_SOURCES: Array<[string, string]> = [
  ["AppShell.vue", appShellSource],
  ["PanelCard.vue", panelCardSource],
  ["StatCard.vue", statCardSource],
  ["MeterBar.vue", meterBarSource],
  ["PageHeader.vue", pageHeaderSource],
  ["PaginationBar.vue", paginationBarSource],
  ["ChartFrame.vue", chartFrameSource],
];

const GLOBAL_TOKEN_NAMES = new Set(
  [...tokensCssSource.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]),
);

function referencedVariables(source: string): Set<string> {
  return new Set([...source.matchAll(/var\((--[\w-]+)/g)].map((match) => match[1]));
}

function declaredLocally(source: string): Set<string> {
  return new Set([...source.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]));
}

describe("共享组件令牌纪律", () => {
  for (const [name, source] of COMPONENT_SOURCES) {
    it(`${name} 不含裸十六进制色值`, () => {
      expect(source.match(/#[0-9a-fA-F]{3,8}\b/g) ?? []).toEqual([]);
    });

    it(`${name} 引用的每个 CSS 变量都可解析`, () => {
      // var() 拼错名字不会报错，只会静默回退成浏览器默认值——
      // 组件测试挂载不出这个错，这里以「全局令牌或组件内局部声明」为解析边界堵死。
      const local = declaredLocally(source);
      const unresolved = [...referencedVariables(source)].filter(
        (name_) => !GLOBAL_TOKEN_NAMES.has(name_) && !local.has(name_),
      );

      expect(unresolved).toEqual([]);
    });
  }
});
