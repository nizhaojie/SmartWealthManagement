"""投顾四类列表的分页（ADR-0024，`list-pagination` #05）。

覆盖四个接口：待审内容队列、顾问审核历史、客户的「我的方案」与「方案请求」
（内部端 + 客户侧）。它们的共同点是列表都按时间排序、时间只到秒，所以每个
列表都有一条「同秒兜底」的断言——翻页读两遍必须逐字相同。

四件事各自钉一次：

- **形状**：`data` 恒为 `{items, total, page, page_size}`，旧的裸数组与语义
  字段名（`plans` / `requests` / `history`）不并存。
- **`total` 的口径**：是过滤后的总数，不是本页条数，也不含别人的记录——
  客户的方案与请求按客户收窄，`total` 必须跟着收窄。
- **排序键**：时间倒序（队列那一段是等得最久的在前）+ 标识兜底，且跨页成立。
- **越界与钳制**：越界页给空 `items` 而 `total` 不变；页长超上限钳到 100。

造数直接写库（`biz_advisory_request` / `biz_advisory_draft` / `biz_advisory_review`
/ `biz_advisory_review_audit` / `biz_advisory_final`）：这里要断的是读侧。时间刻意
摆成「前 22 条各占一秒、最后三条挤在同一秒」，并把**标识与时间反着来**——两个
排序键都按标识来的话，期望顺序恰好也一样，就测不出「时间才是第一位排序键」。

队列与历史是跨客户的全局列表，且没有关键字筛选可用：断言因此落在「本次造出来
的那些行彼此的顺序」上，另加「翻页不重不漏」这类与数据无关的不变量。方案与请求
按客户收窄，可以直接断精确的 `total`。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.auth.security import hash_password
from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryRequest,
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    Employee,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
ADVISOR_USERNAME = "advisor1"

QUEUE_PATH = "/api/internal/advisory/queue"
HISTORY_PATH = "/api/internal/advisory/history"
INTERNAL_REQUESTS_PATH = "/api/internal/advisory-requests"
CUSTOMER_REQUESTS_PATH = "/api/customer/advisory-requests"
CUSTOMER_PLANS_PATH = "/api/customer/advisory/plans"

STATUS_PENDING = "待处理"
STATUS_CLOSED = "已关闭"

CONTENT_TYPE_PLAN = "方案"

# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 每张列表 25 条：刻意凑成「一页装不下、两页有余」。
ROW_COUNT = 25
# 排序窗口落在 2026-06：别的用例造的行都在「现在」附近，两者不会混。
WINDOW_START = datetime(2026, 6, 1, 9, 0, 0)
# 前 22 条各占一秒，最后三条挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 22

NAME_PREFIX = "分页用例投顾"
# 账号前缀：本次造数与上一次中断留下的遗迹都能靠它收干净。
USERNAME_PREFIX = "advisorypage"
# 本次造数的标记：请求编号与条件指纹都带上它，遗留数据一眼可辨。
CASE_TAG = "PAGECASE"

# 「最新的在前」的期望顺序（时间倒序，同秒那组按标识倒序兜底）。
EXPECTED_NEWEST_FIRST = [*range(SAME_SECOND_FROM), 24, 23, 22]
# 「等得最久的在前」的期望顺序（时间升序，同秒那组按标识升序兜底）。
EXPECTED_OLDEST_FIRST = [22, 23, 24, *range(SAME_SECOND_FROM - 1, -1, -1)]


def _at(index: int) -> datetime:
    """第 index 条的时刻：标识最小的那条**最晚**，最后三条挤在同一秒。

    标识与时间反着来，两个排序键各自的作用才分得开（见模块 docstring）。
    """
    return WINDOW_START + timedelta(seconds=SAME_SECOND_FROM - min(index, SAME_SECOND_FROM))


def _username(index: int) -> str:
    return f"{USERNAME_PREFIX}{index:02d}"


def _real_name(index: int) -> str:
    return f"{NAME_PREFIX}{index:02d}"


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_headers(client: TestClient, username: str = ADVISOR_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _advisor_id(engine) -> int:
    with OrmSession(engine) as session:
        advisor = session.scalar(select(Employee).where(Employee.username == ADVISOR_USERNAME))
        assert advisor is not None
        return advisor.id


def _purge_created(session: OrmSession) -> None:
    """清掉本次（或上一次中断留下的）造数：留下的那份会让精确断言的数字对不上。

    账号前缀是固定的，因此这一次造数与上一次的遗迹能被同一段代码收干净。
    """
    customer_ids = list(
        session.scalars(select(Customer.id).where(Customer.username.like(f"{USERNAME_PREFIX}%")))
    )
    if not customer_ids:
        return
    drafts = list(
        session.scalars(select(AdvisoryDraft.id).where(AdvisoryDraft.customer_id.in_(customer_ids)))
    )
    if drafts:
        reviews = list(
            session.scalars(select(AdvisoryReview.id).where(AdvisoryReview.draft_id.in_(drafts)))
        )
        if reviews:
            session.execute(
                delete(AdvisoryReviewAudit).where(AdvisoryReviewAudit.review_id.in_(reviews))
            )
        # 定稿与审核记录都指向原稿，先撤下游再撤原稿（外键顺序）。
        session.execute(delete(AdvisoryFinal).where(AdvisoryFinal.draft_id.in_(drafts)))
        session.execute(delete(AdvisoryReview).where(AdvisoryReview.draft_id.in_(drafts)))
        session.execute(delete(AdvisoryDraft).where(AdvisoryDraft.id.in_(drafts)))
    session.execute(delete(AdvisoryRequest).where(AdvisoryRequest.customer_id.in_(customer_ids)))
    session.execute(delete(Customer).where(Customer.id.in_(customer_ids)))


@pytest.fixture
def seeded_lists(auth_client: TestClient) -> Iterator[dict]:
    """一位客户名下的五类记录：25 条请求、25 份待审原稿（各带审核留痕）、25 份定稿。

    待审原稿与定稿各用一批原稿：一份原稿不可能既在待审队列里、又已经定稿送达。
    """
    username = _username(0)
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            _purge_created(session)
            session.commit()
        advisor_id = _advisor_id(engine)
        with OrmSession(engine) as session:
            customer = Customer(
                username=username,
                password_hash=hash_password(SEEDED_PASSWORD),
                real_name=_real_name(0),
                id_number="110101199001020000",
                phone="13700000000",
                customer_level="普通",
                status="正常",
                opened_at=WINDOW_START,
            )
            session.add(customer)
            session.flush()
            customer_id = customer.id

            request_ids = _add_requests(session, customer_id=customer_id)
            review_draft_ids = _add_drafts(
                session, customer_id=customer_id, advisor_id=advisor_id, with_review=True
            )
            _add_audits(session, draft_ids=review_draft_ids, advisor_id=advisor_id)
            final_draft_ids = _add_drafts(
                session, customer_id=customer_id, advisor_id=advisor_id, with_review=False
            )
            final_ids = _add_finals(
                session,
                draft_ids=final_draft_ids,
                customer_id=customer_id,
                advisor_id=advisor_id,
            )
            session.commit()
    finally:
        engine.dispose()

    yield {
        "customer_id": customer_id,
        "username": username,
        "request_ids": request_ids,
        "review_draft_ids": review_draft_ids,
        "final_ids": final_ids,
    }

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            _purge_created(session)
            session.commit()
    finally:
        engine.dispose()


def _add_requests(session: OrmSession, *, customer_id: int) -> list[int]:
    """25 条方案请求；返回按写入顺序（即标识顺序）排列的请求标识。"""
    created: list[int] = []
    for index in range(ROW_COUNT):
        row = AdvisoryRequest(
            request_no=f"AR{CASE_TAG}{index:04d}",
            customer_id=customer_id,
            status=STATUS_PENDING,
            filters={"product_type": "债券基金"},
            condition_fingerprint=f"{CASE_TAG}{index:04d}",
            submitted_at=_at(index),
        )
        session.add(row)
        session.flush()
        created.append(row.id)
    return created


def _add_drafts(
    session: OrmSession, *, customer_id: int, advisor_id: int, with_review: bool
) -> list[int]:
    """25 份原稿，`with_review` 时各自加一条待审的审核记录；返回原稿标识（= 内容引用）。"""
    created: list[int] = []
    for index in range(ROW_COUNT):
        draft = AdvisoryDraft(
            customer_id=customer_id,
            advisor_id=advisor_id,
            tilt="均衡",
            content_classification="投顾内容",
            candidates=[],
            allocation_suggestion={},
            warnings=[],
            profile_computed_at=WINDOW_START,
            candidate_pool_snapshot={},
            generated_at=_at(index),
            advisory_request_id=None,
        )
        session.add(draft)
        session.flush()
        if with_review:
            session.add(
                AdvisoryReview(
                    content_type=CONTENT_TYPE_PLAN,
                    content_ref=draft.id,
                    draft_id=draft.id,
                    thread_id=f"{CASE_TAG}-{draft.id}",
                    status="待审",
                    create_time=_at(index),
                )
            )
        created.append(draft.id)
    return created


def _add_audits(session: OrmSession, *, draft_ids: list[int], advisor_id: int) -> None:
    """给每份待审原稿补一条「已放行」的审核留痕。"""
    for index, draft_id in enumerate(draft_ids):
        review_id = session.scalar(
            select(AdvisoryReview.id).where(AdvisoryReview.draft_id == draft_id)
        )
        session.add(
            AdvisoryReviewAudit(
                review_id=review_id,
                advisor_id=advisor_id,
                action="放行",
                reason=None,
                decided_at=_at(index),
            )
        )


def _add_finals(
    session: OrmSession, *, draft_ids: list[int], customer_id: int, advisor_id: int
) -> list[int]:
    created: list[int] = []
    for index, draft_id in enumerate(draft_ids):
        row = AdvisoryFinal(
            draft_id=draft_id,
            customer_id=customer_id,
            advisor_id=advisor_id,
            content_classification="投顾内容",
            candidates=[],
            allocation_suggestion={},
            warnings=[],
            released_at=_at(index),
        )
        session.add(row)
        session.flush()
        created.append(row.id)
    return created


def _get(client: TestClient, path: str, headers: dict[str, str], **params) -> dict:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_all_pages(
    client: TestClient, path: str, headers: dict[str, str], *, page_size: int, **params
) -> dict:
    """把全部页翻一遍拼成一次全量读数：跨页的顺序与去重只有拼起来才看得见。"""
    items: list[dict] = []
    page_sizes: list[int] = []
    page = 1
    total = 0
    while True:
        data = _get(client, path, headers, page=page, page_size=page_size, **params)
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


def _ids(rows: list[dict], key: str = "id") -> list[int]:
    return [row[key] for row in rows]


def _shape_holds(page: dict, *, page_number: int) -> None:
    """形状只有 `{items, total, page, page_size}` 这一套。"""
    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == page_number


def _order_of(rows: list[dict], *, wanted: set[int], key: str) -> list[int]:
    """只看本次造出来的那些行，返回它们在全量读数里的先后。

    队列与历史是全局列表，别人的记录会插进来；「我这些行彼此的顺序」才是这里
    要断的东西。
    """
    return [row[key] for row in rows if row[key] in wanted]


def _indices_in(order: list[int], *, source: list[int]) -> list[int]:
    """把「标识序列」翻译成造数时的 index 序列（期望顺序按 index 写，更好读）。"""
    position = {identifier: index for index, identifier in enumerate(source)}
    return [position[identifier] for identifier in order]


# --- 待审内容队列 ---


def _queue(client: TestClient, **params) -> dict:
    return _get(client, QUEUE_PATH, _employee_headers(client), **params)


def test_the_queue_serves_the_page_shape(auth_client: TestClient, seeded_lists: dict):
    page = _queue(auth_client, page_size=5)

    _shape_holds(page, page_number=1)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
    # 队列里至少有本次造的 25 份待审原稿。
    assert page["total"] >= ROW_COUNT


def test_turning_the_queue_pages_yields_every_pending_review_exactly_once(
    auth_client: TestClient, seeded_lists: dict
):
    read = _read_all_pages(auth_client, QUEUE_PATH, _employee_headers(auth_client), page_size=10)

    assert read["page_sizes"] == _expected_page_sizes(read["total"], 10)
    content_refs = _ids(read["items"], "content_ref")
    assert len(content_refs) == len(set(content_refs)) == read["total"]


def test_the_queue_puts_the_longest_waiting_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: dict
):
    """时间升序（等得最久的在前）跨页成立，且标识只是兜底。"""
    read = _read_all_pages(auth_client, QUEUE_PATH, _employee_headers(auth_client), page_size=10)

    order = _order_of(read["items"], wanted=set(seeded_lists["review_draft_ids"]), key="content_ref")
    assert len(order) == ROW_COUNT
    assert _indices_in(order, source=seeded_lists["review_draft_ids"]) == EXPECTED_OLDEST_FIRST


def test_pending_reviews_created_in_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_lists: dict
):
    """同一秒落库的待审内容顺序固定：`create_time` 只到秒，靠内容标识兜底。

    这组正是标识兜底唯一会暴露的地方：顺序不稳时，翻页会把一条读两次、另一条
    谁也读不到，而两页看起来都正常。
    """
    wanted = set(seeded_lists["review_draft_ids"])
    first = _queue(auth_client, page_size=MAX_PAGE_SIZE)
    second = _queue(auth_client, page_size=MAX_PAGE_SIZE)

    order = _order_of(first["items"], wanted=wanted, key="content_ref")
    assert order == _order_of(second["items"], wanted=wanted, key="content_ref")

    # 队首先是最早的那一秒，那一秒里有三条。
    same_second = _indices_in(order, source=seeded_lists["review_draft_ids"])[:3]
    assert same_second == EXPECTED_OLDEST_FIRST[:3]

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            moments = set(
                session.scalars(
                    select(AdvisoryReview.create_time).where(
                        AdvisoryReview.content_ref.in_(
                            [seeded_lists["review_draft_ids"][index] for index in same_second]
                        )
                    )
                )
            )
    finally:
        engine.dispose()
    assert len(moments) == 1


def test_a_queue_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: dict
):
    first = _queue(auth_client, page_size=10)
    beyond = _queue(auth_client, page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["page"] == 999
    assert beyond["total"] == first["total"]


def test_a_queue_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_lists: dict
):
    page = _queue(auth_client, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE


# --- 顾问审核历史 ---


def _history(client: TestClient, **params) -> dict:
    return _get(client, HISTORY_PATH, _employee_headers(client), **params)


def test_the_history_serves_the_page_shape(auth_client: TestClient, seeded_lists: dict):
    page = _history(auth_client, page_size=5)

    _shape_holds(page, page_number=1)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
    assert set(page["items"][0]) == {
        "content_type",
        "content_ref",
        "draft_id",
        "customer_id",
        "customer_name",
        "action",
        "reason",
        "decided_at",
    }


def test_turning_the_history_pages_yields_every_audit_exactly_once(
    auth_client: TestClient, seeded_lists: dict
):
    read = _read_all_pages(auth_client, HISTORY_PATH, _employee_headers(auth_client), page_size=10)

    assert read["page_sizes"] == _expected_page_sizes(read["total"], 10)
    content_refs = _ids(read["items"], "content_ref")
    assert len(content_refs) == len(set(content_refs)) == read["total"]


def test_the_history_is_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: dict
):
    """最近审核的在前，且跨页成立；同一秒的两条靠内容标识兜底。"""
    read = _read_all_pages(auth_client, HISTORY_PATH, _employee_headers(auth_client), page_size=10)

    order = _order_of(read["items"], wanted=set(seeded_lists["review_draft_ids"]), key="content_ref")
    assert len(order) == ROW_COUNT
    assert _indices_in(order, source=seeded_lists["review_draft_ids"]) == EXPECTED_NEWEST_FIRST


def test_a_history_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: dict
):
    first = _history(auth_client, page_size=10)
    beyond = _history(auth_client, page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["total"] == first["total"]


# --- 客户的「我的方案」 ---


def _plans(client: TestClient, username: str, **params) -> dict:
    return _get(client, CUSTOMER_PLANS_PATH, _customer_headers(client, username), **params)


def test_the_customer_plans_serve_the_page_shape_with_the_customers_own_total(
    auth_client: TestClient, seeded_lists: dict
):
    """方案按客户收窄：25 份定稿全归他，`total` 就是 25。"""
    page = _plans(auth_client, seeded_lists["username"], page_size=5)

    _shape_holds(page, page_number=1)
    assert page["total"] == ROW_COUNT
    assert page["page_size"] == 5
    assert len(page["items"]) == 5


def test_turning_the_customer_plan_pages_yields_every_plan_exactly_once(
    auth_client: TestClient, seeded_lists: dict
):
    read = _read_all_pages(
        auth_client,
        CUSTOMER_PLANS_PATH,
        _customer_headers(auth_client, seeded_lists["username"]),
        page_size=10,
    )

    assert read["page_sizes"] == _expected_page_sizes(ROW_COUNT, 10)
    assert read["total"] == ROW_COUNT
    plan_ids = _ids(read["items"])
    assert len(plan_ids) == len(set(plan_ids)) == ROW_COUNT


def test_the_customer_plans_are_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: dict
):
    """放行时间倒序跨页成立，同秒那组按定稿标识倒序兜底。"""
    read = _read_all_pages(
        auth_client,
        CUSTOMER_PLANS_PATH,
        _customer_headers(auth_client, seeded_lists["username"]),
        page_size=10,
    )

    assert _indices_in(_ids(read["items"]), source=seeded_lists["final_ids"]) == (
        EXPECTED_NEWEST_FIRST
    )


def test_a_customer_plan_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: dict
):
    beyond = _plans(auth_client, seeded_lists["username"], page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["total"] == ROW_COUNT


# --- 客户的「方案请求」 ---


def _customer_requests(client: TestClient, username: str, **params) -> dict:
    return _get(client, CUSTOMER_REQUESTS_PATH, _customer_headers(client, username), **params)


def test_the_customer_requests_serve_the_page_shape_with_the_customers_own_total(
    auth_client: TestClient, seeded_lists: dict
):
    page = _customer_requests(auth_client, seeded_lists["username"], page_size=5)

    _shape_holds(page, page_number=1)
    assert page["total"] == ROW_COUNT
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
    # 客户侧不回显内部标识（既有口径不因分页而变）。
    assert "customer_id" not in page["items"][0]


def test_turning_the_customer_request_pages_yields_every_request_exactly_once(
    auth_client: TestClient, seeded_lists: dict
):
    read = _read_all_pages(
        auth_client,
        CUSTOMER_REQUESTS_PATH,
        _customer_headers(auth_client, seeded_lists["username"]),
        page_size=10,
    )

    assert read["page_sizes"] == _expected_page_sizes(ROW_COUNT, 10)
    assert read["total"] == ROW_COUNT
    request_ids = _ids(read["items"])
    assert len(request_ids) == len(set(request_ids)) == ROW_COUNT


def test_the_customer_requests_are_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: dict
):
    """提交时间倒序跨页成立，同秒那组按请求标识倒序兜底。"""
    read = _read_all_pages(
        auth_client,
        CUSTOMER_REQUESTS_PATH,
        _customer_headers(auth_client, seeded_lists["username"]),
        page_size=10,
    )

    assert _indices_in(_ids(read["items"]), source=seeded_lists["request_ids"]) == (
        EXPECTED_NEWEST_FIRST
    )


def test_a_customer_request_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: dict
):
    beyond = _customer_requests(auth_client, seeded_lists["username"], page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["total"] == ROW_COUNT


# --- 内部端的待生成方案请求 ---


def _pending_requests(client: TestClient, **params) -> dict:
    return _get(client, INTERNAL_REQUESTS_PATH, _employee_headers(client), **params)


def test_the_pending_request_page_carries_the_customer_and_the_waiting_time(
    auth_client: TestClient, seeded_lists: dict
):
    """顾问端要凭这一页决定先处理哪一条：客户与等待时长必须在。"""
    page = _pending_requests(auth_client, status=STATUS_PENDING, page_size=MAX_PAGE_SIZE)

    _shape_holds(page, page_number=1)
    row = next(item for item in page["items"] if item["id"] in seeded_lists["request_ids"])
    assert row["customer_id"] == seeded_lists["customer_id"]
    assert row["customer_name"] == _real_name(0)
    assert row["waiting_seconds"] >= 0


def test_the_pending_request_list_is_longest_waiting_first_and_pages_without_gaps(
    auth_client: TestClient, seeded_lists: dict
):
    read = _read_all_pages(
        auth_client,
        INTERNAL_REQUESTS_PATH,
        _employee_headers(auth_client),
        page_size=10,
        status=STATUS_PENDING,
    )

    assert read["page_sizes"] == _expected_page_sizes(read["total"], 10)
    request_ids = _ids(read["items"])
    assert len(request_ids) == len(set(request_ids)) == read["total"]

    order = _order_of(read["items"], wanted=set(seeded_lists["request_ids"]), key="id")
    assert len(order) == ROW_COUNT
    assert _indices_in(order, source=seeded_lists["request_ids"]) == EXPECTED_OLDEST_FIRST


def test_the_status_filter_narrows_the_total(auth_client: TestClient, seeded_lists: dict):
    """筛掉的请求不计入 `total`，也不出现在 `items` 里。"""
    pending = _pending_requests(auth_client, status=STATUS_PENDING, page_size=MAX_PAGE_SIZE)
    closed = _pending_requests(auth_client, status=STATUS_CLOSED)

    assert closed == {"items": [], "total": 0, "page": 1, "page_size": DEFAULT_PAGE_SIZE}
    assert pending["total"] >= ROW_COUNT
    assert all(item["status"] == STATUS_PENDING for item in pending["items"])
