"""结果解读：把结果集与原始问题一起送入模型，生成自然语言解读。

解读必须说明数据口径——同一个「收益率」在不同口径下是不同的数字，
只给结论不给口径会误导。因此无论真假 provider，视图的口径说明都
进入解读：fake provider 直接引用，真实 provider 在提示词中被要求
复述口径。
"""

from app.analytics.catalog import ViewSpec
from app.analytics.execution import QueryResult
from app.exceptions import AppError
from app.llm.provider import chat_completion
from app.settings import Settings

SYSTEM_PROMPT = (
    "你是数据分析 Agent 的结果解读器。根据员工的原始问题、查询结果与语义视图的"
    "口径说明，用两到四句中文解读这些数字意味着什么。硬性规则：必须明确说明数据"
    "口径（统计范围与字段定义），不得给出投资建议或收益预测，不得编造结果中不存"
    "在的数字。"
)


def generate_interpretation(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    settings: Settings,
) -> str:
    if settings.resolved_llm_provider == "fake":
        return _fake_interpret(question, views, result)
    return _openai_compatible_interpret(question, views, result, settings)


def _basis_text(views: list[ViewSpec]) -> str:
    return "；".join(view.summary for view in views)


def _fake_interpret(
    question: str, views: list[ViewSpec], result: QueryResult
) -> str:
    truncated_note = "，结果超出行数上限已截断" if result.truncated else ""
    return (
        f"问题「{question}」的查询共返回 {len(result.rows)} 行{truncated_note}。"
        f"数据口径：{_basis_text(views)}"
    )


def _openai_compatible_interpret(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    settings: Settings,
) -> str:
    rows_preview = "\n".join(
        ", ".join(str(value) for value in row) for row in result.rows[:20]
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
        return _fake_interpret(question, views, result)
