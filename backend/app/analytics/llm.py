"""查询生成：把自然语言问题转成一条作用于语义视图的 SELECT。

fake provider 是确定性实现，且**可被配置为返回指定查询**——包括恶意
查询。护栏测试借此验证校验层与视图层拦得住，而不是验证模型乖：
- ``register_fake_query(question, sql)`` 注册一条精确命中问题的返回；
- 未注册时，若问题与某条示例完全相同，返回该示例的查询；
- 否则按「无法生成查询」处理。

每次调用都会记入 ``fake_generation_calls``，测试据此断言提示词里注入了
哪些视图定义与示例（关键词筛选的 seam）。
"""

from dataclasses import dataclass

from app.analytics.audience import Audience
from app.analytics.errors import (
    GENERATION_FAILED_CODE,
    GENERATION_FAILED_MESSAGE,
    OUT_OF_SCOPE_CODE,
    OUT_OF_SCOPE_MESSAGE,
)
from app.analytics.examples import QueryExample
from app.exceptions import AppError
from app.llm.provider import chat_completion
from app.replay import library as replay_library
from app.settings import Settings

_EMPLOYEE_SYSTEM_PROMPT = (
    "你是数据分析 Agent 的查询生成器，把内部员工的自然语言问题转成一条 MySQL 查询。"
    "硬性规则：只输出一条 SELECT 语句；只能查询给定的语义视图，不得访问任何其他表；"
    "不得使用注释、分号、SET 或变量；只输出 SQL 本身，不要输出解释。"
    "如果给定的语义视图无法回答该问题，只输出 OUT_OF_SCOPE。"
)

# 客户口径多两条约束，都是 ADR-0025 那条边界的落点：查询范围已经由视图锁死为本人，
# 因此不需要（也不允许）再按客户标识筛；产品查询只筛不排序——按收益或费率排序就是
# 在替客户比较产品，那是投顾助手的产物。
_CUSTOMER_SYSTEM_PROMPT = (
    "你是智能客服的数据查询生成器，把客户本人的问题转成一条 MySQL 查询。"
    "硬性规则：只输出一条 SELECT 语句；只能查询给定的语义视图，不得访问任何其他表；"
    "不得使用注释、分号、SET 或变量；只输出 SQL 本身，不要输出解释。"
    "给定的语义视图已经锁定为提问客户本人的数据，不要按客户标识筛选。"
    "涉及产品时只允许按风险等级筛选（客户等级 Cn 可筛 R1–Rn），不得评分、不得排序，"
    "只按产品代码排序。"
    "如果给定的语义视图无法回答该问题，只输出 OUT_OF_SCOPE。"
)

_SYSTEM_PROMPTS: dict[Audience, str] = {
    Audience.EMPLOYEE: _EMPLOYEE_SYSTEM_PROMPT,
    Audience.CUSTOMER: _CUSTOMER_SYSTEM_PROMPT,
}

_OUT_OF_SCOPE_TOKEN = "OUT_OF_SCOPE"


@dataclass
class FakeGenerationCall:
    question: str
    view_names: list[str]
    view_definitions: str
    examples: list[QueryExample]
    history: list[dict]


fake_generation_calls: list[FakeGenerationCall] = []
_fake_overrides: dict[str, str] = {}


def register_fake_query(question: str, sql: str) -> None:
    """把 fake provider 配置为对指定问题返回指定查询（含恶意查询）。"""
    _fake_overrides[question] = sql


def clear_fake_queries() -> None:
    _fake_overrides.clear()
    fake_generation_calls.clear()


def _example_match(question: str, examples: list[QueryExample]) -> str | None:
    """问题与某条示例完全相同则返回该示例的查询（fake 与回放的共同回退）。"""
    for example in examples:
        if example.question == question:
            return example.sql
    return None


def generate_query(
    question: str,
    view_names: list[str],
    view_definitions: str,
    examples: list[QueryExample],
    settings: Settings,
    history: list[dict] | None = None,
    audience: Audience = Audience.EMPLOYEE,
) -> str:
    history = history or []
    # 回放模式（ADR-0008）不发起模型调用：预置问题返回预写 SQL，其余问题与
    # fake provider 同一确定性回退（示例精确命中，否则「无法生成查询」）。
    if settings.demo_replay:
        preset = replay_library.analytics_preset(question)
        if preset is not None:
            return preset.sql
        matched = _example_match(question, examples)
        if matched is not None:
            return matched
        raise AppError(GENERATION_FAILED_CODE, GENERATION_FAILED_MESSAGE)
    if settings.resolved_llm_provider == "fake":
        return _fake_generate(question, view_names, view_definitions, examples, history)
    return _openai_compatible_generate(
        question, view_definitions, examples, settings, history, audience
    )


def _fake_generate(
    question: str,
    view_names: list[str],
    view_definitions: str,
    examples: list[QueryExample],
    history: list[dict],
) -> str:
    fake_generation_calls.append(
        FakeGenerationCall(
            question=question,
            view_names=view_names,
            view_definitions=view_definitions,
            examples=examples,
            history=history,
        )
    )
    if question in _fake_overrides:
        return _fake_overrides[question]
    matched = _example_match(question, examples)
    if matched is not None:
        return matched
    raise AppError(GENERATION_FAILED_CODE, GENERATION_FAILED_MESSAGE)


def _openai_compatible_generate(
    question: str,
    view_definitions: str,
    examples: list[QueryExample],
    settings: Settings,
    history: list[dict],
    audience: Audience,
) -> str:
    example_text = "\n".join(
        f"问题：{example.question}\n查询：{example.sql}" for example in examples
    )
    history_text = "\n".join(
        f"{message['role']}：{message['content']}" for message in history
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPTS[audience]},
        {
            "role": "user",
            "content": (
                f"语义视图定义：\n{view_definitions}\n\n"
                f"示例：\n{example_text}\n\n"
                f"对话历史：\n{history_text}\n\n"
                f"问题：{question}"
            ),
        },
    ]
    content = _strip_code_fence(chat_completion(messages, settings).strip())
    if not content or content == _OUT_OF_SCOPE_TOKEN:
        raise AppError(OUT_OF_SCOPE_CODE, OUT_OF_SCOPE_MESSAGE)
    return content


def _strip_code_fence(content: str) -> str:
    # 模型常把 SQL 包在 ```sql ... ``` 里，剥掉围栏再交给校验层。
    if content.startswith("```"):
        lines = content.splitlines()
        lines = lines[1:] if lines else []
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content
