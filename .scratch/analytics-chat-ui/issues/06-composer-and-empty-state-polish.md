# 06 — 输入区与空态的四处返工

**What to build:** 数据分析页的四处呈现返工：底部输入区换成客服侧的对话形态（左侧图标、单行、回车发送、没有换行）；「历史查询」从顶栏搬到页头「清空对话」的右侧；空态引导去掉限宽、铺满面板宽度；「试试这些」示例问题点击后**只填进输入框**，不再自动发送。

**Blocked by:** 03（对话壳与输入区）、05（历史查询进抽屉）——这两份交付的东西本次有三处被推翻。

**Status:** ready-for-agent

**本 ticket 推翻的既有决定（不静默偏离，逐条记下）：**

| 原决定 | 出处 | 本次改为 | 为什么 |
|---|---|---|---|
| 多行自适应输入框 + Ctrl+Enter 发送，Enter 换行 | spec Q14、ticket 03 | 单行输入，**回车发送、没有换行** | 与客服侧的对话输入取同一形态（同一系统里两处对话输入不该有两套回车约定）。中文输入法组字时的回车由输入法吃掉，不会再误发半句——这与「Enter 留给换行」原本要防的是同一件事，做法换了、保证没丢 |
| 「历史查询」挂 `AppShell` 的 `topbar-right` | spec Q9、ticket 05 | 页头操作区，「清空对话」的右侧 | 两个动作同属「这一页的对话控制」，分居顶栏与页头时不成组。第三栏仍然不渲染（`inspector` 插槽依旧不注入），两栏形态不变 |
| 空态示例问题**点击直接发问** | spec 的「对话壳与输入」、ticket 03 | 点击**只填入输入框**，发不发、要不要先改几个字由员工决定 | 与抽屉里「再问一次」取了同一条语义：示例只是把一句话送到手边，不是替人提问 |

**引导文案的限宽是 bug 不是设计**：`.empty__guide` 上的 `max-width: 60ch` 把这段话说成挤在面板左半边的一小列，右侧留出大片空白。去掉它。

- [ ] 输入区改成单行 `el-input`（去掉 `type="textarea"` 与 `:autosize`），左侧一个图标底座，与 `apps/customer/src/chat/ChatPage.vue` 的 composer 同形
- [ ] 回车提交走**表单的原生隐式提交**（不挂 `keydown`）：单行 input 承载不了换行，所以「没有换行」是形态决定的，不是靠拦键盘
- [ ] 占位文案里的快捷键说明跟着改（`（Ctrl + Enter 发送）` → `（回车发送）`），否则它会指向一个已失效的操作
- [ ] 「历史查询」改挂在页头操作区，排在「清空对话」右侧；撤掉 `useTopbarActions()` 调用，顶栏不再有这一页的按钮
- [ ] 空态引导去掉 `max-width: 60ch`
- [ ] 空态示例问题改为 emit「填进输入框」，不发起查询；空态因此仍留在页面上
- [ ] 同步三个 spec：`analyticsConversation.spec.ts`（示例问题改为只填不发、输入区改为单行）、`clearConversation.spec.ts` 与 `analyticsHistoryDrawer.spec.ts`（提问框选择器）、`analyticsHistoryDrawer.spec.ts`（入口从顶栏改页头）

**实现落点：** `apps/internal/src/analytics/MessageComposer.vue`、`EmptyConversation.vue`、`DataAnalysisWorkspace.vue` 与同目录三个 spec。**不进 `packages/shared`**（Q8 的同一条理由）。

**验收：** 输入框左侧有图标、单行、按回车直接发出且输入框里不可能出现换行；「历史查询」在「清空对话」右边，点开是抽屉；空态那句引导铺满面板宽度；点一条「试试这些」只把问题填进输入框，页面上不出现新一轮问答。
