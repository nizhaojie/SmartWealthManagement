"""员工侧解读的两条落点：**0 行不给结论**，**样例行逐行对齐**。

复现的误答（2026-09-27，真实 provider + 真实库）：数据分析里问「客户王守成的持仓情况」，
系统答「客户王守成当前无任何持仓记录，资产规模为 0」，而王守成名下确有一笔持仓
（天枢货币基金，市值 20420）。

成因两层，各自独立：

1. 提问里的全名与视图里存的值对不上（当时存的是脱敏值「王**」），生成的等值比较恒 0 行。
   那一半由 ADR-0029 从**视图口径**上解决（员工侧客户概况给出实名，迁移 `0034`），
   本文件只钉住 catalog 必须如实写明这一点。
2. 0 行被交给模型解读，模型把它读成一个实质结论（「该客户无持仓」）。空结果没有任何可
   解读的内容，因此员工侧这一档不经过模型——这是本文件的第一条断言。

第三条断言针对另一处实测缺陷：样例行原先串成一整段「列 为 值，列 为 值；……」，三行
持仓的解读里出现过「把客户 3 的 108000 说成客户 1 的市值、把客户 1 的 20420 说成客户 2
的」。样例行因此改成逐行对齐的表格，跨行取值的空间由断言挡着。
"""

from app.analytics import interpretation as interpretation_module
from app.analytics.audience import Audience
from app.analytics.catalog import EMPLOYEE_VIEW_CATALOG, select_views
from app.analytics.execution import QueryResult
from app.analytics.interpretation import generate_interpretation
from app.settings import get_settings


def _views():
    return select_views("客户持仓", allowed=[spec.name for spec in EMPLOYEE_VIEW_CATALOG])


def _real_provider_settings():
    return get_settings().model_copy(
        update={"llm_provider": "openai_compatible", "llm_api_key": "test-key"}
    )


def test_an_empty_result_is_never_handed_to_the_model(monkeypatch):
    """0 行不走模型：它没有可解读的内容，而模型会把它说成「该客户没有持仓」。"""

    def _fail(*args, **kwargs):
        raise AssertionError("0 行不应交给模型解读")

    monkeypatch.setattr(interpretation_module, "chat_completion", _fail)
    result = QueryResult(columns=["customer_id", "customer_name"], rows=[], truncated=False)

    answer = generate_interpretation(
        "客户王守成的持仓情况",
        _views(),
        result,
        _real_provider_settings(),
        audience=Audience.EMPLOYEE,
    )

    assert "没有查到符合条件的数据（共 0 行）" in answer
    # 空结果只是一个「没匹配到」的信号，不是一个关于客户的结论。
    assert "空结果只说明没有匹配到行" in answer
    # 口径照给：员工要靠它换一个能匹配到行的问法。
    assert "口径" in answer


def test_a_result_with_rows_still_goes_to_the_model(monkeypatch):
    """有一条前提得钉住：上面那档只针对 0 行，有行时解读仍由模型措辞。"""
    calls: list[list[dict]] = []

    def _capture(messages, settings):
        calls.append(messages)
        return "解读"

    monkeypatch.setattr(interpretation_module, "chat_completion", _capture)
    result = QueryResult(
        columns=["customer_id", "customer_name"],
        rows=[[1, "王守成"]],
        truncated=False,
    )

    answer = generate_interpretation(
        "客户王守成的持仓情况",
        _views(),
        result,
        _real_provider_settings(),
        audience=Audience.EMPLOYEE,
    )

    assert answer == "解读"
    assert len(calls) == 1


def test_the_row_preview_is_a_table_so_values_cannot_cross_rows(monkeypatch):
    """样例行逐行对齐：串成一整段时，模型会把某一行的数字写到另一行上。"""
    captured: list[list[dict]] = []

    def _capture(messages, settings):
        captured.append(messages)
        return "解读"

    monkeypatch.setattr(interpretation_module, "chat_completion", _capture)
    result = QueryResult(
        columns=["customer_id", "customer_name", "current_value"],
        rows=[[1, "王守成", 20420.0], [2, "李思远", 52000.0], [3, "张衡", 108000.0]],
        truncated=False,
    )

    generate_interpretation(
        "我名下客户的持仓情况",
        _views(),
        result,
        _real_provider_settings(),
        audience=Audience.EMPLOYEE,
    )

    prompt = captured[0][-1]["content"]
    table = [line for line in prompt.splitlines() if line.startswith("| ")]
    assert table[0] == "| customer_id | customer_name | current_value |"
    assert table[1] == "| --- | --- | --- |"
    # 每位客户自己的三个值落在同一行上，一位客户一行——不串行。
    assert table[2] == "| 1 | 王守成 | 20420.0 |"
    assert table[3] == "| 2 | 李思远 | 52000.0 |"
    assert table[4] == "| 3 | 张衡 | 108000.0 |"


def test_the_view_documents_that_customer_name_is_the_real_name():
    """口径里必须写明姓名是实名（ADR-0029）。

    退回「脱敏」口径，生成侧就会重新拿客户全名去比一个存着「王**」的列——恒 0 行，
    而 0 行曾经被读成「该客户没有持仓」。
    """
    spec = next(s for s in EMPLOYEE_VIEW_CATALOG if s.name == "va_customer_overview")

    assert "customer_name 是客户实名" in spec.summary
    assert "脱敏" not in spec.summary


def test_every_scoped_employee_view_says_the_row_scope_is_already_built_in():
    """口径里必须写明行级范围已内建。

    只注入与问题相关的那几张视图，模型看不到别的视图的说明；少了这一句，它会去手上这张
    视图里找一个能表达「我的客户」的列，找不到就判「超出可查范围」——实测的
    「查询我名下客户的持仓情况」正是这样答成 1101 的。
    """
    scoped = {
        spec.name: spec.summary
        for spec in EMPLOYEE_VIEW_CATALOG
        if spec.name != "va_product_element"  # 产品主数据没有行级过滤要声明
    }

    assert set(scoped) == {
        "va_customer_overview",
        "va_holding_distribution",
        "va_transaction_stat",
        "va_risk_alert_stat",
    }
    for name, summary in scoped.items():
        assert "行级范围已内建" in summary, f"{name} 没说行级范围已内建"
