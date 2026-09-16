"""投顾助手 Agent 的 LangGraph 运行时（ADR-0007）。

一个进程级单例 checkpointer：生成流程在产出 AI 原稿后调用 `interrupt()`
暂停，暂停期间的状态由它承接；理财顾问放行或驳回时，用同一个
checkpointer、同一个 thread_id 重新编译一次图并以 `Command(resume=...)`
续跑，就能接回中断前的状态——暂停与恢复本身不需要我们自己实现。

用内存实现是当前唯一可用的 checkpointer 后端（未引入额外的 Postgres/
Sqlite checkpoint 依赖），意味着待审内容的暂停状态不扛后端进程重启；
这条线的护栏是「未经审核不可送达客户」，不是「重启不丢待审队列」，两者
不冲突，重启后可重新生成方案。
"""

from langgraph.checkpoint.memory import MemorySaver

ADVISORY_CHECKPOINTER = MemorySaver()
