# 01 — 设计令牌层

**What to build:** `packages/shared` 新增 theme 模块：`:root` CSS 自定义属性作为唯一事实源（色彩/文字/圆角/阴影/间距/字体/布局常量），Element Plus 的 `--el-*` 变量映射到令牌，TS 侧提供只读镜像供 JS 取色场景（ECharts 等），令牌值带对比度测试。两个应用的 `main.ts` 在 EP 样式之后引入 `tokens.css`。

这是后续所有 issue 的地基——壳、复合组件、逐页改造全部只消费这里的令牌，不允许各自发明色值。

**Blocked by:** 无

**Status:** done

- [x] `:root` 令牌文件覆盖 spec「设计令牌层」清单的全部类别（色彩/语义/涨跌/中性/文字/圆角/阴影/间距/字体/布局）
- [x] 涨跌色入令牌：`up #C81E1E` / `down #1E7A46`（红涨绿跌，独立语义名）
- [x] EP `--el-color-primary` 及其 light/dark 派生变量映射到 `primary #1F6FEB`
- [x] TS 只读镜像导出全部色彩令牌（含涨跌色），供 JS 取色
- [x] 对比度测试沿用 `palette.test.ts` 模式：文本类与涨跌令牌对白底 ≥ 4.5:1
- [x] `#9CA3AF` 以注释声明豁免并限定「仅占位与装饰」用途
- [x] 既有 `chart/palette.ts` 不动（图表分类色板与 UI 令牌是两个东西）
- [x] customer 与 internal 的 `main.ts` 在 `element-plus/dist/index.css` 之后引入令牌样式
- [x] `pnpm --filter @wealth/shared test` 与两端 `typecheck` 全绿

## 落地要点

- CSS 变量命名为避免与 EP 的 `--el-*` 撞名，使用统一前缀（如 `--wm-*`）。
- EP 主色派生变量（`--el-color-primary-light-3/5/7/8/9`、`dark-2`）必须一并映射，否则按钮 hover/disabled 态会露出 EP 默认蓝。
- TS 镜像只暴露色彩；间距/圆角/阴影没有 JS 消费方，留在 CSS 层即可。
- 对比度校验直接复用 `chart/color.ts` 里现成的 `contrastRatio`，不要另写一份。

## 已知取舍

- success 与 down 同值、danger 与 up 同值：在各自语境（操作反馈 vs 盈亏数字）不会误读，令牌名分开保留了未来分叉的余地。
- EP 组件内部着色（tag 浅底 + 彩色文字等）维持库默认，本 issue 不做无障碍加固——那是另一个横切问题，见 spec Out of Scope。
