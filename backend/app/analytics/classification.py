"""输出的内容分类与免责声明（CONTEXT.md：投顾内容与事实性内容之分）。

数据分析 Agent 的内容分类默认值是事实性内容——它只解读内部数据查询的
结果。当问题本身要求一份**面向客户的报告类内容**（投资研报、财富报告、
行业分析）时，输出按投顾内容对待，并由模板在输出末尾附上免责声明——
声明是结构的一部分，不依赖模型记得写。

已知的边界：判定看的是**问题**的关键词，而非生成内容本身。问法不含
关键词但输出实质是报告时不会附声明——这是启发式的固有缺口，方向是
保守的（宁可多附），更严格的判定留给需要它的 slice。

分类常量与免责声明模板本身在 ``app.agent.classification``——投顾助手
Agent 同样要用同一份声明文本，不各自维护一份。
"""

from app.agent.classification import ADVISORY_CONTENT, DISCLAIMER, FACTUAL_CONTENT, disclaimer_for

# 面向客户的报告类问法。命中即按投顾内容对待：宁可多附一次声明。
_REPORT_CLASS_KEYWORDS = ("研报", "财富报告", "行业分析", "投资报告")

__all__ = [
    "FACTUAL_CONTENT",
    "ADVISORY_CONTENT",
    "DISCLAIMER",
    "classify_output",
    "disclaimer_for",
]


def classify_output(question: str, *, default: str = FACTUAL_CONTENT) -> str:
    """按问题判定输出分类；不命中报告类时回落到 Agent 配置的默认值。"""
    if any(keyword in question for keyword in _REPORT_CLASS_KEYWORDS):
        return ADVISORY_CONTENT
    return default
