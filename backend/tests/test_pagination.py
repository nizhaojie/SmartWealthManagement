"""列表分页契约的端到端断言（ADR-0024，`list-pagination` #02）。

交易流水是这套契约的试金石：它是唯一「三表扇入 + 内存排序」的列表，`total` 的口径
与稳定排序键都在它身上第一次经受检验——三张表各自切片再合并，或者先切片后排序，
都会在翻页时凭空少一笔，而且不会报错。

断言落在 HTTP 层（seam 1）：参数怎么读、`total` 算谁、越界与超上限怎么办，都是客户端
的翻页控件会直接撞上的行为。造数刻意绕开受理侧（直接写三张表）：这里要断的是读模型，
不是受理校验，受理那一侧有自己的断言（`test_customer_transfer_and_merged_history`）。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Deposit, Product, Transaction, Transfer
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
TRANSACTIONS_PATH = "/api/customer/transactions"

CUSTOMER_MODERATE = "zhangc3"
PRODUCT_R3 = "F000003"

PURCHASE = "申购"
TRANSFER = "转账"
DEPOSIT = "充值"

# 造数落在 2026-02 这个窗口里：种子最晚的历史成交在 2023 年，两者不会混，于是
# 带上日期范围读出来的 `total` 就是本次造出来的条数，不必去数种子给了几笔。
WINDOW_START = datetime(2026, 2, 1, 9, 0, 0)
WINDOW_END = "2026-02-28"
# 共 25 条：9 笔申赎 + 8 笔转账 + 8 笔充值。刻意凑成「一页装不下、两页有余」。
ROW_COUNT = 25
# 前 22 条各占一秒，最后三条（转账、充值、申赎各一）挤在同一秒里——同秒的多表记录
# 是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 22

# 三张表各自的来源序号降序就是同秒时的先后（`_FLOW_*`，数值大的在前）。
SAME_SECOND_ORDER = [DEPOSIT, TRANSFER, PURCHASE]


def _kind_of(index: int) -> str:
    """第 `index` 条记录属于哪一类：三张表轮着来，每一类都够两页之外。"""
    return (PURCHASE, TRANSFER, DEPOSIT)[index % 3]


def _number_of(index: int) -> str:
    prefix = {PURCHASE: "TX", TRANSFER: "TR", DEPOSIT: "DP"}[_kind_of(index)]
    return f"{prefix}20260201{index:04d}"


def _occurred_at(index: int) -> datetime:
    return WINDOW_START + timedelta(seconds=min(index, SAME_SECOND_FROM))


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _add_flow_rows(engine, *, customer_id: int) -> None:
    """直接写三张表：一条记录只落在它自己那张表上（ADR-0019、ADR-0023）。"""
    with OrmSession(engine) as session:
        product_id = session.scalar(select(Product.id).where(Product.product_code == PRODUCT_R3))
        assert product_id is not None
        for index in range(ROW_COUNT):
            number = _number_of(index)
            occurred_at = _occurred_at(index)
            kind = _kind_of(index)
            if kind == PURCHASE:
                session.add(
                    Transaction(
                        transaction_no=number,
                        customer_id=customer_id,
                        product_id=product_id,
                        transaction_type=PURCHASE,
                        amount=Decimal("1000.00"),
                        shares=Decimal("666.6667"),
                        nav=Decimal("1.500000"),
                        fee=Decimal("12.00"),
                        status="已确认",
                        create_time=occurred_at,
                    )
                )
            elif kind == TRANSFER:
                session.add(
                    Transfer(
                        transfer_no=number,
                        customer_id=customer_id,
                        amount=Decimal("1000.00"),
                        payee_name="王五",
                        payee_account="6222020200998877665",
                        create_time=occurred_at,
                    )
                )
            else:
                session.add(
                    Deposit(
                        deposit_no=number,
                        customer_id=customer_id,
                        amount=Decimal("1000.00"),
                        create_time=occurred_at,
                    )
                )
        session.commit()


def _purge(engine, *, customer_id: int) -> None:
    """本次造出来的三张表的行一律清掉，种子那笔 2020 年的申赎不动。"""
    with OrmSession(engine) as session:
        session.execute(
            delete(Transaction).where(
                Transaction.customer_id == customer_id,
                Transaction.create_time >= WINDOW_START,
            )
        )
        session.execute(
            delete(Transfer).where(
                Transfer.customer_id == customer_id, Transfer.create_time >= WINDOW_START
            )
        )
        session.execute(
            delete(Deposit).where(
                Deposit.customer_id == customer_id, Deposit.create_time >= WINDOW_START
            )
        )
        session.commit()


@pytest.fixture
def seeded_flow_rows(auth_client: TestClient) -> Iterator[None]:
    """本次造数活到用例结束：25 条流水落在 `WINDOW_START` 之后的窗口里。"""
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER_MODERATE)
    _purge(engine, customer_id=customer_id)
    _add_flow_rows(engine, customer_id=customer_id)
    try:
        yield
    finally:
        _purge(engine, customer_id=customer_id)
        engine.dispose()


def _page(client: TestClient, **params) -> dict:
    """读一页流水。不带参数时用上日期窗口，把种子那笔历史成交排除在外。"""
    query = {"start_date": "2026-02-01", "end_date": WINDOW_END, **params}
    response = client.get(
        TRANSACTIONS_PATH, headers=_headers(client, CUSTOMER_MODERATE), params=query
    )
    assert response.status_code == 200
    return response.json()["data"]


def _numbers(page: dict) -> list[str]:
    return [row["transaction_no"] for row in page["items"]]


def test_the_default_page_is_ten_and_the_total_counts_everything(
    auth_client: TestClient, seeded_flow_rows: None
):
    """响应的形状只有 `{items, total, page, page_size}` 这一套（旧的 `transactions` 不并存）。

    默认页长 10、页码从 1 起，`total` 是过滤后的总条数而不是本页条数。
    """
    page = _page(auth_client)

    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == 1
    assert page["page_size"] == 10
    assert page["total"] == ROW_COUNT
    assert len(page["items"]) == 10


def test_turning_the_pages_yields_every_record_exactly_once(
    auth_client: TestClient, seeded_flow_rows: None
):
    """三页翻完不重不漏：并集是全部 25 条，两两不相交，`total` 每页都一样。

    三张表各自切片再合并，或者先切片后排序，都会在这里少一笔——而那时页面上看起来
    仍然「正常」，只是有一笔记录谁也翻不到。
    """
    pages = [_page(auth_client, page=number, page_size=10) for number in (1, 2, 3)]

    assert [len(page["items"]) for page in pages] == [10, 10, 5]
    assert {page["total"] for page in pages} == {ROW_COUNT}

    collected = [_number_of(index) for index in range(ROW_COUNT)]
    seen = [number for page in pages for number in _numbers(page)]
    assert set(seen) == set(collected)
    assert len(seen) == len(set(seen)) == ROW_COUNT


def test_the_records_stay_sorted_across_the_page_boundary(
    auth_client: TestClient, seeded_flow_rows: None
):
    """排序跨页成立：把三页拼起来，成交时间仍然一路倒序。

    「只在本页内排序」是分页最典型的坏法：单看任何一页都对，翻页即乱。
    """
    traded_at = [
        row["traded_at"]
        for number in (1, 2, 3)
        for row in _page(auth_client, page=number, page_size=10)["items"]
    ]

    assert traded_at == sorted(traded_at, reverse=True)


def test_records_within_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_flow_rows: None
):
    """同一秒的记录顺序固定：成交时间是秒精度，兜底键把它定死。

    最后三条（转账、充值、申赎各一）挤在同一秒里：它们跨在排序键的第一位上分不出
    先后，靠「来源序号」兜底——数值大的在前。读两次拿到的顺序必须逐字相同。
    """
    first = _page(auth_client, page_size=100)
    second = _page(auth_client, page_size=100)

    assert _numbers(first) == _numbers(second)
    assert [row["transaction_type"] for row in first["items"][:3]] == SAME_SECOND_ORDER
    assert len({row["traded_at"] for row in first["items"][:3]}) == 1


def test_the_total_is_the_filtered_count_not_the_three_tables_together(
    auth_client: TestClient, seeded_flow_rows: None
):
    """筛一类时的 `total` 是那一类的条数：类型筛选决定读哪几张表，`total` 跟着走。"""
    transfers = _page(auth_client, transaction_type=TRANSFER)

    assert transfers["total"] == 8
    assert {row["transaction_type"] for row in transfers["items"]} == {TRANSFER}
    assert len(transfers["items"]) == 8


def test_a_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_flow_rows: None
):
    """越界页给空 `items`，`total` 不变——翻过头不是「没有流水」。"""
    page = _page(auth_client, page=99)

    assert page["items"] == []
    assert page["total"] == ROW_COUNT
    assert page["page"] == 99


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_flow_rows: None
):
    """页长超上限是钳制到 100，而不是报错：客户端多要几行不该让翻页整个失效。"""
    page = _page(auth_client, page_size=1000)

    assert page["page_size"] == 100
    assert page["total"] == ROW_COUNT
    assert len(page["items"]) == ROW_COUNT
