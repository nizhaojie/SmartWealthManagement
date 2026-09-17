from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def get_trace_id() -> str:
    current = trace_id_var.get()
    if current:
        return current
    generated = str(uuid4())
    trace_id_var.set(generated)
    return generated


def bind_trace_id(trace_id: str | None) -> str:
    bound = trace_id or str(uuid4())
    trace_id_var.set(bound)
    return bound


@dataclass
class TokenUsage:
    """一次请求内所有模型调用的 token 用量合计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0


_usage_var: ContextVar[TokenUsage | None] = ContextVar("token_usage", default=None)


def start_token_usage() -> None:
    """请求（或一次 Agent 回合）开始时调用，之后模型调用报告的用量都累加到它上面。"""
    _usage_var.set(TokenUsage())


def record_token_usage(
    *, prompt_tokens: int | None, completion_tokens: int | None
) -> None:
    """累加一次模型调用报告的用量。没开始累计时静默丢弃——用量是增强信息，
    不该因为它而让调用失败。"""
    usage = _usage_var.get()
    if usage is None:
        return
    usage.prompt_tokens += prompt_tokens or 0
    usage.completion_tokens += completion_tokens or 0


def get_token_usage() -> TokenUsage | None:
    return _usage_var.get()
