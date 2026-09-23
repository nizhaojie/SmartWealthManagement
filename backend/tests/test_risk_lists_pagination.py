"""风控三个列表的分页与排序下推（ADR-0024，`list-pagination` #03）。

预警列表原先是在**前端**对全量结果排序（`sortAlerts`）。分页之后前端手里只有当前页：
排序若不同步下推后端，「按等级（重到轻）」就只在这一页内成立，翻页即乱——而每一页
单看都是排好的，所以这件事只能在这一层钉住。这里断言三件事：

- 响应的形状恒为 `{items, total, page, page_size}`，`total` 是**过滤后**的总数；
- 排序由服务端做出，把三页拼起来仍然整体有序（页内排序会在这里现形）；
- 排序键稳定：时间只有秒精度，同一秒的记录靠兜底键定死先后，顺序不随查询漂。

造数直接写两张读模型表（`fin_risk_alert`、`biz_risk_focus`）：要断的是读侧，不是受理
侧；直接写才能把等级、置信度、时间这些排序键摆成想要的样子、并且两两可分。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, RiskAlert, RiskFocus, WorkOrder, WorkOrderTransition
from app.risk_focus import FOCUS_RISK_ALERT, FOCUS_RISK_INTENT
from app.risk_monitoring.grading import LEVEL_LIGHT, LEVEL_MODERATE, LEVEL_SEVERE
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
CUSTOMER_USERNAME = "wangc1"

ALERTS_PATH = "/api/internal/risk-alerts"
FOCUS_PATH = "/api/internal/risk-focus"
RULES_PATH = "/api/internal/risk-rules"

# 造数落在 2026-03 这个窗口里：与别的用例造出来的记录不重叠，收尾时按窗口清掉。
WINDOW_START = datetime(2026, 3, 1, 9, 0, 0)

# 25 条，刻意凑成「一页装不下、两页有余」。
ROW_COUNT = 25
# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# 前 22 条各占一秒，最后三条挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 22

# 等级轮着来：重度 9 条、中度 8 条、轻度 8 条。三个等级都跨得出两页。
LEVELS = (LEVEL_SEVERE, LEVEL_MODERATE, LEVEL_LIGHT)

# 种子里的风控规则条数。
SEEDED_RULE_COUNT = 20


def _level(index: int) -> str:
    return LEVELS[index % len(LEVELS)]


def _confidence(index: int) -> Decimal:
    """`(index * 7) % 25` 在 0..24 上每个值恰好取到一次，置信度因此两两不同。

    并列会让「按置信度排序」的断言退化成「随便一种并列顺序」——兜底键自己另有用例。
    """
    return Decimal((index * 7) % ROW_COUNT + 1) / Decimal(100)


def _created_at(index: int) -> datetime:
    return WINDOW_START + timedelta(seconds=min(index, SAME_SECOND_FROM))


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == CUSTOMER_USERNAME))
    assert value is not None
    return int(value)


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": RISK_OFFICER_USERNAME, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _purge(engine) -> None:
    """把两张读模型表清空。

    工单先删：`biz_work_order.source_alert_id` 指着预警，反过来删会撞外键。
    """
    with OrmSession(engine) as session:
        session.execute(delete(WorkOrderTransition))
        session.execute(delete(WorkOrder))
        session.execute(delete(RiskAlert))
        session.execute(delete(RiskFocus))
        session.commit()


def _add_alerts(engine, *, customer_id: int) -> None:
    with OrmSession(engine) as session:
        for index in range(ROW_COUNT):
            session.add(
                RiskAlert(
                    customer_id=customer_id,
                    alert_type="大额转账",
                    alert_level=_level(index),
                    confidence=_confidence(index),
                    rule_codes=["R001"],
                    rule_hits=[],
                    trigger_detail=f"用例造数 {index}",
                    transaction_ids=[],
                    status="未处理",
                    create_time=_created_at(index),
                )
            )
        session.commit()


def _add_focus(engine, *, customer_id: int) -> None:
    with OrmSession(engine) as session:
        for index in range(ROW_COUNT):
            session.add(
                RiskFocus(
                    customer_id=customer_id,
                    # 每五条里有一条是高风险意图：筛选项因此能筛出一个确定的总数。
                    focus_type=FOCUS_RISK_INTENT if index % 5 == 0 else FOCUS_RISK_ALERT,
                    severity=_level(index),
                    reason=f"用例造数 {index}",
                    source="pagination-case",
                    trace_id=f"trace-{index}",
                    occurred_at=_created_at(index),
                )
            )
        session.commit()


@pytest.fixture
def seeded_risk_lists(auth_client: TestClient) -> Iterator[None]:
    """本用例的 25 条预警 + 25 条风险关注，跑完清掉。"""
    engine = _engine()
    _purge(engine)
    customer_id = _customer_id(engine)
    _add_alerts(engine, customer_id=customer_id)
    _add_focus(engine, customer_id=customer_id)
    try:
        yield
    finally:
        _purge(engine)
        engine.dispose()


def _get(client: TestClient, path: str, **params) -> dict:
    response = client.get(path, headers=_headers(client), params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_all_pages(client: TestClient, path: str, *, page_size: int, **params) -> dict:
    """把全部页翻一遍，拼成「一次全量读数」：跨页的顺序问题只有拼起来才看得见。"""
    pages = []
    page = 1
    total = None
    while True:
        data = _get(client, path, page=page, page_size=page_size, **params)
        total = data["total"]
        pages.append(data)
        if page * page_size >= data["total"]:
            break
        page += 1
    return {
        "items": [row for data in pages for row in data["items"]],
        "page_sizes": [len(data["items"]) for data in pages],
        "total": total,
    }


def _ids(rows: list[dict]) -> list[int]:
    return [row["id"] for row in rows]


# --- 响应形状与 total 的口径 ---


def test_the_page_shape_is_items_total_page_and_page_size(
    auth_client: TestClient, seeded_risk_lists: None
):
    """三个列表形状一致：只有 `items`/`total`/`page`/`page_size`，没有第二套字段名。"""
    alerts = _get(auth_client, ALERTS_PATH)
    focus = _get(auth_client, FOCUS_PATH)
    rules = _get(auth_client, RULES_PATH)

    for page in (alerts, focus, rules):
        assert set(page) == {"items", "total", "page", "page_size"}
        assert page["page"] == 1
        assert page["page_size"] == DEFAULT_PAGE_SIZE

    assert alerts["total"] == ROW_COUNT
    assert focus["total"] == ROW_COUNT
    assert rules["total"] == SEEDED_RULE_COUNT
    assert len(alerts["items"]) == DEFAULT_PAGE_SIZE


def test_the_total_is_the_filtered_count_not_the_whole_table(
    auth_client: TestClient, seeded_risk_lists: None
):
    """`total` 跟着筛选走：重度 9 条、高风险意图 5 条，都是过滤后的条数。"""
    severe = _get(auth_client, ALERTS_PATH, alert_level=LEVEL_SEVERE)

    assert severe["total"] == 9
    assert {row["alert_level"] for row in severe["items"]} == {LEVEL_SEVERE}

    intent = _get(auth_client, FOCUS_PATH, focus_type=FOCUS_RISK_INTENT)

    assert intent["total"] == 5
    assert {row["focus_type"] for row in intent["items"]} == {FOCUS_RISK_INTENT}


def test_the_alert_list_can_be_narrowed_to_one_customer(
    auth_client: TestClient, seeded_risk_lists: None
):
    """按客户筛：右侧检查器看的是「这位客户的预警」，不能靠前端过滤当前页。"""
    engine = _engine()
    try:
        customer_id = _customer_id(engine)
    finally:
        engine.dispose()

    data = _get(auth_client, ALERTS_PATH, customer_id=customer_id)

    assert data["total"] == ROW_COUNT

    empty = _get(auth_client, ALERTS_PATH, customer_id=999999)
    assert empty == {"items": [], "total": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE}


# --- 翻页不重不漏 ---


def test_turning_the_pages_yields_every_alert_exactly_once(
    auth_client: TestClient, seeded_risk_lists: None
):
    read = _read_all_pages(auth_client, ALERTS_PATH, page_size=10)

    assert read["page_sizes"] == [10, 10, 5]
    assert read["total"] == ROW_COUNT
    # 25 个互不相同的标识：少一个或重一个都会在这里现形。
    assert len(_ids(read["items"])) == len(set(_ids(read["items"]))) == ROW_COUNT
    assert {row["created_at"] for row in read["items"]} == {
        _created_at(index).isoformat() for index in range(ROW_COUNT)
    }


def test_turning_the_pages_yields_every_focus_entry_exactly_once(
    auth_client: TestClient, seeded_risk_lists: None
):
    read = _read_all_pages(auth_client, FOCUS_PATH, page_size=10)

    assert read["page_sizes"] == [10, 10, 5]
    assert read["total"] == ROW_COUNT
    assert len(_ids(read["items"])) == len(set(_ids(read["items"]))) == ROW_COUNT


def test_a_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_risk_lists: None
):
    """越界页给空 `items`，`total` 不变——翻过头不是「没有预警」。"""
    for path, total in (
        (ALERTS_PATH, ROW_COUNT),
        (FOCUS_PATH, ROW_COUNT),
        (RULES_PATH, SEEDED_RULE_COUNT),
    ):
        page = _get(auth_client, path, page=99)

        assert page["items"] == [], path
        assert page["total"] == total, path
        assert page["page"] == 99, path


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_risk_lists: None
):
    page = _get(auth_client, ALERTS_PATH, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE
    assert page["total"] == ROW_COUNT
    assert len(page["items"]) == ROW_COUNT


# --- 排序下推：整体有序与稳定排序键 ---


def test_the_default_order_is_newest_first(
    auth_client: TestClient, seeded_risk_lists: None
):
    page = _get(auth_client, ALERTS_PATH, page_size=100)

    created_at = [row["created_at"] for row in page["items"]]
    assert created_at == sorted(created_at, reverse=True)


def test_the_order_the_officer_picked_is_applied_across_the_page_boundary(
    auth_client: TestClient, seeded_risk_lists: None
):
    """四种排序各自把三页拼起来，仍然整体有序。

    「只在本页内排序」是分页最典型的坏法：单看任何一页都对，翻页即乱。所以这里断的
    是**拼起来之后**的整体顺序，而不是某一页内的顺序。
    """
    keys = {
        "created_desc": (lambda row: row["created_at"], True),
        "confidence_desc": (lambda row: row["confidence"], True),
        "confidence_asc": (lambda row: row["confidence"], False),
    }
    for order_by, (key, reverse) in keys.items():
        read = _read_all_pages(
            auth_client, ALERTS_PATH, page_size=10, order_by=order_by
        )

        values = [key(row) for row in read["items"]]
        assert values == sorted(values, reverse=reverse), order_by
        assert len(values) == ROW_COUNT, order_by


def test_sorting_by_level_puts_the_heaviest_first_and_keeps_paging_ordered(
    auth_client: TestClient, seeded_risk_lists: None
):
    """「按等级（重到轻）」是分页后最容易出错的一处，也是本次验收的那一条。

    等级是中文标签，字典序排出来是「中度 < 轻度 < 重度」，与轻重无关；次序必须显式
    给出（`grading.LEVEL_RANK`）。同级内按时间倒序。
    """
    read = _read_all_pages(auth_client, ALERTS_PATH, page_size=10, order_by="level_desc")

    levels = [row["alert_level"] for row in read["items"]]
    assert levels == [LEVEL_SEVERE] * 9 + [LEVEL_MODERATE] * 8 + [LEVEL_LIGHT] * 8

    for level in LEVELS:
        created_at = [row["created_at"] for row in read["items"] if row["alert_level"] == level]
        assert created_at == sorted(created_at, reverse=True), level


def test_records_within_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_risk_lists: None
):
    """同一秒的记录顺序固定：`create_time` 是秒精度，靠 `id` 兜底把它定死。

    顺序不稳定时，翻页会把同一条记录读两次、另一条谁也读不到——而两页看起来都正常。
    """
    first = _get(auth_client, ALERTS_PATH, page_size=100)
    second = _get(auth_client, ALERTS_PATH, page_size=100)

    assert _ids(first["items"]) == _ids(second["items"])
    assert len({row["created_at"] for row in first["items"][:3]}) == 1


def test_the_focus_list_stays_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_risk_lists: None
):
    read = _read_all_pages(auth_client, FOCUS_PATH, page_size=10)

    occurred_at = [row["occurred_at"] for row in read["items"]]
    assert occurred_at == sorted(occurred_at, reverse=True)

    # 同一秒的三条：读两次拿到的顺序逐字相同，靠的是 `id` 兜底而不是查询计划的偶然。
    first = _get(auth_client, FOCUS_PATH, page_size=100)
    second = _get(auth_client, FOCUS_PATH, page_size=100)
    assert _ids(first["items"]) == _ids(second["items"])


def test_the_rule_list_pages_by_rule_code(
    auth_client: TestClient, seeded_risk_lists: None
):
    """规则按编号升序——编号唯一，这个键本身就是稳定的，不必再补兜底列。"""
    read = _read_all_pages(auth_client, RULES_PATH, page_size=7)

    assert read["page_sizes"] == [7, 7, 6]
    assert read["total"] == SEEDED_RULE_COUNT

    codes = [row["rule_code"] for row in read["items"]]
    assert codes == sorted(codes)
    assert len(set(codes)) == SEEDED_RULE_COUNT


def test_an_unknown_sort_is_reported_as_a_bad_request(
    auth_client: TestClient, seeded_risk_lists: None
):
    """排序方式不在契约里就报错，不静默退回默认：客户端以为换了一种排法，界面看起来
    只是「顺序有点怪」。"""
    response = auth_client.get(
        ALERTS_PATH, headers=_headers(auth_client), params={"order_by": "created_at"}
    )

    assert response.status_code == 400
