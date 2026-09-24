"""智能客服的数据查询分支：客户用自己的名义查自己的数据（ADR-0025）。

Seam：后端 HTTP 层（``POST /api/customer/chat/messages``），模型走 fake provider——
查询由示例（或测试注册的 `register_fake_query`）给定，因此这里验证的是**分支与
出口**，不是模型乖。

要成立的三件事：查得到（只出自己的行、数字进解读文本）、三种出口彼此可区分
（失败/超时是降级、白名单外是边界、零行是事实），以及越界的两条线（员工侧的
视图不在候选集里、另一位客户的行查不到）。执行账号的行级范围另有
``test_semantic_views.py`` 专测，这里测的是客户从对话里实际看得到什么。
"""

from collections.abc import Iterator

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

import app.agent.graph as agent_graph
from app import degradation
from app.analytics import llm as analytics_llm
from app.analytics.errors import QUERY_TIMEOUT_CODE
from app.db.analytics_account import setup_analytics_account
from app.db.models import AgentDebugTrace, DegradationTrace
from app.main import app
from app.settings import Settings, get_settings

# 种子里两位客户的风险承受等级不同，恰好用来看产品筛选的两面：C1 只筛得出 R1，
# C2 筛得出 R1/R2——两个等级才看得出「只按产品代码排序」。
CUSTOMER = "wangc1"
WIDER_CUSTOMER = "lisic2"
SEEDED_PASSWORD = "Test@1234"

HOLDINGS_QUESTION = "我持有哪些产品"
FOLLOW_UP_QUESTION = "这个月转了多少"
OUT_OF_SCOPE_QUESTION = "我的画像标签是什么"
PRODUCT_QUESTION = "有什么适合我的风险等级的产品"

# 兜底回答的标记：数据查询的任何一条出口都不该长成知识库兜底的样子。
FALLBACK_MARKERS = ("人工客服", "95588")


@pytest.fixture(scope="module")
def _analytics_account(_test_database_ready: None) -> None:
    # 受限执行账号的创建与授权需要 root，且要求视图已存在（迁移之后）。
    setup_analytics_account(get_settings().test_database_url)


@pytest.fixture
def chat_client(
    auth_client: TestClient, _analytics_account: None
) -> Iterator[TestClient]:
    _pin_settings(
        milvus_collection=get_settings().test_milvus_collection,
        embedding_api_key="",
        llm_provider="fake",
        llm_api_key="",
        # 数据查询分支不连 Neo4j；用一个从不重建的命名空间，免得与别的测试模块
        # 共享默认命名空间时互相影响。
        neo4j_graph_namespace="wealth_test_customer_data_query_unused",
    )
    analytics_llm.clear_fake_queries()
    try:
        yield auth_client
    finally:
        app.dependency_overrides.pop(get_settings, None)
        analytics_llm.clear_fake_queries()


def _pin_settings(**overrides) -> Settings:
    settings = get_settings().model_copy(update=overrides)
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _login(client: TestClient, username: str = CUSTOMER) -> tuple[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["access_token"]
    session_id = pyjwt.decode(token, options={"verify_signature": False})["sid"]
    return token, session_id


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _chat(client: TestClient, token: str, message: str) -> dict:
    response = client.post(
        "/api/customer/chat/messages",
        headers=_headers(token),
        json={"message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _holding_codes(client: TestClient, username: str) -> set[str]:
    """客户的持仓产品代码，取自客户自己的资产接口——答案该对得上这组代码。"""
    response = client.get("/api/customer/assets", headers=_headers(_login(client, username)[0]))
    assert response.status_code == 200, response.text
    return {holding["product_code"] for holding in response.json()["data"]["holdings"]}


def _data_query_material(session_id: str) -> dict:
    """这一场会话里数据查询留下的调试级材料：查询语句、命中的视图、行数。"""
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            rows = list(
                session.scalars(
                    select(AgentDebugTrace)
                    .where(
                        AgentDebugTrace.session_id == session_id,
                        AgentDebugTrace.data_query.is_not(None),
                    )
                    .order_by(AgentDebugTrace.id.desc())
                )
            )
    finally:
        engine.dispose()
    assert rows, "数据查询分支应当留下一条带查询材料的调试级留痕"
    return rows[0].data_query


def _data_query_sql(session_id: str) -> str:
    sql = _data_query_material(session_id).get("sql")
    assert sql, "这一轮的查询材料里应当有实际执行过的语句"
    return sql


def _degradation_rows(trace_id: str) -> list[DegradationTrace]:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            return list(
                session.scalars(
                    select(DegradationTrace).where(
                        DegradationTrace.trace_id == trace_id
                    )
                )
            )
    finally:
        engine.dispose()


# ---- 查得到：只出自己的行，数字进文本 -----------------------------------------


def test_customer_asks_for_own_holdings_and_gets_her_own_numbers(
    chat_client: TestClient, monkeypatch
):
    """「我持有哪些产品」得到的是本人持仓的文本，且全程不碰知识检索。

    把检索入口换成必炸的替身：数据查询若悄悄退到知识库，这条用例会当场失败。
    """

    def _fail(*args, **kwargs):
        raise AssertionError("数据查询分支不应触发知识检索")

    monkeypatch.setattr(agent_graph, "search_chunks", _fail)

    mine = _holding_codes(chat_client, CUSTOMER)
    foreign = _holding_codes(chat_client, WIDER_CUSTOMER) - mine
    assert mine, "种子数据里这位客户应当有持仓"
    assert foreign, "另一位客户该持有本人没有的产品，否则「只出自己的行」无从验证"

    token, session_id = _login(chat_client)
    data = _chat(chat_client, token, HOLDINGS_QUESTION)

    assert data["intent"] == "数据查询"
    # 数据回答的依据是查询本身，不是知识库文档：没有引用角标可言。
    assert data["citations"] == []
    # 只筛不排序的事实性内容，不附投顾免责声明。
    assert data["content_classification"] == "事实性内容"
    for code in mine:
        assert code in data["answer"], "自己的持仓必须在回答里"
    for code in foreign:
        assert code not in data["answer"], "别人的持仓不该出现在回答里"
    # 数字直接写进文本（Q5A），而不是只回一句「已为您查询」。
    assert any(character.isdigit() for character in data["answer"])
    # 查询本身进调试级留痕：事后能回答「系统当时查了什么、取回几行」。
    material = _data_query_material(session_id)
    assert material["views"] == ["va_my_holdings"]
    assert material["row_count"] == len(mine)
    assert material["error_code"] is None
    assert "va_my_holdings" in material["sql"]


def test_follow_up_question_continues_the_same_session(chat_client: TestClient):
    """「这个月转了多少」能接上，是因为上一轮的提问进了选视图与生成上下文。"""
    # 同一场登录的两问共用一个会话；这条追问本身只带「转」，靠上一轮的提问补语境。
    token, session_id = _login(chat_client)
    analytics_llm.register_fake_query(
        FOLLOW_UP_QUESTION,
        "SELECT transaction_no, transaction_type, amount, traded_at"
        " FROM va_my_transactions ORDER BY traded_at",
    )

    first = _chat(chat_client, token, HOLDINGS_QUESTION)
    second = _chat(chat_client, token, FOLLOW_UP_QUESTION)

    assert first["intent"] == "数据查询"
    assert second["intent"] == "数据查询"
    call = analytics_llm.fake_generation_calls[-1]
    assert call.question == FOLLOW_UP_QUESTION
    assert any(
        message["role"] == "user" and message["content"] == HOLDINGS_QUESTION
        for message in call.history
    ), "上一轮的提问必须进生成上下文"
    assert {"va_my_transactions", "va_my_holdings"} <= set(call.view_names), (
        "上一轮的提问也要进选视图的语境，否则追问可能连候选视图都没有"
    )
    assert "没有查到" not in second["answer"]
    assert session_id


# ---- 三种出口彼此可区分 -------------------------------------------------------


def test_question_outside_the_whitelist_gets_the_boundary_message(
    chat_client: TestClient, monkeypatch
):
    """白名单外明确告知不在可查范围并列出能查什么——不是知识库兜底答案。"""

    def _fail(*args, **kwargs):
        raise AssertionError("越界的问题不该退到知识检索")

    monkeypatch.setattr(agent_graph, "search_chunks", _fail)

    token, _ = _login(chat_client)
    data = _chat(chat_client, token, OUT_OF_SCOPE_QUESTION)

    assert data["intent"] == "数据查询"
    assert data["citations"] == []
    assert data["answer"] == agent_graph.data_query_out_of_scope_message()
    # 列出可查什么：清单由视图目录生成，白名单改了它跟着改。
    for topic in ("持仓明细", "交易流水", "资金账户余额", "风险承受等级", "产品要素"):
        assert topic in data["answer"]
    for marker in FALLBACK_MARKERS:
        assert marker not in data["answer"]


def test_employee_side_views_are_not_in_the_customer_candidate_set(
    chat_client: TestClient,
):
    """员工侧的预警统计不在客户候选集：客户问它得到的是边界话术。"""
    token, _ = _login(chat_client)

    data = _chat(chat_client, token, "我的账户有没有风控预警")

    assert data["intent"] == "数据查询"
    assert data["answer"] == agent_graph.data_query_out_of_scope_message()


def test_zero_rows_answers_the_fact_while_failure_answers_the_degradation(
    chat_client: TestClient,
):
    """零行与失败必须分得开：前者是事实（如实说没有），后者是降级（并留痕）。"""
    token, session_id = _login(chat_client)
    zero_row_question = "我的风险承受等级是什么"
    analytics_llm.register_fake_query(
        zero_row_question, "SELECT risk_level FROM va_my_risk_assessment WHERE 1 = 0"
    )

    data = _chat(chat_client, token, zero_row_question)

    assert data["intent"] == "数据查询"
    assert data["answer"] == agent_graph.DATA_QUERY_EMPTY_MESSAGE
    # 零行不是降级：这一轮正常作答，没有降级留痕。
    assert data["degraded"] is False
    assert _degradation_rows(data["trace_id"]) == []
    assert session_id


def test_failed_query_degrades_with_a_trace_and_never_falls_back(
    chat_client: TestClient,
):
    """查询超时 → 固定话术 + 降级留痕；回答里没有半点知识库内容。"""
    _pin_settings(
        milvus_collection=get_settings().test_milvus_collection,
        embedding_api_key="",
        llm_provider="fake",
        llm_api_key="",
        neo4j_graph_namespace="wealth_test_customer_data_query_unused",
        analytics_query_timeout_ms=300,
    )
    question = "我的持仓明细"
    # 重型笛卡尔积：超过 max_execution_time 时被 MySQL 打断（ER_QUERY_TIMEOUT）。
    analytics_llm.register_fake_query(
        question,
        "SELECT COUNT(*) FROM information_schema.columns a"
        " JOIN information_schema.columns b"
        " JOIN information_schema.columns c"
        " JOIN information_schema.columns d",
    )
    token, session_id = _login(chat_client)

    data = _chat(chat_client, token, question)

    assert data["intent"] == "数据查询"
    assert data["answer"] == agent_graph.DATA_QUERY_FAILURE_MESSAGE
    assert data["degraded"] is True
    for marker in FALLBACK_MARKERS:
        assert marker not in data["answer"]
    rows = _degradation_rows(data["trace_id"])
    assert [row.dependency for row in rows] == [degradation.DEPENDENCY_DATA_QUERY]
    assert rows[0].reason == degradation.REASON_TIMEOUT
    assert rows[0].agent_type == "customer_service"
    # 失败的这一轮同样留下查询材料，错误码与降级那条对得上。
    assert _data_query_material(session_id)["error_code"] == QUERY_TIMEOUT_CODE


# ---- 高风险意图识别：数据查询的问题照常过它 ------------------------------------


def test_a_data_query_question_still_feeds_the_high_risk_intent_path(
    chat_client: TestClient,
):
    """分支选择与高风险意图识别互不相干：一句既查数据又露苗头的话，两件事都发生。"""
    token, _ = _login(chat_client)
    customer_id = int(pyjwt.decode(token, options={"verify_signature": False})["sub"])
    # 关注记录是共享表：别的用例也会为这位客户留下记录，因此比的是**增量**。
    before = _focus_reasons(chat_client, customer_id)

    data = _chat(chat_client, token, "我持有的产品怎么操作可以规避限额")

    # 它先是数据查询（走的是分析链路，不是检索）……
    assert data["intent"] == "数据查询"
    # ……同时照常被高风险意图识别看见，风控侧因此多出一条关注记录。
    reasons = _focus_reasons(chat_client, customer_id)
    assert len(reasons) == len(before) + 1
    assert "转账限额" in reasons[-1]


def _focus_reasons(client: TestClient, customer_id: int) -> list[str]:
    """风控侧为这位客户写下的高风险意图关注理由（经风控专员自己的列表读）。"""
    login = client.post(
        "/api/internal/auth/login",
        json={"username": "risk1", "password": SEEDED_PASSWORD},
    )
    response = client.get(
        "/api/internal/risk-focus",
        headers={"Authorization": f"Bearer {login.json()['data']['access_token']}"},
    )
    assert response.status_code == 200, response.text
    # 列表按时间倒序：最后一条就是这一次新写下的那条。
    return [
        item["reason"]
        for item in reversed(response.json()["data"]["items"])
        if item["customer_id"] == customer_id and item["focus_type"] == "高风险意图"
    ]


# ---- 产品筛选：Cn 筛 R1–Rn，只筛不排序 ----------------------------------------


def test_product_screening_filters_by_own_level_and_sorts_by_product_code_only(
    chat_client: TestClient,
):
    """按自己的风险等级筛产品、只按产品代码排序、不含任何推荐话术。"""
    token, session_id = _login(chat_client, WIDER_CUSTOMER)
    holdings_before = _holding_codes(chat_client, WIDER_CUSTOMER)

    data = _chat(chat_client, token, PRODUCT_QUESTION)

    assert data["intent"] == "数据查询"
    assert data["content_classification"] == "事实性内容"
    sql = _data_query_sql(session_id).lower()
    assert "risk_level" in sql, "按等级筛是这条路径的机制前提"
    assert sql.count("order by") == 1 and "product_code" in sql.split("order by")[1]
    assert "desc" not in sql, "只筛不排序：不许按收益、费率或等级排序"
    # C2 看得到 R1 与 R2 两档，且按产品代码的先后出现——排序键就是产品代码。
    answer = data["answer"]
    assert "F000001" in answer and "F000002" in answer
    assert answer.index("F000001") < answer.index("F000002")
    for wording in ("推荐", "建议", "更适合", "最优"):
        assert wording not in answer
    # 这条路径是只读的：问过产品不会改变客户的持仓。
    assert _holding_codes(chat_client, WIDER_CUSTOMER) == holdings_before
