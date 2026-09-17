"""画像置信度的综合重排与周期校准（Seam 1）。

两件事在这一层被验证：

- 同一批画像标签在「产品推荐」与「风险研判」两个场景下排出不同先后，且低分标签不被丢弃；
- 周期校准按**显式传入的时间基准**（ADR-0011）重算置信度、标记过期标签，可手工触发。

校准会改全库的标签与画像汇总分，所以每个用例前后都对这两张表做快照/还原，避免把状态
泄漏给其它测试模块（其它模块也在用同一个测试库）。
"""

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.customer_profile import calibration
from app.db.models import Customer, CustomerProfile, ProfileTag, ProfileTagConflict
from app.main import app
from app.settings import get_settings

EMPLOYEE_USERNAME = "advisor1"
SEEDED_PASSWORD = "Test@1234"

SCENARIO_PRODUCT = "product_recommendation"
SCENARIO_RISK = "risk_analysis"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _session():
    """借道 FastAPI 的依赖覆盖拿到与请求同一个测试库的会话。"""
    from app.db.session import get_session

    override = app.dependency_overrides[get_session]
    iterator = override()
    return iterator, next(iterator)


def _internal_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _insert_customer_with_tags(*, username: str, tags: list[dict]) -> int:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    try:
        with OrmSession(engine) as session:
            customer = Customer(
                username=username,
                password_hash="x",
                real_name=f"客户{username}",
                id_number=f"{uuid.uuid4().int % 10**17:017d}X",
                phone="13900000009",
                customer_level="普通",
                status="正常",
                opened_at=datetime(2024, 1, 1, 10, 0, 0),
            )
            session.add(customer)
            session.flush()
            session.add(
                CustomerProfile(
                    customer_id=customer.id,
                    risk_level="C3",
                    risk_score=50,
                    investment_experience="1-3年",
                    annual_income_range="10-30万",
                    total_assets=Decimal("80000.00"),
                    target_allocation={"股票": 40, "债券": 40, "现金": 20, "另类": 0},
                    product_preference={"基金": ["混合基金"]},
                    confidence_score=Decimal("0.80"),
                    computed_at=datetime(2026, 1, 1, 9, 0, 0),
                )
            )
            for tag in tags:
                session.add(ProfileTag(customer_id=customer.id, **tag))
            session.commit()
            return customer.id
    finally:
        engine.dispose()


def _delete_customer(customer_id: int) -> None:
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    try:
        with OrmSession(engine) as session:
            session.execute(delete(ProfileTag).where(ProfileTag.customer_id == customer_id))
            session.execute(
                delete(ProfileTagConflict).where(ProfileTagConflict.customer_id == customer_id)
            )
            session.execute(
                delete(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
            )
            session.execute(delete(Customer).where(Customer.id == customer_id))
            session.commit()
    finally:
        engine.dispose()


@pytest.fixture
def _restore_calibration_state() -> Iterator[None]:
    """快照/还原校准会触碰的两张表：标签的过期标记与画像的汇总置信度。"""
    settings = get_settings()
    engine = create_engine(settings.test_database_url)
    with OrmSession(engine) as session:
        tag_state = {
            row.id: row.expired for row in session.scalars(select(ProfileTag))
        }
        profile_state = {
            row.customer_id: row.confidence_score
            for row in session.scalars(select(CustomerProfile))
        }
    try:
        yield
    finally:
        with OrmSession(engine) as session:
            for tag in session.scalars(select(ProfileTag)):
                if tag.id in tag_state:
                    tag.expired = tag_state[tag.id]
            for profile in session.scalars(select(CustomerProfile)):
                if profile.customer_id in profile_state:
                    profile.confidence_score = profile_state[profile.customer_id]
            session.commit()
        engine.dispose()


# --- 综合重排：不同场景配置产生不同排序 -------------------------------------


def test_profile_tags_are_ordered_differently_under_two_scenarios(auth_client: TestClient):
    now = _utcnow()
    customer_id = _insert_customer_with_tags(
        username="rerankscenario",
        tags=[
            # 与查询高度相关，但很旧、基础分低。
            {
                "tag_key": "investment_experience",
                "tag_value": "无",
                "source": "AI对话提取",
                "evidence_count": 0,
                "observed_at": now - timedelta(days=800),
            },
            # 与查询不相关，但很新、基础分高。
            {
                "tag_key": "annual_income_range",
                "tag_value": "100万以上",
                "source": "风评问卷",
                "evidence_count": 0,
                "observed_at": now,
            },
        ],
    )
    try:
        product = auth_client.get(
            f"/api/internal/customers/{customer_id}/profile",
            params={"scenario": SCENARIO_PRODUCT, "query": "投资经验"},
            headers=_internal_headers(auth_client),
        )
        risk = auth_client.get(
            f"/api/internal/customers/{customer_id}/profile",
            params={"scenario": SCENARIO_RISK, "query": "投资经验"},
            headers=_internal_headers(auth_client),
        )

        assert product.status_code == 200
        assert risk.status_code == 200
        product_tags = product.json()["data"]["tags"]
        risk_tags = risk.json()["data"]["tags"]

        def keys(tags: list[dict]) -> list[str]:
            return [tag["key"] for tag in tags]

        assert keys(product_tags) == ["investment_experience", "annual_income_range"]
        assert keys(risk_tags) == ["annual_income_range", "investment_experience"]
        # 输出是排序不是过滤：两个场景都返回全部标签。
        assert len(product_tags) == 2
        assert len(risk_tags) == 2
        # 每个标签带上重排得分与五因子贡献，便于解释排序为什么是这样。
        assert product_tags[0]["rerank_score"] > product_tags[1]["rerank_score"]
        assert len(product_tags[0]["rerank_factors"]) == 5
    finally:
        _delete_customer(customer_id)


def test_profile_read_keeps_write_order_when_no_scenario_is_asked_for(auth_client: TestClient):
    now = _utcnow()
    customer_id = _insert_customer_with_tags(
        username="rerankdefault",
        tags=[
            {
                "tag_key": "investment_experience",
                "tag_value": "无",
                "source": "AI对话提取",
                "evidence_count": 0,
                "observed_at": now - timedelta(days=800),
            },
            {
                "tag_key": "annual_income_range",
                "tag_value": "100万以上",
                "source": "风评问卷",
                "evidence_count": 0,
                "observed_at": now,
            },
        ],
    )
    try:
        response = auth_client.get(
            f"/api/internal/customers/{customer_id}/profile",
            headers=_internal_headers(auth_client),
        )
        tags = response.json()["data"]["tags"]
        assert [tag["key"] for tag in tags] == ["investment_experience", "annual_income_range"]
        assert "rerank_score" not in tags[0]
    finally:
        _delete_customer(customer_id)


def test_unknown_scenario_is_rejected(auth_client: TestClient):
    response = auth_client.get(
        "/api/internal/customers/1/profile",
        params={"scenario": "不存在的场景"},
        headers=_internal_headers(auth_client),
    )
    assert response.status_code == 400
    assert response.json()["message"] == "未知的重排场景"


def test_rerank_scenario_requires_internal_identity(auth_client: TestClient):
    response = auth_client.get("/api/internal/customers/1/profile", params={"scenario": SCENARIO_RISK})
    assert response.status_code == 401


# --- 周期校准：显式时间基准、标记过期标签 -----------------------------------


def test_calibration_marks_only_the_tags_decayed_below_the_threshold(
    auth_client: TestClient, _restore_calibration_state: None
):
    now = _utcnow()
    customer_id = _insert_customer_with_tags(
        username="calibthreshold",
        tags=[
            {
                "tag_key": "investment_experience",
                "tag_value": "0-1年",
                "source": "理财顾问手工修正",
                "evidence_count": 0,
                "observed_at": now,
                "reason": "访谈确认",
            },
            {
                "tag_key": "annual_income_range",
                "tag_value": "10万以下",
                "source": "默认值",
                "evidence_count": 0,
                "observed_at": now - timedelta(days=3 * 365),
            },
        ],
    )
    try:
        iterator, session = _session()
        try:
            report = calibration.recalibrate(session, now=now, expiry_threshold=0.4)
        finally:
            iterator.close()

        assert report["basis"] == now.isoformat()
        assert report["expiry_threshold"] == 0.4

        iterator, session = _session()
        try:
            tags = {
                tag.tag_key: tag
                for tag in session.scalars(
                    select(ProfileTag).where(ProfileTag.customer_id == customer_id)
                )
            }
            assert tags["investment_experience"].expired is False
            assert tags["annual_income_range"].expired is True
        finally:
            iterator.close()
    finally:
        _delete_customer(customer_id)


def test_the_same_tag_expires_or_not_depending_on_the_passed_basis(
    auth_client: TestClient, _restore_calibration_state: None
):
    # 「客户自述」初值 0.55：按观测时刻算还在阈值之上，按一年后算已衰减到 0.35。
    observed_at = datetime(2025, 1, 1, 12, 0, 0)
    customer_id = _insert_customer_with_tags(
        username="calibbasis",
        tags=[
            {
                "tag_key": "investment_experience",
                "tag_value": "1-3年",
                "source": "客户自述",
                "evidence_count": 0,
                "observed_at": observed_at,
            }
        ],
    )
    try:
        iterator, session = _session()
        try:
            calibration.recalibrate(session, now=observed_at, expiry_threshold=0.4)
        finally:
            iterator.close()

        iterator, session = _session()
        try:
            assert session.scalar(
                select(ProfileTag.expired).where(ProfileTag.customer_id == customer_id)
            ) is False
        finally:
            iterator.close()

        # 同一个标签、同一条记录，只把基准推后一年就过期了——若校准内部读时钟，
        # 这一步不可能得到「恰好过期」的结果。
        iterator, session = _session()
        try:
            calibration.recalibrate(
                session, now=observed_at + timedelta(days=365), expiry_threshold=0.4
            )
        finally:
            iterator.close()

        iterator, session = _session()
        try:
            assert session.scalar(
                select(ProfileTag.expired).where(ProfileTag.customer_id == customer_id)
            ) is True
            assert session.scalar(
                select(CustomerProfile.confidence_score).where(
                    CustomerProfile.customer_id == customer_id
                )
            ) == Decimal("0.35")
        finally:
            iterator.close()
    finally:
        _delete_customer(customer_id)


def test_recalibration_resets_the_expiry_flag_of_a_reconfirmed_tag(
    auth_client: TestClient, _restore_calibration_state: None
):
    now = _utcnow()
    customer_id = _insert_customer_with_tags(
        username="calibrewrite",
        tags=[
            {
                "tag_key": "investment_experience",
                "tag_value": "0-1年",
                "source": "默认值",
                "evidence_count": 0,
                "observed_at": now - timedelta(days=3 * 365),
            }
        ],
    )
    try:
        iterator, session = _session()
        try:
            calibration.recalibrate(session, now=now, expiry_threshold=0.4)
        finally:
            iterator.close()

        assert (
            auth_client.get(
                f"/api/internal/customers/{customer_id}/profile",
                headers=_internal_headers(auth_client),
            )
            .json()["data"]["tags"][0]["expired"]
            is True
        )

        # 重新确认这条标签：它换成了顾问修正，过期标记随之复位。
        write = auth_client.put(
            f"/api/internal/customers/{customer_id}/profile/tags",
            headers=_internal_headers(auth_client),
            json={
                "tag_key": "investment_experience",
                "value": "3-5年",
                "source": "理财顾问手工修正",
                "reason": "访谈确认",
            },
        )
        assert write.status_code == 200
        assert write.json()["data"]["tags"][0]["expired"] is False
    finally:
        _delete_customer(customer_id)


def test_calibrate_endpoint_is_manually_triggerable_and_reports_the_run(
    auth_client: TestClient, _restore_calibration_state: None
):
    now = _utcnow()
    customer_id = _insert_customer_with_tags(
        username="calibendpoint",
        tags=[
            {
                "tag_key": "annual_income_range",
                "tag_value": "10万以下",
                "source": "默认值",
                "evidence_count": 0,
                "observed_at": now - timedelta(days=3 * 365),
            }
        ],
    )
    try:
        headers = _internal_headers(auth_client)
        response = auth_client.post("/api/internal/profiles/calibrate", headers=headers)
        assert response.status_code == 200
        report = response.json()["data"]
        assert report["basis"]
        assert report["expired_tags"] >= 1
        assert report["customers"] >= 1

        # 校准之后画像面板读到的是标记为过期、且置信度按时间衰减后的值。
        profile = auth_client.get(
            f"/api/internal/customers/{customer_id}/profile", headers=headers
        ).json()["data"]
        tag = next(item for item in profile["tags"] if item["key"] == "annual_income_range")
        assert tag["expired"] is True
        assert tag["confidence"] == 0.0

        # 同一基准重复触发不改变结果（幂等）。
        again = auth_client.post("/api/internal/profiles/calibrate", headers=headers)
        assert again.status_code == 200
        assert again.json()["data"]["expired_tags"] == report["expired_tags"]
    finally:
        _delete_customer(customer_id)


def test_calibrate_endpoint_requires_internal_identity(auth_client: TestClient):
    assert auth_client.post("/api/internal/profiles/calibrate").status_code == 401
