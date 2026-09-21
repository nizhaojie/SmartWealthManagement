"""投顾内容的类型，以及每类内容在审核中断处的恢复运行时。

审核流水线按内容类型无关的方式工作：审核记录、加锁、队列与审核历史只认
「内容类型 + 内容引用」这一对标识，不认载荷长什么样——载荷长什么样是各内容
类型自己的事（方案与操作建议的载荷分表，见 ADR-0020）。

内容类型只在两处起作用：

- 队列与历史给每条内容打上类型标注，让顾问知道面前的是哪一类内容；
- 放行/驳回时按类型找到那次生成运行，把它从中断处恢复。

第二处是**登记**而不是 if/elif：各内容类型的图在自己的定义处调用
`register_resume_graph` 登记（见 app.advisory.graph），审核流水线只做查表。
类型没有登记运行时时宁可报错，也不回退到别的内容类型的图上——跑错图就是
把一份决定喂给了另一份内容，而且不会有任何测试当场发现。
"""

from collections.abc import Callable
from typing import Any

from app.exceptions import AppError

CONTENT_TYPE_PLAN = "方案"
CONTENT_TYPE_OPERATION_ADVICE = "操作建议"

NO_RESUME_RUNTIME_MESSAGE = "该内容类型尚未接入审核运行时"

# (db, cache) -> 已 compile 的 LangGraph 图
ResumeGraphBuilder = Callable[..., Any]

_RESUME_GRAPH_BUILDERS: dict[str, ResumeGraphBuilder] = {}


def register_resume_graph(content_type: str, builder: ResumeGraphBuilder) -> None:
    _RESUME_GRAPH_BUILDERS[content_type] = builder


def resume_graph_builder(content_type: str) -> ResumeGraphBuilder:
    builder = _RESUME_GRAPH_BUILDERS.get(content_type)
    if builder is None:
        raise AppError(500, NO_RESUME_RUNTIME_MESSAGE)
    return builder
