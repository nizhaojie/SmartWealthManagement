"""产品筛选的分页（ADR-0024，`list-pagination` #09）。

产品清单的排序键是硬性约束（ADR-0005）：`product_code` 升序，不接受客户端覆盖，
护栏测试 4 断言过「传任何排序参数都无效」。分页在这条固定顺序上切片，这里要补的是
「切片本身不重不漏、越界与钳制符合契约、且这条排序跨页仍然成立」——不是重新验证
护栏本身（那已经在 `test_product_screening.py` 里钉住了）。

造数直接写 `fin_product`：种子库只有 5 只产品，装不满一页（默认页长 10），分页现象
（跨页、越界、钳制）看不见。造出来的这一批用一个专属 `product_type`（种子里不存在
的值）标记，筛选时按它收窄，不与种子的 5 只、也不与别的测试用例混在一起。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, Product, RiskAssessment, SuitabilityDecision
from app.risk_assessment.service import ASSESSOR_TYPE
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
CUSTOMER_USERNAME = "wangc1"
PRODUCTS_PATH = "/api/customer/products"

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# 25 只产品：一页装不下、两页有余。product_type 是种子里不存在的标记值，筛选时用它
# 把这一批与种子的 5 只、以及别的用例造出来的产品分开。
PRODUCT_COUNT = 25
PRODUCT_TYPE_MARKER = "分页用例基金"
CODE_PREFIX = "PAGE"


def _code(index: int) -> str:
    return f"{CODE_PREFIX}{index:04d}"


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_headers(client: TestClient, username: str = CUSTOMER_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _answers_at_option_index(questions: list[dict], option_index: int) -> dict[str, str]:
    return {question["id"]: question["options"][option_index]["id"] for question in questions}


def _submit_c5_assessment(client: TestClient, headers: dict[str, str]) -> None:
    """C5：可购范围覆盖 R1–R5，这一批造数无论哪个等级都不会被适当性过滤掉。"""
    questionnaire = client.get("/api/customer/risk-assessment/questionnaire", headers=headers)
    questions = questionnaire.json()["data"]["questions"]
    submitted = client.post(
        "/api/customer/risk-assessment",
        headers=headers,
        json={"answers": _answers_at_option_index(questions, 3)},
    )
    assert submitted.status_code == 200
    assert submitted.json()["data"]["risk_level"] == "C5"


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(Product).where(Product.product_type == PRODUCT_TYPE_MARKER))
        session.commit()


def _restore_wangc1(engine) -> None:
    """把 `wangc1` 的自测评与画像风险等级还原成种子状态（C1）。

    这份用例借用种子客户来拿到覆盖 R1–R5 的可购范围（提交一次 C5 自测），别的用例
    (如 `test_risk_alert_queries.py`) 依赖 `wangc1` 种子时是 C1——这份状态是跨文件
    共享的，留下 C5 会让后面按执行顺序跑到的用例看到一个改过的种子。
    """
    with OrmSession(engine) as session:
        session.execute(delete(SuitabilityDecision))
        session.execute(delete(RiskAssessment).where(RiskAssessment.assessor_type == ASSESSOR_TYPE))
        customer = session.scalar(select(Customer).where(Customer.username == CUSTOMER_USERNAME))
        assert customer is not None
        profile = session.scalar(
            select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
        )
        assert profile is not None
        profile.risk_level = "C1"
        profile.risk_score = 18
        profile.computed_at = datetime(2022, 3, 16, 9, 0, 0)
        session.commit()


def _add_products(engine) -> None:
    """25 只产品，`product_code` 与预期排序一致；`expected_return` 刻意反着排——

    按收益率排的话这一批的顺序会整个倒过来，分页若不小心漏用了产品代码这条排序键，
    这里立刻就能现出原形（`test_product_screening.py` 的护栏测试断的是同一件事，
    这里只是在分页的形状下再确认一次它没有被绕开）。风险等级在 R1–R5 之间轮着来，
    C5 客户对它们一视同仁地可见。
    """
    risk_levels = ("R1", "R2", "R3", "R4", "R5")
    with OrmSession(engine) as session:
        for index in range(PRODUCT_COUNT):
            session.add(
                Product(
                    product_code=_code(index),
                    product_name=f"分页用例产品{index:02d}",
                    product_type=PRODUCT_TYPE_MARKER,
                    risk_level=risk_levels[index % len(risk_levels)],
                    expected_return=Decimal(str(30 - index)),
                    min_amount=Decimal("100.00"),
                    term_days=0,
                    fund_manager="分页用例基金经理",
                    fee_rate=Decimal("0.1000"),
                    nav=Decimal("1.000000"),
                    status="在售",
                )
            )
        session.commit()


@pytest.fixture
def seeded_products(auth_client: TestClient) -> Iterator[dict[str, str]]:
    """25 只专属产品 + 一位放行到 C5（R1–R5 全可见）的客户请求头。"""
    engine = _engine()
    _purge(engine)
    _restore_wangc1(engine)
    _add_products(engine)
    headers = _customer_headers(auth_client)
    _submit_c5_assessment(auth_client, headers)
    try:
        yield headers
    finally:
        _purge(engine)
        _restore_wangc1(engine)
        engine.dispose()


def _get(client: TestClient, headers: dict[str, str], **params) -> dict:
    params.setdefault("product_type", PRODUCT_TYPE_MARKER)
    response = client.get(PRODUCTS_PATH, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_all_pages(client: TestClient, headers: dict[str, str], *, page_size: int, **params) -> dict:
    """把全部页翻一遍拼成一次全量读数：跨页的重复或遗漏只有拼起来才看得见。"""
    items: list[dict] = []
    page_sizes: list[int] = []
    page = 1
    total = 0
    while True:
        data = _get(client, headers, page=page, page_size=page_size, **params)
        total = data["total"]
        page_sizes.append(len(data["items"]))
        items.extend(data["items"])
        if not data["items"] or page * data["page_size"] >= total:
            break
        page += 1
    return {"items": items, "page_sizes": page_sizes, "total": total}


def _expected_page_sizes(total: int, page_size: int) -> list[int]:
    full, rest = divmod(total, page_size)
    return [page_size] * full + ([rest] if rest else [])


def _codes(rows: list[dict]) -> list[str]:
    return [row["product_code"] for row in rows]


def test_the_screening_serves_the_page_shape(auth_client: TestClient, seeded_products: dict[str, str]):
    page = _get(auth_client, seeded_products)

    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == 1
    assert page["page_size"] == DEFAULT_PAGE_SIZE
    assert page["total"] == PRODUCT_COUNT
    assert len(page["items"]) == DEFAULT_PAGE_SIZE


def test_turning_the_pages_yields_every_product_exactly_once(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    read = _read_all_pages(auth_client, seeded_products, page_size=10)

    assert read["page_sizes"] == _expected_page_sizes(PRODUCT_COUNT, 10)
    assert read["total"] == PRODUCT_COUNT
    codes = _codes(read["items"])
    assert len(codes) == len(set(codes)) == PRODUCT_COUNT


def test_the_screening_stays_ordered_by_product_code_across_the_page_boundary(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    """跨页仍是产品代码升序，且这不是恰好按收益率排出来的（造数时两者刻意反着摆）。"""
    read = _read_all_pages(auth_client, seeded_products, page_size=7)

    codes = _codes(read["items"])
    assert codes == [_code(index) for index in range(PRODUCT_COUNT)]
    assert codes == sorted(codes)
    assert codes != list(reversed(codes))


def test_a_page_beyond_the_last_screening_page_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    page = _get(auth_client, seeded_products, page=99)

    assert page["items"] == []
    assert page["page"] == 99
    assert page["total"] == PRODUCT_COUNT


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    page = _get(auth_client, seeded_products, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE
    assert len(page["items"]) == PRODUCT_COUNT


def test_the_total_is_the_filtered_count_not_the_whole_catalog(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    """再叠加一个客观筛选条件：`total` 随之收窄，且仍是过滤后的总数而不是本页条数。"""
    page = _get(auth_client, seeded_products, min_expected_return="20")

    expected = [index for index in range(PRODUCT_COUNT) if 30 - index >= 20]
    assert page["total"] == len(expected)
    assert len(page["items"]) == min(len(expected), DEFAULT_PAGE_SIZE)
    assert _codes(page["items"]) == [_code(index) for index in expected[:DEFAULT_PAGE_SIZE]]


def test_client_sort_params_do_not_survive_pagination(
    auth_client: TestClient, seeded_products: dict[str, str]
):
    """护栏测试 4 的 seam：分页参数与伪排序参数同时出现时，排序依旧只认产品代码。"""
    page = _get(
        auth_client,
        seeded_products,
        page=2,
        page_size=10,
        sort="expected_return",
        order="desc",
    )

    assert _codes(page["items"]) == [_code(index) for index in range(10, 20)]
