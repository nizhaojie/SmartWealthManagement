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


def has_pending_checkpoint(thread_id: str) -> bool:
    """这个 thread_id 是否还有可恢复的暂停状态。

    内存 checkpointer 不扛后端进程重启：重启后暂停状态丢失，此时不能再用
    ``Command(resume=...)`` 续跑——LangGraph 会找不到中断点，从入口节点
    重新执行，而恢复请求没有初始 state，各节点按 ``state[...]`` 取值会抛
    ``KeyError``。放行/驳回前先查这里，把「状态已丢」对外说成一个明确的
    业务错误，而不是把 KeyError 漏成 500。
    """
    return ADVISORY_CHECKPOINTER.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
