"""客户侧数据解读只说行数、截断与口径，不念逐行数据，也不编造没查到的数字。

自 ADR-0028 起，客户侧文本与结果表分工：逐行数据由随回答送达的结果表承载，文本
负责回答「这些数字是怎么来的」。模型解读会把口径说明里的字段名写成具体数字（例如
没查到的风险承受等级和有效期），因此客户侧无论 provider 都不经过模型。
"""

from app.agent.config import CUSTOMER_SERVICE_VIEW_NAMES
from app.agent.graph import customer_data_answer
from app.analytics.audience import Audience
from app.analytics.catalog import ViewSpec, select_views
from app.analytics.execution import QueryResult
from app.analytics.interpretation import generate_interpretation
from app.llm import provider as llm_provider
from app.replay import library as replay_library
from app.settings import get_settings


def _customer_views() -> list[ViewSpec]:
    return select_views(
        "有什么适合我的风险等级的产品", allowed=CUSTOMER_SERVICE_VIEW_NAMES
    )


def test_customer_interpretation_states_rows_and_basis_without_reciting_them(
    monkeypatch,
):
    def _fail(*args, **kwargs):
        raise AssertionError("客户侧解读不应调用模型")

    monkeypatch.setattr(llm_provider, "chat_completion", _fail)
    settings = get_settings().model_copy(
        update={"llm_provider": "openai_compatible", "llm_api_key": "test-key"}
    )
    rows = [
        [f"P{index:03d}", f"产品{index}", "R1" if index < 15 else "R2"]
        for index in range(30)
    ]
    result = QueryResult(
        columns=["product_code", "product_name", "risk_level"],
        rows=rows,
        truncated=False,
    )

    answer = generate_interpretation(
        "有什么适合我的风险等级的产品",
        _customer_views(),
        result,
        settings,
        audience=Audience.CUSTOMER,
    )

    assert "为您查到 30 行数据，已列在下表" in answer
    assert "口径" in answer
    # 逐行明细与低基数列计数都不再进文本：表格是数据的唯一出处。
    assert "P000" not in answer and "P029" not in answer
    assert "R1 15 行" not in answer and "R2 15 行" not in answer
    for column in result.columns:
        assert f"{column} 为 " not in answer
    # 结果里没有的东西一个也不许出现——这正是客户侧不走模型的原因。
    assert "风险承受等级C1" not in answer
    assert "有效期至20" not in answer
    assert "24 行" not in answer
    assert "6 行" not in answer


def test_customer_interpretation_flags_truncation_next_to_the_row_count():
    settings = get_settings().model_copy(update={"llm_provider": "fake"})
    result = QueryResult(
        columns=["product_code"],
        rows=[["P000"], ["P001"]],
        truncated=True,
    )

    answer = generate_interpretation(
        "我持有哪些产品",
        _customer_views(),
        result,
        settings,
        audience=Audience.CUSTOMER,
    )

    assert "为您查到 2 行数据（结果超出行数上限，已截断），已列在下表" in answer


def test_replay_does_not_hand_the_preset_interpretation_to_customers():
    """回放模式下客户不采信预置解读，员工口径不受影响（ADR-0028 决定 5）。

    预置解读是员工口吻，且会写出内部视图名（「语义视图 va_product_element」）；它的
    目标视图同时在客户候选集里，因此客户侧继续采信它就会留下「客户能读到内部视图名」
    的实例。`ANALYTICS_PRESETS[0]` 的 SQL 照旧使用——确定性不丢，丢的只是那段文本。

    客户侧要走的是「确定性模板 + 结果表」：这两样在客服图上由两个函数产出（解读与
    客户契约），预置问题本身在客服图里落到知识检索（它不含第一人称的数据问法），
    因此这条断言钉在这两个出口上，而不是绕一圈从 HTTP 进去。
    """
    preset = replay_library.ANALYTICS_PRESETS[0]
    views = select_views(preset.question, allowed=CUSTOMER_SERVICE_VIEW_NAMES)
    assert "va_product_element" in {view.name for view in views}, (
        "预置的目标视图若不在客户候选集里，这条用例就失去意义"
    )
    result = QueryResult(
        columns=["risk_level", "product_count"],
        rows=[["R1", 3], ["R2", 1]],
        truncated=False,
    )
    settings = get_settings().model_copy(update={"demo_replay": True})

    customer_answer = generate_interpretation(
        preset.question, views, result, settings, audience=Audience.CUSTOMER
    )

    assert customer_answer != preset.interpretation
    assert "va_" not in customer_answer
    assert "产品要素" in customer_answer  # 中文视图名仍在，口径照给
    assert "为您查到 2 行数据，已列在下表" in customer_answer

    table = customer_data_answer(views, result)
    assert set(table.views) == {"产品要素", "风险承受等级"}
    assert "customer_id" not in [column.key for column in table.columns]

    # 员工侧不受影响：同一次回放里，员工拿到的仍是预写解读。
    assert (
        generate_interpretation(
            preset.question, views, result, settings, audience=Audience.EMPLOYEE
        )
        == preset.interpretation
    )
