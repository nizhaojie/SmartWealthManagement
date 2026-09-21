"""内容分类与免责声明模板——五个 Agent 共用（ADR-0007）。

分类只有两种：事实性内容与投顾内容。哪一种由调用方实际调用了什么工具
决定，不由模型自己声明——模型可能会算错或者被诱导，工具调用是结构性
事实。免责声明同理：附不附、附什么文本，由这里的模板决定，不依赖模型
记得在输出末尾写一句话。
"""

FACTUAL_CONTENT = "事实性内容"
ADVISORY_CONTENT = "投顾内容"

DISCLAIMER = (
    "本内容仅为投资分析参考，不构成任何直接投资建议，"
    "不构成对任何产品的收益承诺，据此操作风险自负，请谨慎对待。"
)


def disclaimer_for(content_classification: str) -> str | None:
    return DISCLAIMER if content_classification == ADVISORY_CONTENT else None
