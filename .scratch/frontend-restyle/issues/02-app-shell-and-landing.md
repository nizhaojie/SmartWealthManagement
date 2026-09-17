# 02 — AppShell、customer 路由化与 internal 落地页

**What to build:** `packages/shared` 新增 `AppShell`（浅色侧边栏 + 顶栏 + 内容插槽，导航项/品牌区/用户区由应用注入）。customer 应用补装 vue-router，四个视图获得真实 URL，顶部裸按钮导航被壳取代。internal 用 `AppShell` 重写 `WorkbenchShell`，并新增静态模块导航落地页作为登录后的默认路由。

**Blocked by:** 01 — 设计令牌层

**Status:** done

- [x] `AppShell` 在 shared 落地：无业务语义，导航项经 props 注入，品牌区/用户区/内容经插槽注入
- [x] 壳的全部视觉值来自 01 的令牌（浅色侧边栏 220px、顶栏 56px），无硬编码
- [x] 两个应用的依赖加入 `@element-plus/icons-vue`（本 slice 唯一新增依赖），侧边栏导航项配图标
- [x] **登出入口在壳层恒在**：任何角色、任何路由下可见可用（沿袭 internal-workbench-shell 的教训，有既有测试覆盖）
- [x] customer 引入 vue-router：智能客服 `/chat`、风险测评 `/risk-assessment`、产品筛选 `/products`、我的资产 `/assets`，登录页独立路由；刷新不丢视图、后退键正常
- [x] internal 的 `WorkbenchShell` 改为基于 `AppShell`，角色驱动导航与面包屑行为不变（`modules.ts` 留在 internal，不进 shared——ADR-0003）
- [x] internal 新增落地页路由 `/`：以入口卡片（图标+名称+描述）渲染登录者可见模块，数据来自既有 `MODULES` 配置，**零业务数据聚合**
- [x] 登录后默认路径从「第一个可见模块」改为落地页
- [x] 品牌区文案维持：customer「智能财富管家」、internal「内部工作台」
- [x] 组件测试：导航项渲染、登出恒在、customer 各视图 URL 可达；两端既有套件全绿

## 落地要点

- `AppShell` 只负责布局与导航渲染；「哪些模块对谁可见」是业务语义，internal 的 `visibleModules` 与 customer 的视图清单各自留在应用内，经 props 传入。
- customer 的 `App.vue` 目前用 `ref` 切换 `CustomerView`——路由化时删掉这套机制，`name="nav-*"` 的锚点属性保留（既有测试与走查依赖它们定位）。
- 落地页卡片是 internal 本地组件（它只出现一次，不够格进 shared——见 spec 复合组件节）。
- internal 的默认路径逻辑在 `modules.ts` 的 `defaultPathFor`，改为返回 `/`；落地页自身对无可见模块的角色要有空态说明（正常页面，不是错误状态——与占位模块同一原则）。

## 已知取舍

- shared 为跑 `AppShell` 组件测试新增了测试工具 devDependencies（`@vitejs/plugin-vue` / `@vue/test-utils` / `jsdom`）并给 vitest 配了 vue 插件——spec「唯一新增依赖」指运行时依赖，测试工具是 Testing Decisions 里「AppShell 组件测试」的必要推论，不进产物。
- customer 四个目的地放进 220px 侧边栏偏空，但换来两端单一壳组件与视觉血缘；若未来 customer 页面增多，这是正确方向的积累而非浪费。
- 落地页会让登录后多一次点击才能到工作模块——用「先看到全貌」换这一次点击，访谈中已确认值得（Q6 选 A 的理由）。
