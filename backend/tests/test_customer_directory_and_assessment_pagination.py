"""客户目录与风险测评历史的分页（ADR-0024，`list-pagination` #04）。

客户目录是分页改造里最高危的一处：它原先一次拉全量客户，还要顺带拉一份**全量画像
映射**（`select(CustomerProfile).all()`）。分页只切客户那一半是不够的——画像得跟着页
走，否则响应看起来完全正常（`items` 与 `total` 都对得上），只是每一次翻页都顺手把整张
画像表读了一遍。所以这里除了断形状与翻页，还要断「画像只读了页内那几行」。

关键字筛选也落在这一层：目录分页之后前端手里只有一页，在浏览器里过滤只过滤得动这一
页——「共 N 条」会变成「这一页里筛出了几条」，而两个数字看起来都像是真的。

测评历史同理，补的是「时间倒序 + 标识兜底」：`assessment_date` 只有日精度，同一天提交
的多次评测靠 `id` 兜底定死先后，否则翻页会在两页之间来回跳。

造数直接写库（`sys_customer` / `fin_customer_profile` / `fin_risk_assessment`）：这里要
断的是读侧，不是开户与测评受理；直接写才能把开户时间摆成「前 22 位各占一秒、最后三位
挤在同一秒」这种排序兜底唯一会暴露的样子。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, event, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, CustomerProfile, RiskAssessment
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
# 理财顾问不受归属收窄，拿到的是全量目录（`app.customer_scope`）。
ADVISOR_USERNAME = "advisor1"

CUSTOMERS_PATH = "/api/internal/customers"
ASSESSMENTS_PATH = "/api/internal/customers/{customer_id}/risk-assessments"

PROFILE_TABLE = "fin_customer_profile"
CUSTOMER_TABLE = "sys_customer"

# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# 25 位客户：刻意凑成「一页装不下、两页有余」。
CUSTOMER_COUNT = 25
# 开户时间落在 2026-04：种子里最晚的一笔开户在 2022-03，两者不会混。
WINDOW_START = datetime(2026, 4, 1, 9, 0, 0)
# 前 22 位各占一秒，最后三位挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 22

# 关键字命中本次造出来的全部客户：姓名与账号两种匹配都要能筛到。所有造数与断言都
# 带上这两个前缀，目录里别人的客户（种子、别的用例留下的）因此不会混进来。
NAME_PREFIX = "分页用例"
USERNAME_PREFIX = "pagecase"

# 25 次测评，日期落在 2026-05：前 22 天一天一次，最后三次挤在同一天。
ASSESSMENT_COUNT = 25
ASSESSMENT_START = date(2026, 5, 1)
SAME_DAY_FROM = 22

# 客户分层与画像等级各自轮着来：页内画像映射取错行会直接体现在 `risk_level` 上。
LEVELS = ("普通", "金卡", "白金", "钻石", "私行")
RISK_LEVELS = ("C1", "C2", "C3", "C4", "C5")


def _username(index: int) -> str:
    return f"{USERNAME_PREFIX}{index:02d}"


def _levels(index: int) -> tuple[str, str]:
    return LEVELS[index % len(LEVELS)], RISK_LEVELS[index % len(RISK_LEVELS)]


def _opened_at(index: int) -> datetime:
    """开户时间与标识**反着来**：标识最小的那位开得最晚，最后三位挤在同一秒。

    两个排序键都按标识来的话，这批数据的期望顺序恰好也一样——那样就测不出「时间才是
    第一位排序键、标识只是兜底」。反过来摆，两个键各自的作用才分得开。
    """
    return WINDOW_START + timedelta(seconds=SAME_SECOND_FROM - min(index, SAME_SECOND_FROM))


def _assessment_date(index: int) -> date:
    return ASSESSMENT_START + timedelta(days=min(index, SAME_DAY_FROM))


# 同秒那一组在「最新的在前」里的先后：写入顺序即标识顺序，兜底键是标识倒序。
SAME_SECOND_ORDER = [24, 23, 22]
# 目录的期望顺序：开户时间倒序（标识 0 开得最晚），最后三位同秒、按标识倒序兜底。
EXPECTED_ORDER = [*range(SAME_SECOND_FROM), *SAME_SECOND_ORDER]


def _engine():
    return create_engine(get_settings().test_database_url)


def _headers(client: TestClient, username: str = ADVISOR_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


@contextmanager
def _captured_profile_reads() -> Iterator[list[dict[str, Any]]]:
    """收集本次请求里打到画像表的语句参数。

    监听挂在 `Engine` 这一类上：测试的引擎由 `auth_client` 夹具在内部建出来，测试拿不到
    它的引用，而「多读了整张画像表」恰好只体现在那条语句的绑定参数里（没有 `IN`，或者
    `IN` 里不是这一页的客户）——响应本身看不出这件事。
    """

    def _record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        if PROFILE_TABLE in statement:
            captured.append(dict(parameters or {}))

    captured: list[dict[str, Any]] = []
    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield captured
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def _purge_stale(engine) -> None:
    """清掉上一次运行中断留下的同名造数。

    前缀是固定的，留下的一份会让「关键字命中 25 条」变成 26 条——而那个多出来的客户
    看起来和别的一模一样。先清后造，断言才有一个确定的数。
    """
    with OrmSession(engine) as session:
        stale = list(
            session.scalars(
                select(Customer.id).where(Customer.username.like(f"{USERNAME_PREFIX}%"))
            )
        )
        if stale:
            session.execute(delete(RiskAssessment).where(RiskAssessment.customer_id.in_(stale)))
            session.execute(
                delete(CustomerProfile).where(CustomerProfile.customer_id.in_(stale))
            )
            session.execute(delete(Customer).where(Customer.id.in_(stale)))
            session.commit()


def _add_customers(engine) -> list[int]:
    """25 位客户，各自带一行画像。返回按写入顺序（即开户先后）排列的客户标识。"""
    with OrmSession(engine) as session:
        template = session.scalar(select(Customer).where(Customer.username == "wangc1"))
        assert template is not None
        created: list[int] = []
        for index in range(CUSTOMER_COUNT):
            level, risk_level = _levels(index)
            customer = Customer(
                username=_username(index),
                password_hash=template.password_hash,
                real_name=f"{NAME_PREFIX}{index:02d}",
                id_number=f"11010119900101{index:04d}",
                phone=f"1390000{index:04d}",
                customer_level=level,
                status="正常",
                # 不归任何客户经理：目录收窄（客户经理只看自己名下）不受这批造数影响。
                manager_id=None,
                opened_at=_opened_at(index),
            )
            session.add(customer)
            session.flush()
            session.add(
                CustomerProfile(
                    customer_id=customer.id,
                    risk_level=risk_level,
                    risk_score=index,
                    investment_experience="1-3年",
                    annual_income_range="10-30万",
                    total_assets=Decimal("80000.00"),
                    target_allocation={"股票": 40, "债券": 40, "现金": 20, "另类": 0},
                    product_preference={"基金": ["混合基金"]},
                    confidence_score=Decimal("0.80"),
                    computed_at=WINDOW_START,
                )
            )
            created.append(customer.id)
        session.commit()
        return created


def _add_assessments(engine, *, customer_id: int) -> list[int]:
    with OrmSession(engine) as session:
        created: list[int] = []
        for index in range(ASSESSMENT_COUNT):
            row = RiskAssessment(
                customer_id=customer_id,
                assessment_date=_assessment_date(index),
                total_score=index,
                risk_level=RISK_LEVELS[index % len(RISK_LEVELS)],
                answers=[],
                assessor_type="客户自测",
                valid_until=date(2027, 5, 1),
            )
            session.add(row)
            session.flush()
            created.append(row.id)
        session.commit()
        return created


def _purge(engine, *, customer_ids: list[int], assessment_ids: list[int]) -> None:
    with OrmSession(engine) as session:
        if assessment_ids:
            session.execute(delete(RiskAssessment).where(RiskAssessment.id.in_(assessment_ids)))
        if customer_ids:
            session.execute(
                delete(CustomerProfile).where(CustomerProfile.customer_id.in_(customer_ids))
            )
            session.execute(delete(Customer).where(Customer.id.in_(customer_ids)))
        session.commit()


@pytest.fixture
def seeded_directory(auth_client: TestClient) -> Iterator[list[int]]:
    """本次造出来的 25 位客户（各自带画像），以及第一位名下的 25 次测评。"""
    engine = _engine()
    _purge_stale(engine)
    customer_ids = _add_customers(engine)
    assessment_ids = _add_assessments(engine, customer_id=customer_ids[0])
    try:
        yield customer_ids
    finally:
        _purge(engine, customer_ids=customer_ids, assessment_ids=assessment_ids)
        engine.dispose()


def _get(client: TestClient, path: str, **params) -> dict:
    response = client.get(path, headers=_headers(client), params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _directory(client: TestClient, **params) -> dict:
    """读一页目录。带上账号前缀，这一页里就只会有本用例造出来的那 25 位。"""
    return _get(client, CUSTOMERS_PATH, keyword=USERNAME_PREFIX, **params)


def _read_all_pages(client: TestClient, path: str, *, page_size: int, **params) -> dict:
    """把全部页翻一遍，拼成「一次全量读数」：跨页的顺序问题只有拼起来才看得见。"""
    items: list[dict] = []
    page_sizes: list[int] = []
    page = 1
    total = 0
    while True:
        data = _get(client, path, page=page, page_size=page_size, **params)
        total = data["total"]
        page_sizes.append(len(data["items"]))
        items.extend(data["items"])
        if not data["items"] or page * data["page_size"] >= total:
            break
        page += 1
    return {"items": items, "page_sizes": page_sizes, "total": total}


def _expected_page_sizes(total: int, page_size: int) -> list[int]:
    """每页都装满，只有最后一页可能不满——翻页不重不漏的前提。"""
    full, rest = divmod(total, page_size)
    return [page_size] * full + ([rest] if rest else [])


def _ids(rows: list[dict]) -> list[int]:
    return [row["id"] for row in rows]


def _bound_customer_ids(parameters: dict[str, Any]) -> set[int]:
    """从一条语句的绑定参数里取出 `customer_id` 的值（`IN` 展开后是列表）。"""
    ids: set[int] = set()
    for key, value in parameters.items():
        if "customer_id" not in key:
            continue
        for item in value if isinstance(value, (list, tuple, set)) else [value]:
            ids.add(int(item))
    return ids


# --- 客户目录：形状与 total 的口径 ---


def test_the_directory_serves_the_page_shape(auth_client: TestClient, seeded_directory: list[int]):
    """形状只有 `{items, total, page, page_size}` 这一套（旧的裸数组不并存）。"""
    page = _get(auth_client, CUSTOMERS_PATH)

    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == 1
    assert page["page_size"] == DEFAULT_PAGE_SIZE
    assert len(page["items"]) == DEFAULT_PAGE_SIZE
    assert page["total"] >= CUSTOMER_COUNT


def test_the_directory_items_carry_the_risk_level_of_their_own_profile(
    auth_client: TestClient, seeded_directory: list[int]
):
    """页内画像映射按客户对上号：取错行会在这里现形（`risk_level` 是画像里唯一的字段）。"""
    page = _directory(auth_client, page_size=MAX_PAGE_SIZE)

    assert {
        row["username"]: row["risk_level"] for row in page["items"]
    } == {_username(index): _levels(index)[1] for index in range(CUSTOMER_COUNT)}


def test_only_the_profiles_of_the_current_page_are_read(
    auth_client: TestClient, seeded_directory: list[int]
):
    """画像只读页内客户的那几行。

    这是本次改造里最容易漏的一条：响应完全正确（`items` 是这一页、`total` 是总数），
    多读的那部分一个字都不会出现在响应里，只会在客户变多时变成每一次翻页的开销。
    """
    with _captured_profile_reads() as reads:
        page = _get(auth_client, CUSTOMERS_PATH, page=2, page_size=5)

    page_ids = set(_ids(page["items"]))
    assert len(page_ids) == 5

    assert reads, "客户目录这一路必须为画像发一次查询"
    bound = set().union(*(_bound_customer_ids(parameters) for parameters in reads))
    assert bound == page_ids


def test_turning_the_pages_yields_every_customer_exactly_once(
    auth_client: TestClient, seeded_directory: list[int]
):
    """翻页不重不漏：本页之外还有别的客户，谁也漏不掉、谁也不出现两次。"""
    read = _read_all_pages(auth_client, CUSTOMERS_PATH, page_size=10)

    assert read["page_sizes"] == _expected_page_sizes(read["total"], 10)
    assert read["total"] >= CUSTOMER_COUNT
    ids = _ids(read["items"])
    assert len(ids) == len(set(ids)) == read["total"]


def test_the_directory_is_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_directory: list[int]
):
    """开户时间倒序跨页成立，且标识只是兜底。

    只看本页是排好的、翻页即乱的那种坏法在这里现形；而造数把「标识最小」与「开得最晚」
    摆在一起，所以按标识倒序排也编不出这个顺序——时间必须是第一位的排序键。
    """
    read = _read_all_pages(
        auth_client, CUSTOMERS_PATH, page_size=10, keyword=USERNAME_PREFIX
    )

    assert read["total"] == CUSTOMER_COUNT
    assert [row["username"] for row in read["items"]] == [
        _username(index) for index in EXPECTED_ORDER
    ]


def test_customers_opened_in_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_directory: list[int]
):
    """同一秒开户的客户顺序固定：`opened_at` 是秒精度，靠 `id` 兜底定死先后。

    最后三位挤在同一秒里（下面直接查库确认），读两次的顺序必须逐字相同——顺序不稳定
    时，翻页会把某一位读两次、另一位谁也读不到，而两页看起来都正常。
    """
    first = _directory(auth_client, page_size=MAX_PAGE_SIZE)
    second = _directory(auth_client, page_size=MAX_PAGE_SIZE)

    assert _ids(first["items"]) == _ids(second["items"])
    assert [row["username"] for row in first["items"][-3:]] == [
        _username(index) for index in SAME_SECOND_ORDER
    ]

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            opened_at = list(
                session.scalars(
                    select(Customer.opened_at).where(
                        Customer.username.in_(
                            [_username(index) for index in SAME_SECOND_ORDER]
                        )
                    )
                )
            )
    finally:
        engine.dispose()
    assert len(set(opened_at)) == 1


def test_the_total_is_the_filtered_count_not_the_whole_table(
    auth_client: TestClient, seeded_directory: list[int]
):
    """关键字筛掉的客户不计入 `total`：`total` 是过滤后的总数，不是这一页的条数。"""
    by_name = _get(auth_client, CUSTOMERS_PATH, keyword=NAME_PREFIX)
    by_username = _get(auth_client, CUSTOMERS_PATH, keyword=USERNAME_PREFIX)

    assert by_name["total"] == by_username["total"] == CUSTOMER_COUNT
    assert len(by_username["items"]) == DEFAULT_PAGE_SIZE


def test_the_keyword_is_filtered_on_the_server_so_paging_stays_consistent(
    auth_client: TestClient, seeded_directory: list[int]
):
    """筛完再翻页：第 2 页仍是筛选结果里的第 2 页。

    只过滤当前页时，这里会拿到 25 条命中里的第 21–25 条——看着像「筛出来就这几条」，
    而筛掉的 20 条也在同一批数据里。
    """
    read = _read_all_pages(
        auth_client, CUSTOMERS_PATH, page_size=10, keyword=NAME_PREFIX
    )

    assert read["page_sizes"] == [10, 10, 5]
    assert read["total"] == CUSTOMER_COUNT
    assert {row["username"] for row in read["items"]} == {
        _username(index) for index in range(CUSTOMER_COUNT)
    }


def test_a_keyword_that_matches_nobody_returns_an_empty_first_page(
    auth_client: TestClient, seeded_directory: list[int]
):
    page = _get(auth_client, CUSTOMERS_PATH, keyword="查无此人")

    assert page == {"items": [], "total": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE}


def test_a_percent_sign_is_searched_as_a_character_not_a_wildcard(
    auth_client: TestClient, seeded_directory: list[int]
):
    """`%` 是打出来的字，不是通配符：不转义的话，打一个 `%` 会把整个目录筛出来，
    而那时的界面与「什么都没筛」长得一模一样。"""
    page = _get(auth_client, CUSTOMERS_PATH, keyword="%")

    assert page["total"] == 0


def test_a_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_directory: list[int]
):
    """越界页给空 `items`，`total` 不变——翻过头不是「没有客户」。"""
    page = _directory(auth_client, page=99)

    assert page["items"] == []
    assert page["page"] == 99
    assert page["total"] == CUSTOMER_COUNT


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_directory: list[int]
):
    """页长超上限是钳制到 100，而不是报错：客户端多要几行不该让翻页整个失效。"""
    page = _directory(auth_client, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE


# --- 风险测评历史：形状、翻页与稳定排序键 ---


def _assessments(client: TestClient, customer_id: int, **params) -> dict:
    return _get(client, ASSESSMENTS_PATH.format(customer_id=customer_id), **params)


def test_the_assessment_history_serves_the_page_shape(
    auth_client: TestClient, seeded_directory: list[int]
):
    page = _assessments(auth_client, seeded_directory[0])

    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == 1
    assert page["page_size"] == DEFAULT_PAGE_SIZE
    assert page["total"] == ASSESSMENT_COUNT
    assert len(page["items"]) == DEFAULT_PAGE_SIZE
    assert set(page["items"][0]) == {
        "id",
        "assessment_date",
        "risk_level",
        "total_score",
        "valid_until",
    }


def test_turning_the_assessment_pages_yields_every_record_exactly_once(
    auth_client: TestClient, seeded_directory: list[int]
):
    read = _read_all_pages(
        auth_client, ASSESSMENTS_PATH.format(customer_id=seeded_directory[0]), page_size=10
    )

    assert read["page_sizes"] == [10, 10, 5]
    assert read["total"] == ASSESSMENT_COUNT
    ids = _ids(read["items"])
    assert len(ids) == len(set(ids)) == ASSESSMENT_COUNT


def test_the_assessment_history_is_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_directory: list[int]
):
    """最近的评测在最前，且跨页成立：历次评测的先后不随翻页而变。"""
    read = _read_all_pages(
        auth_client, ASSESSMENTS_PATH.format(customer_id=seeded_directory[0]), page_size=10
    )

    dates = [row["assessment_date"] for row in read["items"]]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == _assessment_date(SAME_DAY_FROM).isoformat()


def test_assessments_of_the_same_day_have_one_fixed_order(
    auth_client: TestClient, seeded_directory: list[int]
):
    """同一天的多次评测顺序固定：`assessment_date` 只有日精度，靠 `id` 兜底。

    同一天提交两次很常见（答错重做），这一组正是 `id` 兜底唯一会暴露的地方。
    """
    customer_id = seeded_directory[0]

    first = _assessments(auth_client, customer_id, page_size=MAX_PAGE_SIZE)
    second = _assessments(auth_client, customer_id, page_size=MAX_PAGE_SIZE)

    assert _ids(first["items"]) == _ids(second["items"])
    assert [row["total_score"] for row in first["items"][:3]] == SAME_SECOND_ORDER
    assert len({row["assessment_date"] for row in first["items"][:3]}) == 1


def test_a_page_beyond_the_last_assessment_page_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_directory: list[int]
):
    page = _assessments(auth_client, seeded_directory[0], page=99)

    assert page["items"] == []
    assert page["total"] == ASSESSMENT_COUNT


def test_another_customer_has_their_own_assessment_history(
    auth_client: TestClient, seeded_directory: list[int]
):
    """历史按客户收窄：别人的评测不会串进来，`total` 也回到各自的名下。"""
    page = _assessments(auth_client, seeded_directory[1])

    assert page == {"items": [], "total": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE}
