"""结果解读：把结果集与原始问题一起送入模型，生成自然语言解读。

解读必须说明数据口径——同一个「收益率」在不同口径下是不同的数字，
只给结论不给口径会误导。因此无论真假 provider，视图的口径说明都
进入解读：fake provider 直接引用，真实 provider 在提示词中被要求
复述口径。

解读按使用者口径分两套（ADR-0025）：员工侧是内部研判，客户侧是**面向本人的
事实陈述**。两者差在说话对象与边界上——客户那一套把数字直接写进文本，不许出现
投资建议、收益预测与产品推荐（只筛不排序的产品清单才轮得到客服说，见 ADR-0005）。
"""

from app.analytics.audience import Audience
from app.analytics.catalog import ViewSpec
from app.analytics.execution import QueryResult
from app.exceptions import AppError
from app.llm.provider import chat_completion
from app.replay import library as replay_library
from app.settings import Settings

_EMPLOYEE_SYSTEM_PROMPT = (
    "你是数据分析 Agent 的结果解读器。根据员工的原始问题、查询结果与语义视图的"
    "口径说明，用两到四句中文解读这些数字意味着什么。硬性规则：必须明确说明数据"
    "口径（统计范围与字段定义），不得给出投资建议或收益预测，不得编造结果中不存"
    "在的数字。"
)

_CUSTOMER_SYSTEM_PROMPT = (
    "你是智能客服的结果解读器，面对的是提问的客户本人。根据客户的原始问题、查询"
    "结果与语义视图的口径说明，用两到四句中文把结果讲给客户，把数字直接写进文本。"
    "硬性规则：必须明确说明数据口径（统计范围与字段定义），只陈述查询结果里的事实，"
    "不得给出投资建议、收益预测或产品推荐，不得评价产品好坏，不得编造结果中不存"
    "在的数字。"
)

_SYSTEM_PROMPTS: dict[Audience, str] = {
    Audience.EMPLOYEE: _EMPLOYEE_SYSTEM_PROMPT,
    Audience.CUSTOMER: _CUSTOMER_SYSTEM_PROMPT,
}


def generate_interpretation(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    settings: Settings,
    *,
    audience: Audience = Audience.EMPLOYEE,
) -> str:
    # 回放模式（ADR-0008）不发起模型调用：预置问题返回预写解读，其余问题
    # 用与 fake provider 相同的带口径模板。
    if settings.demo_replay:
        preset = replay_library.analytics_preset(question)
        if preset is not None:
            return preset.interpretation
        return _fake_interpret(question, views, result, audience=audience)
    if settings.resolved_llm_provider == "fake":
        return _fake_interpret(question, views, result, audience=audience)
    return _openai_compatible_interpret(question, views, result, settings, audience)


def _basis_text(views: list[ViewSpec]) -> str:
    return "；".join(view.summary for view in views)


def _fake_interpret(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    *,
    audience: Audience,
) -> str:
    if audience == Audience.CUSTOMER:
        return _fake_customer_interpret(views, result)
    truncated_note = "，结果超出行数上限已截断" if result.truncated else ""
    return (
        f"问题「{question}」的查询共返回 {len(result.rows)} 行{truncated_note}。"
        f"数据口径：{_basis_text(views)}"
    )


def _fake_customer_interpret(views: list[ViewSpec], result: QueryResult) -> str:
    """客户口径的确定性解读：数字直接写进文本，不加任何评价。

    真实 provider 下的措辞由模型给，这里给的是同一份要求的确定性版本——测试与
    回放看到的就是客户会看到的形态。
    """
    truncated_note = "（结果超出行数上限，已截断）" if result.truncated else ""
    rows = "；".join(
        "，".join(
            f"{column} 为 {value}" for column, value in zip(result.columns, row)
        )
        for row in result.rows[:5]
    )
    return (
        f"为您查到 {len(result.rows)} 行数据{truncated_note}：{rows}。"
        f"数据口径：{_basis_text(views)}"
    )


def _openai_compatible_interpret(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    settings: Settings,
    audience: Audience,
) -> str:
    rows_preview = "\n".join(
        ", ".join(str(value) for value in row) for row in result.rows[:20]
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPTS[audience]},
        {
            "role": "user",
            "content": (
                f"原始问题：{question}\n\n"
                f"视图口径说明：{_basis_text(views)}\n\n"
                f"结果列：{', '.join(result.columns)}\n"
                f"结果行（共 {len(result.rows)} 行"
                f"{'，已截断' if result.truncated else ''}）：\n{rows_preview}"
            ),
        },
    ]
    try:
        return chat_completion(messages, settings).strip()
    except AppError:
        # 解读失败不应让一次成功的查询整体失败：降级为带口径的模板文本，
        # 口径说明仍然在场。
        return _fake_interpret(question, views, result, audience=audience)
