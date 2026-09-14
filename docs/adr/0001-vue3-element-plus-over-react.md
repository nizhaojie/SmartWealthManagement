# 前端用 Vue 3 + Element Plus，而不是 React

两个前端应用采用 Vue 3 + TypeScript + Element Plus + ECharts。这是一个需要记录的选择，因为本组在上一个项目（粤教）里刚刚做完相反方向的迁移——2026-09-10 删除了 Vue 前端、全量合流到 React，并归档了 18 条路由的双端对比证据。任何看到那段历史的人都会问这次为什么又回到 Vue。

## Considered Options

- **React + Ant Design**——被拒绝。它与团队上一个项目刚沉淀的技术栈一致，隔壁 `SmartWealthManagementSystem` 还有一套同需求的 React 实现可参考。拒绝的理由是 Element Plus 的表格、表单与抽屉更贴合本项目的中后台形态。
- **React + Element Plus**——不成立。Element Plus 是 Vue 3 专属组件库，没有 React 版本；历史上的 `element-react` 对应的是 Vue 2 时代的 Element UI，已多年未更新，不支持现代 React。
- **Vue + 其他组件库（Naive UI / Arco Design Vue）**——被拒绝。选 Vue 的动因本就是 Element Plus，换掉它等于两头落空。

## Consequences

隔壁那套 React 前端从此只能作为组件划分与 API 层的设计参考，一行代码都搬不过来。后端不受影响——它是 Python，与前端框架无关。
