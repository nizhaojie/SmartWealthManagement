"""客户侧数据解读只转述查询结果，不把没查到的数字写进回答。"""

from app.analytics.audience import Audience
from app.analytics.catalog import CUSTOMER_VIEW_CATALOG
from app.analytics.execution import QueryResult
from app.analytics.interpretation import generate_interpretation
from app.llm import provider as llm_provider
from app.settings import get_settings


def test_customer_interpretation_counts_every_row_and_skips_the_model(monkeypatch):
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
    views = [
        view
        for view in CUSTOMER_VIEW_CATALOG
        if view.name in {"va_product_element", "va_my_risk_assessment"}
    ]

    answer = generate_interpretation(
        "有什么适合我的风险等级的产品",
        views,
        result,
        settings,
        audience=Audience.CUSTOMER,
    )

    assert "为您查到 30 行数据" in answer
    assert "R1 15 行" in answer
    assert "R2 15 行" in answer
    assert "P000" in answer and "P029" in answer
    assert "风险承受等级C1" not in answer
    assert "有效期至20" not in answer
    assert "24 行" not in answer
    assert "6 行" not in answer
    assert "口径" in answer
