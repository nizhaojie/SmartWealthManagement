"""结果解读：员工侧把结果集与原始问题送入模型；客户侧由结果集直接生成。

解读必须说明数据口径——同一个「收益率」在不同口径下是不同的数字，
只给结论不给口径会误导。因此无论真假 provider，视图的口径说明都
进入解读：fake provider 直接引用，真实 provider 在提示词中被要求
复述口径。

解读按使用者口径分两套（ADR-0025）：员工侧是内部研判，客户侧是**面向本人的
事实陈述**。两者差在说话对象与边界上——客户那一套不许出现投资建议、收益预测与
产品推荐（只筛不排序的产品清单才轮得到客服说，见 ADR-0005）。

客户侧不把解读交给模型。模型会把视图说明里的字段名写成具体数字（例如没查到的
风险承受等级和有效期），也会只看见一部分行就给全体计数。客户看到的句子由结果集
直接生成，且自 ADR-0028 起只留**行数、截断与口径**：逐行数据与低基数列计数都从
文本里去掉，它们由随回答一起送达的结果表承载——表格是数据的唯一出处，文本负责
回答「这些数字是怎么来的」。逐行与计数的两个函数因此仍留给员工侧与模型路径。
"""

from collections import Counter
from decimal import Decimal

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
    "在的数字。解读必须逐行对应：每个数字都要说清它出自哪一行（哪一位客户、哪个"
    "产品），不得把某一行的数字写到另一行上。"
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

# 员工侧 0 行的解读不走模型：模型会把「没匹配到行」读成一个实质结论（「该客户当前无
# 任何持仓记录」），那是一个假事实，而不只是一句空话。0 行的成因是筛选条件与视图的
# 口径或行级范围对不上——问了别人名下的客户、用了口径外的枚举值、字段名存的是别的
# 形态。因此这里把它当作「换个口径再问」的提示来给，并把口径说明原样附上。
_EMPTY_RESULT_MESSAGE = (
    "本次查询没有查到符合条件的数据（共 0 行）。数据口径：{basis}。"
    "空结果只说明没有匹配到行，它不是「没有这项数据」的结论，"
    "请对照上面的口径检查筛选条件。"
)

# 一列取值种类不超过这个数时，把每种取值的行数写进解读。产品代码这类高基数列
# 不计数，避免一句解读变成第二张宽表；它们的原值仍逐行出现。
_COUNT_CARDINALITY_LIMIT = 12
# 员工侧仍由模型措辞，但只把这么多行原文放进提示词。完整计数另附，模型不得
# 凭这段样例给全体重新计数。
_ROW_PREVIEW_LIMIT = 20


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
        # 预置解读是员工口吻，且会写出内部视图名（「语义视图 va_product_element」）——
        # 客户侧不采信它，一律走确定性模板（ADR-0028）；预置 SQL 照旧使用。
        if preset is not None and audience == Audience.EMPLOYEE:
            return preset.interpretation
        return _fake_interpret(question, views, result, audience=audience)
    if audience == Audience.EMPLOYEE and not result.rows:
        return _empty_result_interpret(views)
    if audience == Audience.CUSTOMER or settings.resolved_llm_provider == "fake":
        return _fake_interpret(question, views, result, audience=audience)
    return _openai_compatible_interpret(question, views, result, settings, audience)


def _empty_result_interpret(views: list[ViewSpec]) -> str:
    """0 行的确定性解读：不给结论，只给「没匹配到」与口径（见 _EMPTY_RESULT_MESSAGE）。"""
    return _EMPTY_RESULT_MESSAGE.format(basis=_basis_text(views))


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


def _cell_text(value: object) -> str:
    if value is None:
        return "空"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _column_counts(result: QueryResult) -> str:
    """低基数列的完整计数。用全部行，不用送进模型的那一段样例。"""
    parts: list[str] = []
    for index, column in enumerate(result.columns):
        values = [_cell_text(row[index]) for row in result.rows]
        distinct = set(values)
        if len(distinct) == 1 and len(values) > 1:
            parts.append(f"{column}全部为 {values[0]}，共 {len(values)} 行")
            continue
        if not 1 < len(distinct) <= _COUNT_CARDINALITY_LIMIT:
            continue
        counts = Counter(values)
        listed = "、".join(
            f"{value} {counts[value]} 行"
            for value in sorted(counts, key=lambda item: (-counts[item], item))
        )
        parts.append(f"按{column}：{listed}")
    return "。".join(parts)


def _row_table(result: QueryResult, *, limit: int | None = None) -> str:
    """样例行按表格给出，一行一行对齐。

    原先把它串成一整段「列 为 值，列 为 值；……」：列名与值在同一句里交错，模型会把
    某一行的数字读到另一行上（2026-09-27 实测：三行持仓里把客户 3 的 108000 说成客户
    1 的市值、客户 1 的 20420 说成客户 2 的）。表格把行边界与列边界都摆成显式的，
    跨行取值的空间因此被压掉一大半；剩下的那半由提示词里的「逐行对应」兜着。
    """
    rows = result.rows if limit is None else result.rows[:limit]
    lines = [
        "| " + " | ".join(result.columns) + " |",
        "| " + " | ".join("---" for _ in result.columns) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_cell_text(value) for value in row) + " |" for row in rows
    )
    return "\n".join(lines)


def _fake_customer_interpret(views: list[ViewSpec], result: QueryResult) -> str:
    """客户口径的确定性解读：只说行数、截断与口径。

    客户侧无论 provider 都走这里。模型解读会把口径说明里的字段名写成具体数字，
    也会只看见一部分行就给全体计数；这两件事都违反「不得编造结果中不存在的数字」。

    逐行数据不在这里念：客户侧的结果表随回答一起送达（ADR-0028），表格是数据的
    唯一出处，文本只回答「这些数字是怎么来的」。`_row_table` 与 `_column_counts`
    因此只服务员工侧与模型路径，不在这条出口上调用。
    """
    truncated_note = "（结果超出行数上限，已截断）" if result.truncated else ""
    return (
        f"为您查到 {len(result.rows)} 行数据{truncated_note}，已列在下表。"
        f"数据口径：{_basis_text(views)}"
    )


def _openai_compatible_interpret(
    question: str,
    views: list[ViewSpec],
    result: QueryResult,
    settings: Settings,
    audience: Audience,
) -> str:
    preview = _row_table(result, limit=_ROW_PREVIEW_LIMIT)
    omitted = max(len(result.rows) - _ROW_PREVIEW_LIMIT, 0)
    counts = _column_counts(result)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPTS[audience]},
        {
            "role": "user",
            "content": (
                f"原始问题：{question}\n\n"
                f"视图口径说明：{_basis_text(views)}\n\n"
                f"结果列：{', '.join(result.columns)}\n"
                f"结果共 {len(result.rows)} 行"
                f"{'，已截断' if result.truncated else ''}。\n"
                f"已核算的列计数（以此为准，不要根据样例重新计数）：{counts or '无'}\n"
                f"样例行（表格一行对应结果里的一行，共列出前 {_ROW_PREVIEW_LIMIT} 行，"
                f"其余 {omitted} 行未列出）：\n{preview}\n"
                "只使用结果列里出现过的字段，并逐行对应：每个数字都要说清它出自哪一行，"
                "不得把某一行的数字写到另一行上。结果里没有的客户风险承受等级、有效期等不要写。"
            ),
        },
    ]
    try:
        return chat_completion(messages, settings).strip()
    except AppError:
        # 解读失败不应让一次成功的查询整体失败：降级为带口径的模板文本，
        # 口径说明仍然在场。
        return _fake_interpret(question, views, result, audience=audience)
