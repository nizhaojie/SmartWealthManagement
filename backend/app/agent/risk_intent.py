"""高风险意图识别：客户在对话里露出规避风控、异常资金流动的苗头时，客服 Agent
把它作为一条事件广播出去，风控监测 Agent 订阅后留下关注记录。

判断由关键词的确定性匹配做出，不经过模型——与风控规则的阈值判断同一口径：要不要
提醒风控看一眼，规则说得清楚就够了，模型只负责把答案讲成人话。识别到不等于定性：
它不产生预警、不改变任何服务的可用性，只是「这位客户值得看一眼」。

「反复」是数出来的，不是猜出来的：同一会话里第 N 次问同一类事，理由里才写「反复」。
会话不跨登录延续（ADR-0012 的短期记忆），所以计数也随登录重新开始——这与「反复」
在业务上的含义一致：一次登录里反复打听，比隔着几天的两次提问更值得当场提醒。

问题原文不进事件载荷：载荷只带判定结论（代码与理由），对话原文留在会话归档那里
按脱敏规则处理，不因为一次提醒而多出一份未脱敏的副本。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskIntent:
    """一次识别结果：判定的类别与可直接展示的理由。"""

    code: str
    reason: str


@dataclass(frozen=True)
class _Signal:
    """一类高风险意图：代码、可读的事由、触发它的关键词。"""

    code: str
    subject: str
    keywords: tuple[str, ...]


# 关键词宁窄勿宽——过宽的词会让正常的转账咨询也变成「值得关注」，风控那边很快
# 就会被噪音淹掉，真正的苗头反而看不见。
_SIGNALS: tuple[_Signal, ...] = (
    _Signal(
        code="TRANSFER_LIMIT",
        subject="打听转账限额规避方式",
        keywords=("转账限额", "拆分转账", "分拆转账", "分几笔转", "分几次转", "规避限额", "绕过限额"),
    ),
    _Signal(
        code="SUSPICIOUS_FLOW",
        subject="打听可疑资金流转方式",
        keywords=("洗钱", "套现", "跑分", "帮人转账", "帮别人转账", "代收款", "过一下账"),
    ),
    _Signal(
        code="OVERSEAS_REMITTANCE",
        subject="打听资金出境方式",
        keywords=("境外汇款", "资金出境", "购汇", "换汇"),
    ),
)


def _signal_for(question: str) -> _Signal | None:
    return next(
        (signal for signal in _SIGNALS if any(word in question for word in signal.keywords)),
        None,
    )


def _mentions(question: str, code: str) -> bool:
    signal = _signal_for(question)
    return signal is not None and signal.code == code


def _repeat_count(code: str, history: Sequence[Mapping[str, object]]) -> int:
    """同一会话里，这位客户第几次问到同一类事（含当前这一句）。"""
    earlier = sum(
        1
        for message in history
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and _mentions(str(message["content"]), code)
    )
    return 1 + earlier


def detect_risk_intent(
    question: str, *, history: Sequence[Mapping[str, object]] = ()
) -> RiskIntent | None:
    """识别一句问话里的高风险意图；没有就返回 None。"""
    signal = _signal_for(question)
    if signal is None:
        return None
    prefix = "反复" if _repeat_count(signal.code, history) > 1 else ""
    return RiskIntent(code=signal.code, reason=f"{prefix}{signal.subject}")
