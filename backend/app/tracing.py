from contextvars import ContextVar
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
