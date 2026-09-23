"""数据分析 Agent：结果解读、内容分类与免责声明、多轮追问、历史与示例。

Seam：后端 HTTP 层。模型走 fake provider——解读文本是确定性的，
测试验证的是链路把「结果集 + 原始问题 + 视图口径」送进了生成，并把
解读、分类与免责声明组装进响应。
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.analytics import llm as analytics_llm
from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

HOLDING_QUESTION = "各产品类型的持仓市值分布"
HOLDING_SQL = (
    "SELECT product_type, SUM(current_value) AS total_value"
    " FROM va_holding_distribution GROUP BY product_type ORDER BY total_value DESC"
)


@pytest.fixture(scope="module")
def _analytics_account(_test_database_ready: None) -> None:
    from app.db.analytics_account import setup_analytics_account

    setup_analytics_account(get_settings().test_database_url)


@pytest.fixture
def analytics_client(
    auth_client: TestClient, _analytics_account: None
) -> Iterator[TestClient]:
    test_settings = get_settings().model_copy(
        update={"llm_provider": "fake", "llm_api_key": ""}
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    analytics_llm.clear_fake_queries()
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)
        analytics_llm.clear_fake_queries()


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _ask(
    client: TestClient,
    headers: dict[str, str],
    question: str,
    session_id: str | None = None,
):
    body: dict = {"question": question}
    if session_id is not None:
        body["session_id"] = session_id
    return client.post("/api/internal/analytics/query", headers=headers, json=body)


def test_successful_query_comes_with_an_interpretation_stating_the_basis(
    analytics_client: TestClient,
):
    headers = _employee_headers(analytics_client, "advisor1")

    response = _ask(analytics_client, headers, HOLDING_QUESTION)

    assert response.status_code == 200
    data = response.json()["data"]
    # 结果不只是一张表：解读与结果同时返回。
    assert data["columns"] == ["product_type", "total_value"]
    interpretation = data["interpretation"]
    assert interpretation
    # 解读必须说明数据口径——视图的口径说明进入解读文本。
    assert "口径" in interpretation


def test_report_class_output_carries_a_template_disclaimer(
    analytics_client: TestClient,
):
    # 面向客户的报告类输出（财富报告 / 研报 / 行业分析）按投顾内容对待，
    # 免责声明由模板附加，不依赖模型记得写。
    question = "给我一份各产品类型持仓市值分布的财富报告"
    analytics_llm.register_fake_query(question, HOLDING_SQL)
    headers = _employee_headers(analytics_client, "advisor1")

    response = _ask(analytics_client, headers, question)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["content_classification"] == "投顾内容"
    assert data["disclaimer"]
    assert "不构成任何直接投资建议" in data["disclaimer"]


def test_plain_internal_query_has_no_disclaimer(analytics_client: TestClient):
    headers = _employee_headers(analytics_client, "advisor1")

    response = _ask(analytics_client, headers, HOLDING_QUESTION)

    assert response.status_code == 200
    data = response.json()["data"]
    # 纯内部数据查询是事实性内容，不附免责声明。
    assert data["content_classification"] == "事实性内容"
    assert data["disclaimer"] is None


def test_follow_up_question_sees_the_previous_turn(analytics_client: TestClient):
    # 多轮追问：「那上个季度呢」能成立，是因为上一轮问题进入了生成上下文。
    headers = _employee_headers(analytics_client, "advisor1")
    session_id = f"analytics-test-{uuid4().hex[:8]}"
    follow_up = "那上个季度呢"
    analytics_llm.register_fake_query(follow_up, HOLDING_SQL)

    first = _ask(analytics_client, headers, HOLDING_QUESTION, session_id)
    assert first.json()["code"] == 200
    response = _ask(analytics_client, headers, follow_up, session_id)

    assert response.status_code == 200
    assert response.json()["code"] == 200
    call = analytics_llm.fake_generation_calls[-1]
    assert call.question == follow_up
    assert any(
        message["role"] == "user" and message["content"] == HOLDING_QUESTION
        for message in call.history
    )


def test_query_without_session_starts_without_history(analytics_client: TestClient):
    headers = _employee_headers(analytics_client, "advisor1")

    response = _ask(analytics_client, headers, HOLDING_QUESTION)

    assert response.status_code == 200
    assert analytics_llm.fake_generation_calls[-1].history == []


# ---- 历史查询：可查看、可重用 -------------------------------------------------


def test_history_lists_the_employees_own_past_queries(analytics_client: TestClient):
    question = f"持仓历史查询测试 {uuid4().hex[:8]}"
    analytics_llm.register_fake_query(question, HOLDING_SQL)
    headers = _employee_headers(analytics_client, "advisor1")
    asked = _ask(analytics_client, headers, question)
    assert asked.json()["code"] == 200

    response = analytics_client.get("/api/internal/analytics/history", headers=headers)

    assert response.status_code == 200
    entries = response.json()["data"]["items"]
    mine = [entry for entry in entries if entry["question"] == question]
    assert len(mine) == 1
    entry = mine[0]
    assert entry["sql"] == HOLDING_SQL
    assert entry["status"] == "成功"
    assert entry["row_count"] == asked.json()["data"]["row_count"]
    assert entry["truncated"] is False
    assert entry["create_time"]


def test_history_does_not_leak_other_employees_queries(analytics_client: TestClient):
    question = f"持仓历史隔离测试 {uuid4().hex[:8]}"
    analytics_llm.register_fake_query(question, HOLDING_SQL)
    advisor_headers = _employee_headers(analytics_client, "advisor1")
    asked = _ask(analytics_client, advisor_headers, question)
    assert asked.json()["code"] == 200

    manager_headers = _employee_headers(analytics_client, "manager1")
    response = analytics_client.get(
        "/api/internal/analytics/history", headers=manager_headers
    )

    assert response.status_code == 200
    questions = [entry["question"] for entry in response.json()["data"]["items"]]
    assert question not in questions


# ---- 示例问题 -----------------------------------------------------------------


def test_examples_endpoint_offers_the_configured_example_questions(
    analytics_client: TestClient,
):
    headers = _employee_headers(analytics_client, "advisor1")

    response = analytics_client.get("/api/internal/analytics/examples", headers=headers)

    assert response.status_code == 200
    questions = [item["question"] for item in response.json()["data"]]
    # 随仓库提供的示例问题让员工知道这个工具能回答什么。
    assert "资产规模超过一百万的客户有多少" in questions
    assert HOLDING_QUESTION in questions
