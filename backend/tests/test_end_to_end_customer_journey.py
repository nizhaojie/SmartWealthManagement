"""端到端客户旅程（ticket 07，本项目的收口）。

Seam：后端 HTTP 层，不引入浏览器。一条贯穿全系统的长用例把九份 spec 的接缝
真的串起来走一遍：开户 → 风险评测 → 咨询 → 产品筛选 → 请理财顾问出具方案 →
理财顾问审核放行 → 客户经理发起操作建议 → 交易 → 风控触发预警 → 工单处置。
两位测试客户（私行与普通两个客户分层）各走一遍。

外部模型与向量化走 fake provider（确定性、零外部调用），向量检索落在测试
Milvus 集合上，图谱指向一个从不重建的空命名空间——因此这里验证的是真实链路
（检索、规则引擎、适当性、审核流、事件协作、工单），而不是回放预置。

边界情形（无画像咨询、超长会话、非法输入、并发请求）各自成用例。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import jwt as pyjwt
import pytest
import redis as redis_lib
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session as OrmSession

import app.analytics.llm as analytics_llm
from app.analytics.validation import validate_query
from app.db.analytics_account import setup_analytics_account
from app.db.models import Customer
from app.main import app
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
MANAGER = "manager1"
ADVISOR = "advisor1"
RISK_OFFICER = "risk1"

# 统一入口（app.agent.registry）给出的五个 Agent 入口路由；旅程按它们发请求，
# 注册表漂移会让这些常量对不上。
CHAT_PATH = "/api/customer/chat/messages"
ANALYTICS_PATH = "/api/internal/analytics/query"
ADVISORY_PLAN_PATH = "/api/internal/advisory/customers/{customer_id}/plan"
OPERATION_ADVICE_PATH = "/api/internal/customers/{customer_id}/operation-advice"
RISK_QUERY_PATH = "/api/internal/risk-monitoring/query"

ANALYTICS_QUESTION = "统计各风险等级的在售产品数量"
ANALYTICS_SQL = (
    "SELECT risk_level, COUNT(*) AS product_count FROM va_product_element "
    "WHERE product_status = '在售' GROUP BY risk_level ORDER BY risk_level"
)
RISK_QUESTION = "按预警等级统计每类预警的数量"
RISK_SQL = (
    "SELECT alert_level, COUNT(*) AS alert_count FROM va_risk_alert_stat "
    "GROUP BY alert_level ORDER BY alert_level"
)

# 交易都落在工作时间（避开 R017），日期固定在种子数据之后、与其他用例不混。
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

FAQ_TITLE = "客户常见问题"
FAQ_CONTENT = "# 客户常见问题\n\n## 赎回后资金多久到账\n\n客户办理赎回业务后，赎回资金将在三个工作日内到账。\n"
# fake embedding 按字形切二元语法向量：问题与正文逐字一致时余弦接近 1，
# 稳定越过检索阈值（与客服 Agent 测试同一 seam，见 test_customer_service_agent）。
FAQ_QUESTION = "客户办理赎回业务后，赎回资金将在三个工作日内到账。"

RISK_INTENT_QUESTION = "我想分几笔转，转账限额是多少？"

# 旅程开的客户在应用里拿不到钱：余额只来自种子（Q20，本 slice 不做入金）。旅程因此
# 直接给他的资金账户写一个余额——它是演示的起点，不是被测行为。
JOURNEY_BALANCE = Decimal("2000000.00")

INFO_LOG = Path(__file__).resolve().parent.parent / "logs" / "info.log"


@pytest.fixture(scope="module")
def _analytics_account(_test_database_ready: None) -> None:
    setup_analytics_account(get_settings().test_database_url)


@pytest.fixture
def journey_client(
    auth_client: TestClient, _analytics_account: None
) -> Iterator[TestClient]:
    """fake 模型 + fake 向量化 + 测试向量集合 + 空图谱命名空间。

    与客服 Agent 自身测试的隔离方式一致：检索是真实向量检索（测试集合），
    回答由 fake provider 从真实检索片段确定性拼装；投顾方案生成不经过模型，
    规则引擎、审核流、工单全部是真实链路。
    """
    base = get_settings()
    test_settings = base.model_copy(
        update={
            "milvus_collection": base.test_milvus_collection,
            "embedding_api_key": "",
            "llm_api_key": "",
            "neo4j_graph_namespace": "wealth_test_customer_journey_unused",
        }
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    analytics_llm.clear_fake_queries()
    try:
        yield auth_client
    finally:
        analytics_llm.clear_fake_queries()
        app.dependency_overrides.pop(get_settings, None)


# ---------------------------------------------------------------------------
# 两位测试客户的画像参数
# ---------------------------------------------------------------------------


def _digits(suffix: str) -> str:
    """把 uuid 十六进制串变成全数字串：证件号与手机号只收数字。"""
    return str(int(suffix, 16)).zfill(12)


def _private_banking_customer(suffix: str) -> dict:
    digits = _digits(suffix)
    return {
        "username": f"journeyhn_{suffix}",
        "real_name": "金全程",
        "id_number": f"11010119700101{digits[:4]}",
        "phone": f"138{digits[:8]}",
        "customer_level": "私行",
        "annual_income_range": "100万以上",
        "total_assets": "5000000.00",
        "investment_experience": "10年以上",
        "target_allocation": {"股票": 60, "债券": 20, "现金": 10, "另类": 10},
    }


def _regular_customer(suffix: str) -> dict:
    digits = _digits(suffix)
    return {
        "username": f"journeyrg_{suffix}",
        "real_name": "温小稳",
        "id_number": f"31010119950505{digits[:4]}",
        "phone": f"139{digits[:8]}",
        "customer_level": "普通",
        "annual_income_range": "10-30万",
        "total_assets": "200000.00",
        "investment_experience": "0-1年",
        "target_allocation": {"股票": 10, "债券": 50, "现金": 40},
    }


def _questionnaire_answers(target: str) -> dict[str, str]:
    """全选第一项 = 16 分（C1）；全选最后一项 = 64 分（C5）。"""
    from app.risk_assessment.questionnaire import QUESTIONS

    answers: dict[str, str] = {}
    for question in QUESTIONS:
        index = 0 if target == "C1" else -1
        answers[question.id] = question.options[index].id
    return answers


# ---------------------------------------------------------------------------
# HTTP 助手
# ---------------------------------------------------------------------------


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _open_account(client: TestClient, persona: dict) -> dict:
    response = client.post(
        "/api/internal/customers",
        headers=_employee_headers(client, MANAGER),
        json={**persona, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _fund_customer_account(customer_id: int) -> None:
    """给旅程客户一笔可动的钱，见 `JOURNEY_BALANCE`。"""
    engine = _engine()
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO fin_funding_account (customer_id, available_balance)"
                    " VALUES (:id, :balance)"
                ),
                {"id": customer_id, "balance": JOURNEY_BALANCE},
            )
    finally:
        engine.dispose()


def _chat(client: TestClient, headers: dict[str, str], message: str) -> dict:
    response = client.post(CHAT_PATH, headers=headers, json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _code_to_product_id(code: str) -> int:
    with OrmSession(_engine()) as session:
        from app.db.models import Product

        product_id = session.scalar(select(Product.id).where(Product.product_code == code))
    assert product_id is not None
    return int(product_id)


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id_by_username(username: str) -> int | None:
    with OrmSession(_engine()) as session:
        return session.scalar(select(Customer.id).where(Customer.username == username))


# 清理顺序即外键依赖顺序（与回放模式测试同一份清单，另加方案请求表与资金账户）。
_CUSTOMER_CHILD_TABLES = (
    "biz_advisory_request",
    "biz_work_order",
    "fin_risk_alert",
    "biz_risk_focus",
    "fin_transaction",
    "fin_transfer",
    "fin_funding_account",
    "fin_holdings",
    "fin_suitability_decision",
    "fin_risk_assessment",
    "fin_profile_tag_conflict",
    "fin_profile_tag",
    "fin_customer_profile",
)


def _delete_customer(customer_id: int) -> None:
    engine = _engine()
    try:
        with engine.begin() as connection:
            # 操作建议那一侧：留言 -> 留痕 -> 审核记录 -> 载荷。审核记录按「内容类型 +
            # 内容引用」定位——它的 content_ref 指向载荷表、draft_id 为空，按 draft_id
            # 清理会一条都删不掉，而待审队列会把它们照样列出来。
            for table, key in (
                ("biz_advisory_review_comment", "review_id"),
                ("biz_advisory_review_audit", "review_id"),
            ):
                connection.execute(
                    text(
                        f"DELETE FROM {table} WHERE {key} IN ("
                        " SELECT id FROM biz_advisory_review"
                        " WHERE content_type = '操作建议' AND content_ref IN ("
                        "  SELECT id FROM biz_operation_advice_draft WHERE customer_id = :id))"
                    ),
                    {"id": customer_id},
                )
            connection.execute(
                text(
                    "DELETE FROM biz_advisory_review"
                    " WHERE content_type = '操作建议' AND content_ref IN ("
                    "  SELECT id FROM biz_operation_advice_draft WHERE customer_id = :id)"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text("DELETE FROM biz_operation_advice_draft WHERE customer_id = :id"),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "DELETE FROM biz_advisory_review_comment WHERE review_id IN ("
                    " SELECT id FROM biz_advisory_review WHERE draft_id IN ("
                    "  SELECT id FROM biz_advisory_draft WHERE customer_id = :id))"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "DELETE FROM biz_advisory_review_audit WHERE review_id IN ("
                    " SELECT id FROM biz_advisory_review WHERE draft_id IN ("
                    "  SELECT id FROM biz_advisory_draft WHERE customer_id = :id))"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "DELETE FROM biz_advisory_review WHERE draft_id IN ("
                    " SELECT id FROM biz_advisory_draft WHERE customer_id = :id)"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "DELETE FROM biz_advisory_final WHERE draft_id IN ("
                    " SELECT id FROM biz_advisory_draft WHERE customer_id = :id)"
                ),
                {"id": customer_id},
            )
            connection.execute(
                text("DELETE FROM biz_advisory_draft WHERE customer_id = :id"),
                {"id": customer_id},
            )
            connection.execute(
                text(
                    "DELETE FROM biz_work_order_transition WHERE work_order_id IN ("
                    " SELECT id FROM biz_work_order WHERE customer_id = :id)"
                ),
                {"id": customer_id},
            )
            for table in _CUSTOMER_CHILD_TABLES:
                connection.execute(
                    text(f"DELETE FROM {table} WHERE customer_id = :id"), {"id": customer_id}
                )
            connection.execute(
                text("DELETE FROM conversation_archive WHERE user_id = :id"),
                {"id": customer_id},
            )
            connection.execute(
                text("DELETE FROM sys_customer WHERE id = :id"), {"id": customer_id}
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# 完整旅程：两位客户各走一遍
# ---------------------------------------------------------------------------


def test_full_customer_journey_for_both_personas(journey_client: TestClient):
    client = journey_client
    suffix = uuid4().hex[:10]
    advisor = _employee_headers(client, ADVISOR)
    risk_officer = _employee_headers(client, RISK_OFFICER)

    # 两个查询 Agent 的确定性装配：fake provider 对指定问题返回指定查询
    # （与数据分析 Agent 自己的测试同一 seam），查询本身先过一遍校验层。
    validate_query(ANALYTICS_SQL)
    validate_query(RISK_SQL)
    analytics_llm.register_fake_query(ANALYTICS_QUESTION, ANALYTICS_SQL)
    analytics_llm.register_fake_query(RISK_QUESTION, RISK_SQL)

    # 知识库准备（内部运营动作，旅程之外的前置）：一份 FAQ，咨询引用它。
    upload = client.post(
        "/api/internal/knowledge/documents",
        headers=advisor,
        files={"file": ("faq.md", FAQ_CONTENT.encode("utf-8"), "text/markdown")},
        data={"knowledge_type": "FAQ", "title": FAQ_TITLE},
    )
    assert upload.status_code == 200, upload.text
    knowledge_id = upload.json()["data"]["knowledge_id"]

    try:
        # 统一入口按 Agent 类型列出五个 Agent；旅程随后就按它给出的入口路由，
        # 把五个 Agent 逐一打到真实链路上。
        agents = client.get("/api/agents")
        assert agents.status_code == 200, agents.text
        entries = {entry["agent_type"]: entry for entry in agents.json()["data"]}
        assert set(entries) == {
            "customer_service",
            "data_analysis",
            "advisory",
            "operation_advice",
            "risk_monitoring",
        }
        assert entries["customer_service"]["identity_domain"] == "customer"
        assert entries["advisory"]["identity_domain"] == "internal"
        assert entries["operation_advice"]["identity_domain"] == "internal"
        assert entries["customer_service"]["tools"] == ["knowledge_search"]
        assert entries["advisory"]["content_classification_default"] == "投顾内容"
        assert entries["operation_advice"]["content_classification_default"] == "投顾内容"
        # 注册表给出的就是旅程实际调用的路由——漂移即失败。
        assert entries["customer_service"]["entry_path"] == CHAT_PATH
        assert entries["data_analysis"]["entry_path"] == ANALYTICS_PATH
        assert entries["advisory"]["entry_path"] == ADVISORY_PLAN_PATH
        assert entries["operation_advice"]["entry_path"] == OPERATION_ADVICE_PATH
        assert entries["risk_monitoring"]["entry_path"] == RISK_QUERY_PATH

        for persona_factory, expected_level in (
            (_private_banking_customer, "C5"),
            (_regular_customer, "C1"),
        ):
            persona = persona_factory(suffix)
            _walk_full_journey(
                client,
                persona=persona,
                expected_level=expected_level,
                advisor=advisor,
                risk_officer=risk_officer,
                entries=entries,
            )

        # 五个 Agent 都已在本旅程中被打到过（各自响应里的 Agent 签名在旅程内断言），
        # 响应时间统计按 agent_type 分组，五个都在场。
        times = client.get(
            "/api/internal/traces/agent-response-times", headers=advisor
        )
        assert times.status_code == 200, times.text
        recorded = {row["agent_type"] for row in times.json()["data"]["agents"]}
        assert recorded >= {
            "customer_service",
            "data_analysis",
            "advisory",
            "operation_advice",
            "risk_monitoring",
        }
    finally:
        for persona_factory in (_private_banking_customer, _regular_customer):
            customer_id = _customer_id_by_username(persona_factory(suffix)["username"])
            if customer_id is not None:
                _delete_customer(int(customer_id))
        client.delete(
            f"/api/internal/knowledge/documents/{knowledge_id}", headers=advisor
        )


def _walk_full_journey(
    client: TestClient,
    *,
    persona: dict,
    expected_level: str,
    advisor: dict[str, str],
    risk_officer: dict[str, str],
    entries: dict[str, dict],
) -> None:
    is_private_banking_customer = persona["customer_level"] == "私行"
    advisory_plan_path = entries["advisory"]["entry_path"]
    operation_advice_path = entries["operation_advice"]["entry_path"]

    # ---- 开户：客户经理为新客户开户，初始画像只有开户时采集的自述信息 ----
    account = _open_account(client, persona)
    customer_id = account["id"]
    assert account["username"] == persona["username"]
    assert account["customer_level"] == persona["customer_level"]
    assert account["status"] == "正常"
    _fund_customer_account(customer_id)

    # ---- 登录；两个身份域互相不可见（护栏 2） ----
    customer = _customer_login(client, persona["username"])
    assert client.get(
        "/api/internal/advisory/queue", headers=customer
    ).status_code in (401, 403)
    assert client.post(
        "/api/customer/chat/messages",
        headers=advisor,
        json={"message": "你好"},
    ).status_code in (401, 403)

    # ---- 咨询（无画像客户）：画像只有默认值、没有任何测评，客服照常作答 ----
    no_profile_chat = _chat(client, customer, "你好呀")
    assert no_profile_chat["answer"]
    assert no_profile_chat["content_classification"] == "事实性内容"

    # ---- 适当性门禁：没有风险测评，产品与候选池一律不可见 ----
    assert client.get(
        "/api/customer/products", headers=customer
    ).status_code == 404
    assert client.get(
        "/api/customer/candidate-pool", headers=customer
    ).status_code == 404

    # ---- 风险评测：问卷提交，画像随之更新 ----
    questionnaire = client.get(
        "/api/customer/risk-assessment/questionnaire", headers=customer
    )
    assert questionnaire.status_code == 200
    questions = questionnaire.json()["data"]["questions"]
    assert len(questions) == 16
    answers = _questionnaire_answers(expected_level)
    submitted = client.post(
        "/api/customer/risk-assessment", headers=customer, json={"answers": answers}
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["data"]["risk_level"] == expected_level

    # 客户可见视图里是自己的测评结论；画像标签在内部视图里随问卷更新。
    profile = client.get("/api/customer/profile", headers=customer)
    assert profile.status_code == 200
    assert profile.json()["data"]["risk_level"] == expected_level
    internal_profile = client.get(
        f"/api/internal/customers/{customer_id}/profile", headers=advisor
    )
    assert internal_profile.status_code == 200
    tags = {tag["key"]: tag for tag in internal_profile.json()["data"]["tags"]}
    assert tags["risk_level"]["value"] == expected_level
    assert tags["risk_level"]["source"] == "风评问卷"

    # ---- 产品筛选：只看得到适当性允许的产品；越级产品连详情都不可见 ----
    products = client.get("/api/customer/products", headers=customer)
    assert products.status_code == 200, products.text
    listed = products.json()["data"]["products"]
    codes = [product["product_code"] for product in listed]
    assert codes == sorted(codes) and codes
    if is_private_banking_customer:
        # C5 对全部在售产品可见（F900001/F900002 停售，不在列表）。
        assert codes == ["F000001", "F000002", "F000003", "F000004", "F000005"]
    else:
        assert codes == ["F000001"]
        over_tier = client.get("/api/customer/products/F000005", headers=customer)
        assert over_tier.status_code == 404

    pool = client.get("/api/customer/candidate-pool", headers=customer)
    assert pool.status_code == 200
    pool_data = pool.json()["data"]
    assert pool_data["customer_risk_level"] == expected_level
    allowed_levels = pool_data["allowed_product_risk_levels"]
    if is_private_banking_customer:
        assert allowed_levels == ["R1", "R2", "R3", "R4", "R5"]
    else:
        assert allowed_levels == ["R1"]

    # ---- 请顾问出具方案：客户提交请求 → 顾问队列 → 顾问生成 AI 原稿 ----
    request = client.post(
        "/api/customer/advisory-requests",
        headers=customer,
        json={"product_type": "基金"},
    )
    assert request.status_code == 200, request.text
    request_id = request.json()["data"]["id"]
    assert request.json()["data"]["status"] == "待处理"

    queue = client.get(
        "/api/internal/advisory-requests",
        params={"status": "待处理"},
        headers=advisor,
    )
    assert queue.status_code == 200
    assert any(row["id"] == request_id for row in queue.json()["data"]["requests"])

    # 顾问先请数据分析 Agent 看一眼在售产品的风险分布（统一入口 → data_analysis）。
    analytics = client.post(
        entries["data_analysis"]["entry_path"],
        headers=advisor,
        json={"question": ANALYTICS_QUESTION},
    )
    assert analytics.status_code == 200, analytics.text
    analytics_data = analytics.json()["data"]
    assert analytics_data["sql"] == ANALYTICS_SQL
    assert analytics_data["row_count"] == len(analytics_data["rows"]) > 0
    assert analytics_data["content_classification"] == "事实性内容"

    # 客户经理没有投顾资质，不能生成方案。
    assert client.post(
        advisory_plan_path.format(customer_id=customer_id),
        headers=_employee_headers(client, MANAGER),
        json={"tilt": None, "advisory_request_id": request_id},
    ).status_code == 403

    draft_response = client.post(
        advisory_plan_path.format(customer_id=customer_id),
        headers=advisor,
        json={"tilt": None, "advisory_request_id": request_id},
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()["data"]
    draft_id = draft["id"]
    # 投顾助手的输出默认是投顾内容；候选全部落在候选池内（适当性在方案里仍然生效）。
    assert draft["content_classification"] == "投顾内容"
    assert draft["candidates"]
    # 方案里的候选全部落在候选池内：适当性约束在投顾内容里依然生效。
    assert all(item["risk_level"] in allowed_levels for item in draft["candidates"])
    assert {warning["code"] for warning in draft["warnings"]}.isdisjoint({"ACTIVE_RISK_ALERT"})

    # ---- 顾问审核放行：客户在放行前读不到方案（护栏 5） ----
    before_release = client.get("/api/customer/advisory/plan", headers=customer)
    assert before_release.status_code == 404

    # 顾问不是照搬原稿：把股票比例下调十个点、挪到现金——一次实质性审核。
    original_allocation = dict(draft["allocation_suggestion"] or {})
    edited_allocation = dict(original_allocation)
    shifted = float(edited_allocation.get("股票", 0)) - 10
    edited_allocation["股票"] = max(shifted, 0.0)
    edited_allocation["现金"] = float(edited_allocation.get("现金", 0)) + (
        float(original_allocation.get("股票", 0)) - edited_allocation["股票"]
    )
    release = client.post(
        f"/api/internal/advisory/drafts/{draft_id}/release",
        headers=advisor,
        json={
            "candidates": None,
            "allocation_suggestion": edited_allocation,
            "warnings": None,
        },
    )
    assert release.status_code == 200, release.text

    # 送达客户的是顾问定稿，不是 AI 原稿：客户读到的配置建议带顾问的修改。
    # 客户送达视图不外泄内部标识，原稿 id 不在其中。
    final = client.get("/api/customer/advisory/plan", headers=customer)
    assert final.status_code == 200, final.text
    delivered = final.json()["data"]
    assert "draft_id" not in delivered
    assert delivered["allocation_suggestion"] == edited_allocation
    assert delivered["allocation_suggestion"] != original_allocation
    assert delivered["advisor_name"]

    # ---- 业务操作 Agent：客户经理为名下客户发起一条操作建议（第五份配置） ----
    # 产品与金额由发起人选定（ADR-0021）：先在可选项里挑一只（受理校验读的是同一份
    # 计算），提交的这只就该被原样采用。
    options = client.get(
        f"/api/internal/customers/{customer_id}/operation-advice-options",
        headers=_employee_headers(client, MANAGER),
        params={"direction": "申购"},
    )
    assert options.status_code == 200, options.text
    choice = next(
        item for item in options.json()["data"]["products"] if item["affordable"]
    )
    advice_body = {
        "direction": "申购",
        "product_code": choice["product_code"],
        "amount": choice["min_amount"],
    }
    advice_response = client.post(
        operation_advice_path.format(customer_id=customer_id),
        headers=_employee_headers(client, MANAGER),
        json=advice_body,
    )
    assert advice_response.status_code == 200, advice_response.text
    advice = advice_response.json()["data"]
    # 单笔操作建议也是投顾内容：未经放行进不了客户可见集合（护栏 5 的第二个出口）。
    assert advice["content_classification"] == "投顾内容"
    assert advice["direction"] == "申购"
    assert advice["reason"]
    # 产品仍是候选人选的，且仍在候选池内（护栏 1 的延续）：客户可见的产品清单就是候选池。
    assert advice["product_code"] == choice["product_code"]
    assert advice["amount"] == choice["min_amount"]
    assert advice["product_code"] in codes

    # 理财顾问没有发起入口：发起与放行不落进同一个人手里。
    assert client.post(
        operation_advice_path.format(customer_id=customer_id),
        headers=advisor,
        json=advice_body,
    ).status_code == 403

    # ---- 交易：真实交易触发风控规则，产生分级预警 ----
    in_level_code = "F000005" if is_private_banking_customer else "F000001"
    in_level_id = _code_to_product_id(in_level_code)

    def _submit(amount: str, occurred_at: datetime) -> dict:
        response = client.post(
            "/api/internal/transaction-events",
            headers=risk_officer,
            json={
                "customer_id": customer_id,
                "product_id": in_level_id,
                "transaction_type": "申购",
                "amount": amount,
                "occurred_at": occurred_at.isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]

    if is_private_banking_customer:
        first = _submit("60000", TRADE_AT)
        assert first["alerts"] and first["alerts"][0]["alert_level"] == "轻度"
        heavy = _submit("1200000", TRADE_AT.replace(hour=12))
        # 大额同时命中多条规则（R001/R002/R003/R005），且已有历史预警 → 必为重度。
        assert heavy["alerts"] and heavy["alerts"][0]["alert_level"] == "重度"
        heavy_alert_id = int(heavy["alerts"][0]["id"])
    else:
        single = _submit("100000", TRADE_AT)
        # 恰好命中 R001（单笔 ≥ 5 万）：一条规则 → 轻度。
        assert len(single["alerts"]) == 1
        assert single["alerts"][0]["alert_level"] == "轻度"
        heavy_alert_id = int(single["alerts"][0]["id"])

    listed_alerts = client.get(
        "/api/internal/risk-alerts",
        params={"customer_id": customer_id},
        headers=risk_officer,
    )
    assert listed_alerts.status_code == 200
    # 风险关注里已经留下这位客户的风控预警记录（订阅方在广播时写下）。
    focus = client.get("/api/internal/risk-focus", headers=risk_officer)
    assert focus.status_code == 200
    assert any(
        row["customer_id"] == customer_id and row["focus_type"] == "风控预警"
        for row in focus.json()["data"]
    )

    # ---- 工单处置：预警派生工单 → 受理 → 办结，每次流转都有理由 ----
    derived = client.post(
        f"/api/internal/risk-alerts/{heavy_alert_id}/work-orders",
        headers=risk_officer,
        json={"reason": "客户短期大额申购，需要核实资金来源"},
    )
    assert derived.status_code == 200, derived.text
    order = derived.json()["data"]
    assert order["status"] == "待处理"
    if is_private_banking_customer:
        assert order["priority"] == "特急"
    else:
        assert order["priority"] == "普通"

    accept = client.post(
        f"/api/internal/work-orders/{order['id']}/accept",
        headers=risk_officer,
        json={"reason": "已接单，联系客户核实"},
    )
    assert accept.status_code == 200
    assert accept.json()["data"]["status"] == "处理中"

    complete = client.post(
        f"/api/internal/work-orders/{order['id']}/complete",
        headers=risk_officer,
        json={"reason": "核实完毕", "conclusion": "资金来源清楚，确认为正常交易"},
    )
    assert complete.status_code == 200
    assert complete.json()["data"]["status"] == "已完成"

    detail = client.get(
        f"/api/internal/work-orders/{order['id']}", headers=risk_officer
    )
    assert detail.status_code == 200
    transitions = detail.json()["data"]["transitions"]
    assert [row["to_status"] for row in transitions] == ["待处理", "处理中", "已完成"]
    assert all(row["reason"] for row in transitions)

    # 风控专员用自然语言查预警统计（统一入口 → risk_monitoring）：刚产生的
    # 交易与预警已经能被查到——事件真的落了库，不是只留在响应里。
    risk_query = client.post(
        entries["risk_monitoring"]["entry_path"],
        headers=risk_officer,
        json={"question": RISK_QUESTION},
    )
    assert risk_query.status_code == 200, risk_query.text
    risk_data = risk_query.json()["data"]
    assert risk_data["sql"] == RISK_SQL
    level_column = risk_data["columns"].index("alert_level")
    count_column = risk_data["columns"].index("alert_count")
    levels = {row[level_column]: row[count_column] for row in risk_data["rows"]}
    assert levels.get("重度", 0) >= (1 if is_private_banking_customer else 0)
    assert levels.get("轻度", 0) >= 1

    # ---- 风控预警之后，投顾侧能看到该客户的风险标记 ----
    flagged = client.post(
        advisory_plan_path.format(customer_id=customer_id),
        headers=advisor,
        json={"tilt": None},
    )
    assert flagged.status_code == 200, flagged.text
    warning_codes = {warning["code"] for warning in flagged.json()["data"]["warnings"]}
    assert "ACTIVE_RISK_ALERT" in warning_codes

    # ---- 带固定追踪标识的咨询：高风险意图进风控关注，追踪标识贯穿全链路 ----
    trace_id = f"journey-trace-{uuid4().hex[:12]}"
    traced = client.post(
        CHAT_PATH,
        headers={**customer, "X-Trace-Id": trace_id},
        json={"message": RISK_INTENT_QUESTION},
    )
    assert traced.status_code == 200, traced.text
    intent_chat = traced.json()["data"]
    assert intent_chat["answer"]
    # 响应信封与响应头都带回同一追踪标识。
    assert intent_chat["trace_id"] == trace_id
    assert traced.headers["x-trace-id"] == trace_id

    focus = client.get(
        "/api/internal/risk-focus",
        params={"focus_type": "高风险意图"},
        headers=risk_officer,
    )
    assert focus.status_code == 200
    intent_rows = [
        row for row in focus.json()["data"] if row["customer_id"] == customer_id
    ]
    assert intent_rows and intent_rows[0]["trace_id"] == trace_id

    # 带标识的请求在日志里找得到：一次用户可见的结果能对应到日志的具体位置。
    log_lines = INFO_LOG.read_text(encoding="utf-8")
    assert f"trace_id={trace_id}" in log_lines


# ---------------------------------------------------------------------------
# 边界情形：各自可通
# ---------------------------------------------------------------------------


def test_consultation_works_for_a_freshly_opened_customer(journey_client: TestClient):
    """无画像客户咨询：开户后没有任何测评与持仓，客服照常给出带引用的回答。"""
    client = journey_client
    advisor = _employee_headers(client, ADVISOR)
    upload = client.post(
        "/api/internal/knowledge/documents",
        headers=advisor,
        files={"file": ("faq.md", FAQ_CONTENT.encode("utf-8"), "text/markdown")},
        data={"knowledge_type": "FAQ", "title": FAQ_TITLE},
    )
    assert upload.status_code == 200, upload.text
    knowledge_id = upload.json()["data"]["knowledge_id"]
    persona = _regular_customer(uuid4().hex[:10])
    try:
        _open_account(client, persona)
        customer = _customer_login(client, persona["username"])
        data = _chat(client, customer, FAQ_QUESTION)
        assert data["answer"]
        assert data["citations"], "检索命中时应给出引用"
        assert data["content_classification"] == "事实性内容"
        assert data["degraded"] is False
        inline = {int(n) for n in re.findall(r"\[(\d+)\]", data["answer"])}
        assert inline == {citation["marker"] for citation in data["citations"]}
    finally:
        customer_id = _customer_id_by_username(persona["username"])
        if customer_id is not None:
            _delete_customer(int(customer_id))
        client.delete(f"/api/internal/knowledge/documents/{knowledge_id}", headers=advisor)


def test_super_long_conversation_stays_bounded(journey_client: TestClient):
    """超长对话（远超 token 预算）不报错，短期记忆截断最旧消息、最新消息保留。"""
    client = journey_client
    persona = _regular_customer(uuid4().hex[:10])
    try:
        _open_account(client, persona)
        customer = _customer_login(client, persona["username"])
        token = customer["Authorization"].split(" ", 1)[1]
        session_id = pyjwt.decode(token, options={"verify_signature": False})["sid"]
        memory_key = f"agent:memory:{session_id}"

        huge = "行情波动" * 475  # 每条约 1900 token：一轮就吃掉几乎整个预算
        for index in range(12):
            data = _chat(client, customer, f"第{index}条：{huge}")
            assert data["answer"]

        cache = redis_lib.Redis.from_url(
            get_settings().test_redis_url, decode_responses=True
        )
        try:
            length = cache.llen(memory_key)
            # 12 轮累计远超 2000 token 预算：最旧的被截断，只剩最后几条消息。
            assert 0 < length <= 6
            messages = [json.loads(raw) for raw in cache.lrange(memory_key, 0, -1)]
        finally:
            cache.close()
        # 最新的消息一定保留：最后一轮是第 11 条的问答对。
        assert messages[-2]["content"].startswith("第11条：")
        assert messages[-1]["role"] == "assistant"
    finally:
        customer_id = _customer_id_by_username(persona["username"])
        if customer_id is not None:
            _delete_customer(int(customer_id))


def test_illegal_inputs_are_rejected_without_broken_state(journey_client: TestClient):
    """非法输入被拒绝且不留坏状态：开户、问卷、对话、方案、工单各来一发。"""
    client = journey_client
    manager = _employee_headers(client, MANAGER)
    risk_officer = _employee_headers(client, RISK_OFFICER)
    persona = _regular_customer(uuid4().hex[:10])
    customer_id: int | None = None
    try:
        # 开户：分层不在枚举内。
        bad_level = client.post(
            "/api/internal/customers",
            headers=manager,
            json={**persona, "password": SEEDED_PASSWORD, "customer_level": "钻石王老五"},
        )
        assert bad_level.status_code == 400

        account = _open_account(client, persona)
        customer_id = account["id"]

        # 开户：用户名唯一。
        duplicate = client.post(
            "/api/internal/customers",
            headers=manager,
            json={**persona, "password": SEEDED_PASSWORD},
        )
        assert duplicate.status_code == 409

        # 开户：证件号同样唯一——换了用户名也不行。
        other_name = client.post(
            "/api/internal/customers",
            headers=manager,
            json={
                **_regular_customer(uuid4().hex[:10]),
                "id_number": persona["id_number"],
                "password": SEEDED_PASSWORD,
            },
        )
        assert other_name.status_code == 409

        customer = _customer_login(client, persona["username"])

        # 问卷：答案缺题、选项非法都被拒绝。
        answers = _questionnaire_answers("C1")
        incomplete = client.post(
            "/api/customer/risk-assessment",
            headers=customer,
            json={"answers": dict(list(answers.items())[:10])},
        )
        assert incomplete.status_code == 400
        assert incomplete.json()["code"] == 400
        invalid = client.post(
            "/api/customer/risk-assessment",
            headers=customer,
            json={"answers": {**answers, "q99": "A"}},
        )
        assert invalid.json()["code"] == 400

        # 对话：类型错误的请求体按参数错误处理，不是 500；空串也能被体面接住。
        wrong_type = client.post(
            "/api/customer/chat/messages", headers=customer, json={"message": 123}
        )
        assert wrong_type.status_code == 400
        assert wrong_type.json()["code"] == 400
        empty = client.post(
            "/api/customer/chat/messages", headers=customer, json={"message": "  "}
        )
        assert empty.status_code == 200

        # 方案：给不存在的客户生成方案。
        missing = client.post(
            "/api/internal/advisory/customers/99999999/plan",
            headers=_employee_headers(client, ADVISOR),
            json={"tilt": None},
        )
        assert missing.status_code == 404

        # 工单：流转必须给非空理由。
        # 先造一条可派生的预警，再验证空理由被拒绝。
        product_id = _code_to_product_id("F000001")
        submitted = client.post(
            "/api/internal/transaction-events",
            headers=risk_officer,
            json={
                "customer_id": customer_id,
                "product_id": product_id,
                "transaction_type": "申购",
                "amount": "100000",
                "occurred_at": TRADE_AT.isoformat(),
            },
        )
        assert submitted.status_code == 200, submitted.text
        alert_id = int(submitted.json()["data"]["alerts"][0]["id"])

        blank = client.post(
            f"/api/internal/risk-alerts/{alert_id}/work-orders",
            headers=risk_officer,
            json={"reason": "   "},
        )
        assert blank.status_code == 400
        assert "理由" in blank.json()["message"]

        derived = client.post(
            f"/api/internal/risk-alerts/{alert_id}/work-orders",
            headers=risk_officer,
            json={"reason": "正常派生"},
        )
        assert derived.status_code == 200
        blank_accept = client.post(
            f"/api/internal/work-orders/{derived.json()['data']['id']}/accept",
            headers=risk_officer,
            json={"reason": ""},
        )
        assert blank_accept.status_code == 400
    finally:
        if customer_id is not None:
            _delete_customer(customer_id)


def test_concurrent_requests_are_handled(journey_client: TestClient):
    """并发请求：同一客户的并发咨询全部成功；同一份原稿的并发放行只有一个成功。"""
    client = journey_client
    advisor = _employee_headers(client, ADVISOR)
    persona = _private_banking_customer(uuid4().hex[:10])
    customer_id: int | None = None
    try:
        account = _open_account(client, persona)
        customer_id = account["id"]
        customer = _customer_login(client, persona["username"])

        answers = _questionnaire_answers("C5")
        submitted = client.post(
            "/api/customer/risk-assessment", headers=customer, json={"answers": answers}
        )
        assert submitted.status_code == 200

        # 并发咨询：八条同时发出，全部成功且各自带回追踪标识。
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(
                pool.map(
                    lambda index: _chat(client, customer, f"并发问题{index}：请问如何查询持仓"),
                    range(8),
                )
            )
        assert len(responses) == 8
        assert all(response["answer"] for response in responses)
        assert len({response["trace_id"] for response in responses}) == 8

        # 并发放行同一份 AI 原稿：数据库原子锁保证恰好一个成功，另一个 409。
        draft = client.post(
            f"/api/internal/advisory/customers/{customer_id}/plan",
            headers=advisor,
            json={"tilt": None},
        )
        assert draft.status_code == 200, draft.text
        draft_id = draft.json()["data"]["id"]
        payload = {"candidates": None, "allocation_suggestion": None, "warnings": None}

        def _release(_index: int):
            return client.post(
                f"/api/internal/advisory/drafts/{draft_id}/release",
                headers=advisor,
                json=payload,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(_release, range(2)))
        status_codes = sorted(response.status_code for response in outcomes)
        assert status_codes == [200, 409]
    finally:
        if customer_id is not None:
            _delete_customer(customer_id)
