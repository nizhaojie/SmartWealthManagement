# 用 LangGraph 作为单一 Agent 运行时，四个 Agent 是四份配置

四个 Agent 共用一套 LangGraph 运行时，按登录角色装配不同的 Agent 配置（提示词、工具集、记忆策略、内容分类默认值），而不是四套独立实现。

## Considered Options

- **LangChain 的 AgentExecutor / ReAct 循环**——被拒绝。投顾内容的审核流与预警的工单处置流本质都是状态机，中途要停下等人操作再恢复；在黑箱 ReAct 循环里插入人工环节需要大量改造，而 LangGraph 的 interrupt 加 checkpointer 正是为 human-in-the-loop 设计的。
- **不用框架，编排自己写**——被拒绝。等于重新实现一遍状态持久化与中断恢复。
- **supervisor Agent 做意图路由再分派**——被拒绝。角色在登录时已经确定，客户不可能需要路由到风控 Agent；用 LLM 判断一件登录态已经确定的事，只增加成本与被诱导的风险。

## Consequences

这是本项目锁定成本最高的技术选择：LangGraph 的状态机模型会渗透进审核流与风控处置流的实现方式，换回普通 Agent 循环意味着重写 human-in-the-loop 的全部衔接。学习曲线集中在第一周。

选它的直接收益是：四个 Agent 都要做到完整深度，单运行时四配置省掉四遍重复的编排逻辑。
