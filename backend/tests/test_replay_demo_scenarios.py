"""回放模式的集成测试（ADR-0008 / spec「回放模式」）。

双重身份：既是验收测试，也示范「回放数据兼作集成测试夹具」的用法——
七类演示场景在这里全部走过 HTTP 层，同时用桩把所有外部出口堵死，
任何一处发起模型 / Milvus / Neo4j / Redis 调用都会当场失败：

- 模型：`app.llm.provider._request_chat`（唯一的 HTTP 出口）；
- 向量化与向量库：`app.knowledge.service.embed_texts`、`vector_store.get_client`；
- 图谱：`neo4j.Driver.session`（驱动惰性连接，任何真实使用都要先开 session）；
- Redis：本夹具根本不构造真客户端，依赖注入的是进程内 `InMemoryCache`。

场景数据落在专用客户 ``replaydemo1`` 上（幂等插入），不改写任何种子客户
——测试库跨运行持久，风控、适当性等其它用例按种子客户的等级做精确断言。

预置数据本身的一致性（引用合法、SQL 合法、知识摘录与 FAQ 种子逐字一致）
在纯函数测试里校验，不依赖任何容器。
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import redis as redis_lib
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from neo4j import Driver
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as OrmSession

from app.analytics import validation
from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    Customer,
    CustomerProfile,
    Holding,
    ProfileTag,
    RiskAssessment,
)
from app.db.session import get_session
from app.knowledge import service as knowledge_service
from app.knowledge import object_store
from app.knowledge import vector_store
from app.llm import provider
from app.main import app
from app.replay import library as replay_library
from app.replay.local_cache import InMemoryCache
from app.redis_client import get_redis
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
REPLAY_CUSTOMER = "replaydemo1"

_FAQ_PATH = Path(__file__).resolve().parent.parent / "app" / "knowledge" / "fixtures" / "faq_seed.md"

# 一条触发 R002（单笔金额 ≥ 100 万，重度）的交易金额。
_HEAVY_ALERT_AMOUNT = "1200000"


def _raise_no_external(*_args, **_kwargs):
    raise AssertionError("回放模式发起了外部调用")


# 清理顺序即外键依赖顺序：先删引用方，再删被引用方。
# 前四张表没有 customer_id，沿 审核记录 → 原稿 → 客户 的外键路径定位。
_CUSTOMER_CHILD_TABLES = (
    "biz_advisory_request",
    "biz_work_order",
    "fin_risk_alert",
    "biz_risk_focus",
    "fin_transaction",
    "fin_holdings",
    "fin_suitability_decision",
    "fin_risk_assessment",
    "fin_profile_tag_conflict",
    "fin_profile_tag",
    "fin_customer_profile",
)
# 原稿在审核记录/定稿之后、方案请求之前删除（它被前者引用、引用后者）。


def _delete_replay_customer(customer_id: int) -> None:
    """删掉演示客户及其全部依赖行：测试库跨运行持久，种子客户的状态与
    其它用例的精确断言共底，这里不留任何本用例写入的痕迹。"""
    engine = _engine()
    try:
        with engine.begin() as connection:
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
            # 归档按 user_id 落（无外键），只清本用例写给这位客户的记录。
            connection.execute(
                text("DELETE FROM conversation_archive WHERE user_id = :id"),
                {"id": customer_id},
            )
            connection.execute(
                text("DELETE FROM sys_customer WHERE id = :id AND username = :username"),
                {"id": customer_id, "username": REPLAY_CUSTOMER},
            )
    finally:
        engine.dispose()


@pytest.fixture
def replay_client(_test_database_ready: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """回放模式的 HTTP 夹具：demo_replay 开启 + 全部外部出口堵死。"""
    settings = get_settings().model_copy(
        update={
            "demo_replay": True,
            "llm_api_key": "",
            "embedding_api_key": "",
            "neo4j_graph_namespace": get_settings().test_neo4j_graph_namespace,
            # 预置之外的问题走关键词臂（本地 BM25）。阈值在这里显式注入：「明显无关的
            # 问题不触发作答」这条断言要的是用例自己掌握的分界，不依赖 issue 04 校准出
            # 的默认值（它随语料漂移）。
            "retrieval_keyword_score_threshold": 10.0,
        }
    )
    engine = create_engine(settings.test_database_url)
    cache = InMemoryCache()

    def override_get_session() -> Iterator[OrmSession]:
        with OrmSession(engine) as session:
            yield session

    def override_get_redis() -> Iterator[InMemoryCache]:
        yield cache

    app_dependencies = (get_session, get_redis, get_settings)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_settings] = lambda: settings

    monkeypatch.setattr(provider, "_request_chat", _raise_no_external)
    monkeypatch.setattr(vector_store, "get_client", _raise_no_external)
    monkeypatch.setattr(object_store, "get_client", _raise_no_external)
    # 检索路径里的向量化：replay 分支根本不该走到，堵死以防回归。
    monkeypatch.setattr(knowledge_service, "embed_texts", _raise_no_external)
    monkeypatch.setattr(Driver, "session", _raise_no_external)

    demo_customer_id = _ensure_replay_customer()
    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        _delete_replay_customer(demo_customer_id)
        for dependency in app_dependencies:
            app.dependency_overrides.pop(dependency, None)
        engine.dispose()


def _engine():
    return create_engine(get_settings().test_database_url)


def _sql_one(sql: str, **params):
    engine = _engine()
    try:
        with engine.connect() as connection:
            return connection.execute(text(sql), params).one()
    finally:
        engine.dispose()


def _ensure_replay_customer() -> int:
    """幂等插入演示专用客户：C2 画像 + 标签 + 一笔 F000003 持仓。

    持仓对齐基础种子里 zhangc3 对 F000003 的数字（份额 66666.6667、市值
    108000），图谱多跳断言因此可以复用同一组行业占比。风险测评由用例走
    API 提交（场景三的一部分），保证每次运行都有一份未过期的测评。
    """
    hasher = PasswordHasher()
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            customer = session.query(Customer).filter_by(username=REPLAY_CUSTOMER).one_or_none()
            now = datetime(2024, 1, 1, 9, 0, 0)
            if customer is None:
                customer = Customer(
                    username=REPLAY_CUSTOMER,
                    password_hash=hasher.hash(SEEDED_PASSWORD),
                    real_name="回放演示",
                    id_number="110101199201010011",
                    phone="13800139000",
                    customer_level="白金",
                    status="正常",
                    opened_at=now,
                )
                session.add(customer)
                session.flush()

            if (
                session.query(CustomerProfile).filter_by(customer_id=customer.id).one_or_none()
                is None
            ):
                session.add(
                    CustomerProfile(
                        customer_id=customer.id,
                        risk_level="C3",
                        risk_score=50,
                        investment_experience="3-5年",
                        annual_income_range="30-50万",
                        total_assets=Decimal("800000.00"),
                        target_allocation={"股票": 40, "债券": 35, "现金": 15, "另类": 10},
                        product_preference={"基金": ["混合基金"]},
                        confidence_score=Decimal("0.90"),
                        computed_at=now,
                    )
                )
                tags = {
                    "risk_level": "C3",
                    "investment_experience": "3-5年",
                    "annual_income_range": "30-50万",
                    "total_assets": "800000.00",
                    "target_allocation": {"股票": 40, "债券": 35, "现金": 15, "另类": 10},
                    "product_preference": {"基金": ["混合基金"]},
                }
                for tag_key, value in tags.items():
                    session.add(
                        ProfileTag(
                            customer_id=customer.id,
                            tag_key=tag_key,
                            tag_value=value,
                            source=SOURCE_QUESTIONNAIRE,
                            evidence_count=0,
                            observed_at=now,
                        )
                    )

            product_id = session.execute(
                text("SELECT id FROM fin_product WHERE product_code = 'F000003'")
            ).scalar_one()
            has_holding = (
                session.query(Holding)
                .filter_by(customer_id=customer.id, product_id=product_id)
                .one_or_none()
                is not None
            )
            if not has_holding:
                session.add(
                    Holding(
                        customer_id=customer.id,
                        product_id=product_id,
                        shares=Decimal("66666.6667"),
                        cost_amount=Decimal("100000.00"),
                        current_value=Decimal("108000.00"),
                        profit_loss=Decimal("8000.00"),
                        profit_ratio=Decimal("8.0000"),
                        status="持有中",
                        create_time=now,
                    )
                )
            session.commit()
            return int(customer.id)
    finally:
        engine.dispose()


def _login(client: TestClient, path: str, username: str) -> dict[str, str]:
    response = client.post(
        path,
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
    return _login(client, "/api/customer/auth/login", username)


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    return _login(client, "/api/internal/auth/login", username)


def _chat(client: TestClient, headers: dict[str, str], question: str) -> dict:
    response = client.post(
        "/api/customer/chat/messages",
        headers=headers,
        json={"message": question},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _moderate_answers() -> dict[str, str]:
    """一份全选第二选项的问卷答案：16 题总分 32，评为 C2。"""
    from app.risk_assessment.questionnaire import QUESTIONS

    return {question.id: question.options[1].id for question in QUESTIONS}


# ---------------------------------------------------------------------------
# 七类演示场景：一次走完，全程外部出口被堵死
# ---------------------------------------------------------------------------


def test_seven_demo_scenarios_replay_offline(replay_client: TestClient) -> None:
    client = replay_client
    demo_id = _ensure_replay_customer()
    demo = _customer_headers(client, REPLAY_CUSTOMER)
    advisor = _employee_headers(client, "advisor1")
    risk_officer = _employee_headers(client, "risk1")

    # 前置 + 场景三的一半：重做风评（纯 MySQL + 进程内缓存），画像随之更新。
    answers = _moderate_answers()
    response = client.post(
        "/api/customer/risk-assessment", headers=demo, json={"answers": answers}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["risk_level"] == "C2"

    # 场景一：客服问答带引用——四条预置（含图谱多跳一条）+ 闲聊一条。
    for preset in replay_library.CHAT_PRESETS:
        data = _chat(client, demo, preset.question)
        assert data["answer"] == preset.answer
        assert data["content_classification"] == "事实性内容"
        assert data["trace_id"]
        assert data["degraded"] is False
        markers = [citation["marker"] for citation in data["citations"]]
        assert markers == list(preset.cited)
        # 引用合法：相似度分块指向知识库文档，图谱段落的来源是「知识图谱」而不是
        # 某个不存在的文件（负数 knowledge_id 是图谱段落的标识，见 agent/fusion.py）。
        for citation in data["citations"]:
            if citation["knowledge_id"] < 0:
                assert citation["title"] == "知识图谱"
                assert citation["source_file"].startswith("graph:")
            else:
                assert citation["title"] == "客户常见问题"
                assert citation["heading_path"][0] == "客户常见问题"
        # 回答文本里的每个 [N] 角标都有结构化引用可点，前端不会渲染出裸文本。
        inline_markers = {int(number) for number in re.findall(r"\[(\d+)\]", data["answer"])}
        assert inline_markers == set(markers)

    chitchat = _chat(client, demo, "你好")
    assert chitchat["answer"] == replay_library.CHITCHAT_PRESETS["你好"]
    assert chitchat["citations"] == []
    assert chitchat["intent"] == "闲聊"

    # 场景二：产品筛选——纯 MySQL，回放模式原样可用，按产品代码排序，
    # 且只出现适当性允许的风险等级（C2 → R1/R2）。
    response = client.get("/api/customer/products", headers=demo)
    assert response.status_code == 200
    products = response.json()["data"]["items"]
    codes = [product["product_code"] for product in products]
    assert codes == sorted(codes)
    assert codes
    assert all(product["risk_level"] in ("R1", "R2") for product in products)
    response = client.get("/api/customer/products/F000001", headers=demo)
    assert response.status_code == 200
    assert response.json()["data"]["product_name"] == "天枢货币基金"

    # 场景三：画像与适当性——客户画像随测评更新；候选池经适当性硬过滤。
    response = client.get("/api/customer/profile", headers=demo)
    assert response.status_code == 200
    assert response.json()["data"]["risk_level"] == "C2"
    response = client.get(
        f"/api/internal/customers/{demo_id}/candidate-pool", headers=advisor
    )
    assert response.status_code == 200
    pool = response.json()["data"]
    assert pool["customer_risk_level"] == "C2"
    assert pool["allowed_product_risk_levels"] == ["R1", "R2"]
    assert pool["products"]
    assert all(product["risk_level"] in ("R1", "R2") for product in pool["products"])

    # 场景四：数据查询（NL2SQL）——预置 SQL + 预写解读，行是实时查出来的。
    response = client.post(
        "/api/internal/analytics/query",
        headers=advisor,
        json={"question": replay_library.ANALYTICS_PRESETS[0].question},
    )
    assert response.status_code == 200, response.text
    query = response.json()["data"]
    assert query["sql"] == replay_library.ANALYTICS_PRESETS[0].sql
    assert query["interpretation"] == replay_library.ANALYTICS_PRESETS[0].interpretation
    assert query["row_count"] == len(query["rows"]) > 0
    assert query["content_classification"] == "事实性内容"

    # 场景五：投顾方案与审核——生成（AI 原稿）→ 放行（顾问定稿）。
    response = client.post(
        f"/api/internal/advisory/customers/{demo_id}/plan",
        headers=advisor,
        json={"tilt": None},
    )
    assert response.status_code == 200, response.text
    draft = response.json()["data"]
    draft_id = draft["id"]
    assert draft["customer_id"] == demo_id
    # AI 原稿是真实链路确定性生成的（投顾图不经过模型），回放模式下内容照常完整。
    assert draft["candidates"]
    assert draft["content_classification"] == "投顾内容"
    response = client.post(
        f"/api/internal/advisory/drafts/{draft_id}/release",
        headers=advisor,
        json={"candidates": None, "allocation_suggestion": None, "warnings": None},
    )
    assert response.status_code == 200, response.text
    final = response.json()["data"]
    assert final["draft_id"] == draft_id
    response = client.get(
        f"/api/internal/advisory/drafts/{draft_id}/final", headers=advisor
    )
    assert response.status_code == 200

    # 场景六：图谱多跳——客户 → 产品 → 行业 + 基金经理，直接来自 MySQL 投影。
    response = client.get(
        f"/api/internal/graph/customers/{demo_id}?expand=fund_manager",
        headers=advisor,
    )
    assert response.status_code == 200, response.text
    graph = response.json()["data"]
    assert graph["degraded"] is False
    labels = {node["label"] for node in graph["nodes"]}
    assert "回放演示" in labels
    assert "天璇混合基金" in labels
    assert "冯川" in labels  # F000003 的基金经理：多跳的第三跳
    edge_types = {edge["type"] for edge in graph["edges"]}
    assert {"HOLDS", "BELONGS_TO_INDUSTRY", "MANAGED_BY"} <= edge_types
    # 行业占比与资产页的持仓穿透同源（MySQL 权威数据）：F000003 直接底层
    # 大盘蓝筹 0.4 + 利率债 0.2，两者合计为分母。
    shares = {
        node["attrs"]["industry"]: node["attrs"]["share"]
        for node in graph["nodes"]
        if node["type"] == "industry"
    }
    assert shares == pytest.approx({"大盘蓝筹": 2 / 3, "利率债": 1 / 3})

    # 场景七：风控预警分级——交易事件落库 → 规则命中 → 分级预警。
    # 分级口径：单条命中轻度、多条交叉中度、多条且客户有历史预警才到重度。
    # 先来一笔小额（R001 命中，轻度），再来一笔大额（多条交叉 + 有历史）出重度。
    f000004_id = int(
        _sql_one(
            "SELECT id FROM fin_product WHERE product_code = 'F000004'"
        ).id
    )

    def _submit(amount: str) -> list[dict]:
        response = client.post(
            "/api/internal/transaction-events",
            headers=risk_officer,
            json={
                "customer_id": demo_id,
                "product_id": f000004_id,
                "transaction_type": "申购",
                "amount": amount,
                # 流水号每次运行生成：测试库跨次持久，写死会撞 409。
                "transaction_no": f"TX-REPLAY-{uuid4().hex[:12]}",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["data"]["alerts"]

    first_alerts = _submit("60000")
    # 小额笔的等级取决于库里是否已有该客户的历史预警（跨运行累积），不细断；
    # 它的作用是保证下一笔大额必然存在「本次之前」的预警记录。
    assert first_alerts
    heavy_alerts = _submit(_HEAVY_ALERT_AMOUNT)
    assert heavy_alerts
    # 大额同时命中多条规则（R001/R002/R003/越级），且必有历史预警 → 必为重度。
    assert heavy_alerts[0]["alert_level"] == "重度"
    response = client.get(
        "/api/internal/risk-alerts",
        params={"alert_level": "重度"},
        headers=risk_officer,
    )
    assert response.status_code == 200
    # 刚造出来的那条是最新的，排序是「最新的在前」（`create_time` 倒序），所以它一定在
    # 第一页上——即使这张表跨运行累积到装不下一页。
    assert any(
        alert["customer_id"] == demo_id for alert in response.json()["data"]["items"]
    )

    # 场景七的自然语言查询：预置 SQL + 解读，统计数字来自刚落库的预警。
    risk_preset = replay_library.ANALYTICS_PRESETS[1]
    response = client.post(
        "/api/internal/risk-monitoring/query",
        headers=risk_officer,
        json={"question": risk_preset.question},
    )
    assert response.status_code == 200, response.text
    risk_query = response.json()["data"]
    assert risk_query["sql"] == risk_preset.sql
    assert risk_query["interpretation"] == risk_preset.interpretation
    assert risk_query["rows"]


def test_high_risk_intent_reaches_risk_focus_in_replay(replay_client: TestClient) -> None:
    """客服察觉高风险意图 → 进程内事件分发 → 风控专员看得到关注记录。"""
    client = replay_client
    demo_id = _ensure_replay_customer()
    demo = _customer_headers(client, REPLAY_CUSTOMER)
    data = _chat(client, demo, "我想分几笔转，转账限额是多少？")
    assert data["answer"]

    risk_officer = _employee_headers(client, "risk1")
    response = client.get("/api/internal/risk-focus", headers=risk_officer)
    assert response.status_code == 200
    entries = response.json()["data"]["items"]
    assert any(
        entry["customer_id"] == demo_id and entry["focus_type"] == "高风险意图"
        for entry in entries
    )


def test_replay_same_question_same_answer_across_sessions(
    replay_client: TestClient,
) -> None:
    """同一问题的回放结果确定性可复现：换一个会话再问，逐字一致。"""
    client = replay_client
    question = replay_library.CHAT_PRESETS[0].question
    first = _chat(client, _customer_headers(client, "wangc1"), question)
    second = _chat(client, _customer_headers(client, "lisic2"), question)
    assert first["answer"] == second["answer"] == replay_library.CHAT_PRESETS[0].answer
    assert first["citations"] == second["citations"]


def test_replay_stream_matches_non_stream_answer(replay_client: TestClient) -> None:
    """SSE 流式与同步接口给出同一条回放回答（前端无需区分）。"""
    client = replay_client
    headers = _customer_headers(client, "wangc1")
    question = replay_library.CHAT_PRESETS[1].question
    streamed = client.post(
        "/api/customer/chat/stream", headers=headers, json={"message": question}
    )
    assert streamed.status_code == 200
    done_frames = [
        line[len("data: "):]
        for line in streamed.text.splitlines()
        if line.startswith("data: ")
    ]
    done_payload = json.loads(done_frames[-1])
    assert done_payload["answer"] == replay_library.CHAT_PRESETS[1].answer
    assert done_payload["degraded"] is False


def test_replay_unmatched_question_stays_offline(replay_client: TestClient) -> None:
    """预置之外的问题也不发起外部调用：检索不到依据就明确告知，不编造。"""
    client = replay_client
    data = _chat(
        client, _customer_headers(client, "wangc1"), "量子金融衍生品定价模型是什么？"
    )
    assert "人工客服热线" in data["answer"]
    assert data["citations"] == []
    assert data["degraded"] is False


def test_replay_rejects_graph_rebuild(replay_client: TestClient) -> None:
    client = replay_client
    response = client.post(
        "/api/internal/graph/rebuild", headers=_employee_headers(client, "advisor1")
    )
    assert response.status_code == 400
    assert "回放模式" in response.json()["message"]


def test_replay_rejects_knowledge_mutations(replay_client: TestClient) -> None:
    """知识库上传/下架会调用向量化、Milvus 与对象存储：回放模式明确拒绝。"""
    client = replay_client
    advisor = _employee_headers(client, "advisor1")
    response = client.post(
        "/api/internal/knowledge/documents",
        headers=advisor,
        files={"file": ("demo.md", "# 演示\n\n内容".encode("utf-8"), "text/markdown")},
        data={"knowledge_type": "FAQ", "title": "演示文档"},
    )
    assert response.status_code == 400
    assert "回放模式" in response.json()["message"]
    response = client.delete(
        "/api/internal/knowledge/documents/1", headers=advisor
    )
    assert response.status_code == 400
    assert "回放模式" in response.json()["message"]


# ---------------------------------------------------------------------------
# 预置数据本身的一致性（纯函数，不起服务）
# ---------------------------------------------------------------------------


def test_chat_preset_chunks_quote_the_faq_seed_verbatim() -> None:
    """预置分块逐字摘自 FAQ 种子：引用指向的是真实存在的知识。"""
    faq_text = _FAQ_PATH.read_text(encoding="utf-8")
    for preset in replay_library.CHAT_PRESETS:
        for chunk in preset.chunks:
            assert chunk.content in faq_text, (
                f"预置分块内容不在 FAQ 种子里：{chunk.content}"
            )
            assert f"## {chunk.heading_path[-1]}" in faq_text


def test_chat_presets_cite_legally() -> None:
    """引用序号落在本次候选范围内，回答里的角标与 cited 一一对应。

    候选范围是「相似度分块 + 图谱段落」：融合后顺序确定（向量块在前、图谱段落在后，
    见 `CHAT_PRESETS` 里的说明），预置才敢把 `[N]` 写死。图谱段落必须挂角标——
    它是论断的实际来源，写成裸文本就是「角标和实际不符」。
    """
    settings = get_settings()
    for preset in replay_library.CHAT_PRESETS:
        assert preset.cited, f"预置问题没有引用：{preset.question}"
        assert all(
            settings.graphrag_vector_weight * chunk.score
            > settings.graphrag_graph_weight
            for chunk in preset.chunks
        ), f"图谱段落会插到分块前面，序号假设失效：{preset.question}"
        candidates = len(preset.chunks) + len(preset.passages)
        assert max(preset.cited) <= candidates
        # 引用列表的顺序由正文角标决定（reconcile_answer 以正文为权威）：cited 按
        # 角标在正文里出现的顺序写，接口返回的 markers 才会与它逐项相等。
        inline_in_order = [int(number) for number in re.findall(r"\[(\d+)\]", preset.answer)]
        assert list(dict.fromkeys(inline_in_order)) == list(preset.cited)
        graph_markers = set(range(len(preset.chunks) + 1, candidates + 1))
        assert graph_markers <= set(preset.cited), f"图谱段落未挂角标：{preset.question}"
        # 分块分数全部高于检索阈值（融合前证据分），且严格递减，融合后顺序确定。
        scores = [chunk.score for chunk in preset.chunks]
        assert all(score >= settings.retrieval_score_threshold for score in scores)
        assert scores == sorted(scores, reverse=True)


def test_chat_presets_never_carry_a_customers_portfolio() -> None:
    """回放预置与登录身份无关，因此不许预置任何一位客户的持仓或敞口。

    客服侧是客户身份域，图谱只认登录客户本人（`agent/graph.py` 的 only_customer_id）。
    预置一位客户的持仓，等于让任何登录客户都读到别人的数据（CONTEXT「客户可见视图」）。
    """
    for preset in replay_library.CHAT_PRESETS:
        assert all(
            passage.entity_type != "customer" for passage in preset.passages
        ), f"预置携带了客户数据：{preset.question}"
        assert all(
            entity.get("type") != "customer" for entity in preset.matched_entities
        ), f"预置识别了客户实体：{preset.question}"


def test_analytics_presets_are_valid_readonly_queries() -> None:
    """预置 SQL 通过校验层：只读、只碰语义视图、无多余语句。"""
    for preset in replay_library.ANALYTICS_PRESETS:
        validated = validation.validate_query(preset.sql)
        assert validated.strip().upper().startswith("SELECT")


def test_in_memory_cache_covers_the_redis_subset() -> None:
    cache = InMemoryCache()
    cache.set("k", "v", ex=60)
    assert cache.get("k") == "v"
    assert cache.exists("k") == 1
    cache.expire("k", 60)
    assert cache.delete("k") == 1
    assert cache.get("k") is None
    assert cache.exists("k") == 0

    cache.rpush("list", json.dumps({"role": "user", "content": "a"}))
    cache.rpush("list", json.dumps({"role": "assistant", "content": "b"}))
    assert len(cache.lrange("list", 0, -1)) == 2
    cache.ltrim("list", 1, -1)
    assert cache.lrange("list", 0, -1) == [
        json.dumps({"role": "assistant", "content": "b"})
    ]
    assert cache.publish("event:x", "{}") == 0


def test_ttl_expiry_lazily_evicts_entries() -> None:
    import time

    cache = InMemoryCache()
    cache.set("k", "v", ex=0.01)
    time.sleep(0.03)
    assert cache.get("k") is None


def test_redis_client_serves_in_memory_cache_in_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import redis_client as redis_client_module

    settings = get_settings().model_copy(update={"demo_replay": True})
    monkeypatch.setattr(redis_client_module, "get_settings", lambda: settings)
    first = redis_client_module.redis_client()
    assert isinstance(first, InMemoryCache)
    # 进程级单例：登录写进的会话必须能被下一个请求读到。
    assert redis_client_module.redis_client() is first

    settings_off = get_settings().model_copy(update={"demo_replay": False})
    monkeypatch.setattr(redis_client_module, "get_settings", lambda: settings_off)
    assert isinstance(redis_client_module.redis_client(), redis_lib.Redis)
