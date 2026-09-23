"""操作建议两张列表的分页（ADR-0024，`list-pagination` #07）。

两端各一张列表，在这里各自钉一次：

- **内部「客户建议进度」**（`GET /api/internal/customers/{id}/operation-advice`）：
  按发起时间倒序的一页，`total` 是这位客户的建议总数（不是本页条数，也不含别人的）。
- **客户「我的建议」**（`GET /api/customer/operation-advice`）：按送达时间倒序的一页，
  `total` 是这位客户**已送达**的建议总数——未放行的与被驳回的都不在其中。

共同点即共同风险：两张列表的排序时刻都只到秒，同一秒落库的两条若没有全序键，翻页
会把一条读两次、另一条谁也读不到，而两页看起来都正常。所以两张列表各有一条「同秒
兜底」的断言，并且造数时**让标识与时间反着来**——两个排序键的作用才分得开。

另有一处只属于客户侧：`status` 过滤。侧栏角标读的是「待决定共几条」，而列表本身是
混合状态的，分页之后本页条数不再等于全局条数；它走同一个列表接口的过滤后 `total`，
不另加 count 接口。取值只认四个状态，拼错的状态被拒绝，而不是静默回一个空列表——
空列表在分页之后与「你还没有建议」是同一句话。

造数直接写库（`biz_operation_advice_draft` / `biz_advisory_review` /
`biz_advisory_review_audit` / `biz_operation_advice_decision`）：这里要断的是读侧，
而走发起接口造 27 条既要过额度与适当性的门槛，也钉不住时刻。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review_status import ACTION_RELEASE
from app.auth.security import hash_password
from app.db.models import (
    AdvisoryReview,
    AdvisoryReviewAudit,
    Customer,
    Employee,
    OperationAdviceDecision,
    OperationAdviceDraft,
)
from app.operation_advice.decision import (
    STATUS_ACCEPTED,
    STATUS_AWAITING,
    STATUS_EXPIRED,
    STATUS_REJECTED,
)
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

MANAGER_USERNAME = "manager1"
ADVISOR_USERNAME = "advisor1"

INTERNAL_PATH = "/api/internal/customers/{customer_id}/operation-advice"
CUSTOMER_PATH = "/api/customer/operation-advice"

REVIEW_PENDING = "待审"
REVIEW_RELEASED = "已放行"
REVIEW_REJECTED = "已驳回"

DECISION_ACCEPT = "接受"
DECISION_REJECT = "拒绝"

# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

# 发起时刻的窗口落在 2026-06：别的用例造的行都在「现在」附近，两者不会混。
WINDOW_START = datetime(2026, 6, 1, 9, 0, 0)
# 从这个 index 起挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
TIE_FROM = 22

# 27 条建议：24 条已放行送达客户，一条待审、一条已驳回（客户侧读不到），
# 另有一条放行在 30 天前（送达满 7 个自然日即为「已过期」）。
ROW_COUNT = 27
DELIVERED_ROWS = 24
PENDING_INDEX = 24
REJECTED_INDEX = 25
EXPIRED_INDEX = 26

ACCEPTED_INDICES = (0, 1)
REJECTED_DECISION_INDICES = (2, 3)

INTERNAL_TOTAL = ROW_COUNT
CUSTOMER_TOTAL = DELIVERED_ROWS + 1

# 另一张列表：这位客户之外的 3 条建议，任何 `total` 都不该把它们算进来。
FOREIGN_ROW_COUNT = 3

NAME_PREFIX = "分页用例建议"
# 账号前缀：本次造数与上一次中断留下的遗迹都能靠它收干净。
USERNAME_PREFIX = "advicepage"
# 本次造数的标记：线程标识带上它，遗留数据一眼可辨。
CASE_TAG = "ADVICEPAGE"

# 期望顺序按 index 写（更好读）。
# 内部进度：发起时间倒序 + 标识兜底。前 22 条各占一秒，22–25 挤在同一秒（标识倒序），
# 最后一条是那条放行在 30 天前的（发起时间也最早）。
EXPECTED_INTERNAL = [*range(22), REJECTED_INDEX, PENDING_INDEX, 23, 22, EXPIRED_INDEX]
# 客户侧：送达时间倒序 + 标识兜底。只有 24 条已放行 + 那条过期的。
EXPECTED_CUSTOMER = [*range(22), 23, 22, EXPIRED_INDEX]
# 只看「待客户决定」时，决定的四条与过期的那条都要让位。
EXPECTED_AWAITING = [*range(4, 22), 23, 22]


def _engine():
    return create_engine(get_settings().test_database_url)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _offset(index: int) -> int:
    """第 index 条的秒偏移：标识最小的那条**最晚**，`TIE_FROM` 起挤在同一秒。

    标识与时间反着来（见模块 docstring）：两个排序键各自的作用才分得开。
    """
    return TIE_FROM - min(index, TIE_FROM)


def _generated_at(index: int) -> datetime:
    if index == EXPIRED_INDEX:
        # 发起得最早的那一条：内部进度表里它排在最末。
        return WINDOW_START - timedelta(days=1)
    return WINDOW_START + timedelta(seconds=_offset(index))


def _released_at(index: int, now: datetime) -> datetime:
    if index == EXPIRED_INDEX:
        # 送达满 7 个自然日即为已过期；拨到 30 天前，客户侧它排在最末。
        return now - timedelta(hours=1, days=30)
    # 送达窗口在「现在」附近：待决定的那批必须还在 7 个自然日的有效期内。
    return now - timedelta(hours=1) + timedelta(seconds=_offset(index))


def _review_status(index: int) -> str:
    if index == PENDING_INDEX:
        return REVIEW_PENDING
    if index == REJECTED_INDEX:
        return REVIEW_REJECTED
    return REVIEW_RELEASED


def _is_released(index: int) -> bool:
    return _review_status(index) == REVIEW_RELEASED


def _username(index: int) -> str:
    return f"{USERNAME_PREFIX}{index:02d}"


def _real_name(index: int) -> str:
    return f"{NAME_PREFIX}{index:02d}"


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
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


def _employee_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        employee = session.scalar(select(Employee).where(Employee.username == username))
        assert employee is not None
        return employee.id


def _purge_created(session: OrmSession) -> None:
    """清掉本次（或上一次中断留下的）造数：留下的那份会让精确断言的数字对不上。

    账号前缀是固定的，因此这一次造数与上一次的遗迹能被同一段代码收干净。
    """
    customer_ids = list(
        session.scalars(
            select(Customer.id).where(Customer.username.like(f"{USERNAME_PREFIX}%"))
        )
    )
    if not customer_ids:
        return
    drafts = list(
        session.scalars(
            select(OperationAdviceDraft.id).where(
                OperationAdviceDraft.customer_id.in_(customer_ids)
            )
        )
    )
    if drafts:
        reviews = list(
            session.scalars(
                select(AdvisoryReview.id).where(
                    AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
                    AdvisoryReview.content_ref.in_(drafts),
                )
            )
        )
        if reviews:
            session.execute(
                delete(AdvisoryReviewAudit).where(
                    AdvisoryReviewAudit.review_id.in_(reviews)
                )
            )
            session.execute(delete(AdvisoryReview).where(AdvisoryReview.id.in_(reviews)))
        session.execute(
            delete(OperationAdviceDecision).where(
                OperationAdviceDecision.advice_id.in_(drafts)
            )
        )
        session.execute(
            delete(OperationAdviceDraft).where(OperationAdviceDraft.id.in_(drafts))
        )
    session.execute(delete(Customer).where(Customer.id.in_(customer_ids)))


def _open_customer(
    session: OrmSession, *, index: int, manager_id: int, digits: str
) -> int:
    customer = Customer(
        username=_username(index),
        password_hash=hash_password(SEEDED_PASSWORD),
        real_name=_real_name(index),
        id_number=f"11010119900102{digits}",
        phone=f"137{digits}",
        customer_level="普通",
        status="正常",
        manager_id=manager_id,
        opened_at=WINDOW_START,
    )
    session.add(customer)
    session.flush()
    return customer.id


def _add_advice(
    session: OrmSession,
    *,
    customer_id: int,
    manager_id: int,
    advisor_id: int,
    now: datetime,
) -> tuple[list[int], dict[int, int]]:
    """27 条建议各带一条审核记录；返回（按写入顺序的原稿标识, index → 审核标识）。"""
    draft_ids: list[int] = []
    review_ids: dict[int, int] = {}
    for index in range(ROW_COUNT):
        draft = OperationAdviceDraft(
            customer_id=customer_id,
            manager_id=manager_id,
            product_code="F000001",
            direction="申购",
            amount=Decimal("10000.00"),
            redeemed_shares=None,
            reason=f"{NAME_PREFIX}{index:02d}的理由",
            content_classification="投顾内容",
            generated_at=_generated_at(index),
        )
        session.add(draft)
        session.flush()
        draft_ids.append(draft.id)

        review = AdvisoryReview(
            content_type=CONTENT_TYPE_OPERATION_ADVICE,
            content_ref=draft.id,
            # 方案特有的列：操作建议的审核记录上它是空。
            draft_id=None,
            thread_id=f"{CASE_TAG}-{draft.id}",
            status=_review_status(index),
            create_time=_generated_at(index),
        )
        session.add(review)
        session.flush()
        review_ids[index] = review.id

    for index, review_id in review_ids.items():
        if not _is_released(index):
            continue
        # 送达时间是**放行留痕**（`decision.released_at_by_review`），不是审核记录上的列。
        session.add(
            AdvisoryReviewAudit(
                review_id=review_id,
                advisor_id=advisor_id,
                action=ACTION_RELEASE,
                reason=None,
                decided_at=_released_at(index, now),
            )
        )

    for index in (*ACCEPTED_INDICES, *REJECTED_DECISION_INDICES):
        session.add(
            OperationAdviceDecision(
                advice_id=draft_ids[index],
                customer_id=customer_id,
                decision=(
                    DECISION_ACCEPT
                    if index in ACCEPTED_INDICES
                    else DECISION_REJECT
                ),
                decided_at=_released_at(index, now) + timedelta(minutes=5),
            )
        )
    return draft_ids, review_ids


def _add_foreign_advice(
    session: OrmSession, *, customer_id: int, manager_id: int
) -> None:
    """另一位客户名下的几条建议：任何 `total` 都不该把它们算进来。"""
    for index in range(FOREIGN_ROW_COUNT):
        draft = OperationAdviceDraft(
            customer_id=customer_id,
            manager_id=manager_id,
            product_code="F000001",
            direction="申购",
            amount=Decimal("5000.00"),
            redeemed_shares=None,
            reason=f"{NAME_PREFIX}别人的{index:02d}",
            content_classification="投顾内容",
            generated_at=WINDOW_START,
        )
        session.add(draft)
        session.flush()
        session.add(
            AdvisoryReview(
                content_type=CONTENT_TYPE_OPERATION_ADVICE,
                content_ref=draft.id,
                draft_id=None,
                thread_id=f"{CASE_TAG}-foreign-{draft.id}",
                status=REVIEW_PENDING,
                create_time=WINDOW_START,
            )
        )


@pytest.fixture
def seeded_advice(auth_client: TestClient) -> Iterator[dict]:
    """一位归属 manager1 的客户，名下有 27 条取不同状态与时刻的建议。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            _purge_created(session)
            session.commit()
        manager_id = _employee_id(engine, MANAGER_USERNAME)
        advisor_id = _employee_id(engine, ADVISOR_USERNAME)
        now = _now()
        with OrmSession(engine) as session:
            customer_id = _open_customer(
                session, index=0, manager_id=manager_id, digits="6001"
            )
            foreign_id = _open_customer(
                session, index=1, manager_id=manager_id, digits="6002"
            )
            draft_ids, review_ids = _add_advice(
                session,
                customer_id=customer_id,
                manager_id=manager_id,
                advisor_id=advisor_id,
                now=now,
            )
            _add_foreign_advice(
                session, customer_id=foreign_id, manager_id=manager_id
            )
            session.commit()
    finally:
        engine.dispose()

    yield {
        "customer_id": customer_id,
        "username": _username(0),
        "draft_ids": draft_ids,
        "review_ids": review_ids,
    }

    engine = _engine()
    try:
        with OrmSession(engine) as session:
            _purge_created(session)
            session.commit()
    finally:
        engine.dispose()


def _get(client: TestClient, path: str, headers: dict[str, str], **params) -> dict:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_progress(client: TestClient, seeded: dict, **params) -> dict:
    return _get(
        client,
        INTERNAL_PATH.format(customer_id=seeded["customer_id"]),
        _employee_headers(client, MANAGER_USERNAME),
        **params,
    )


def _read_mine(client: TestClient, seeded: dict, **params) -> dict:
    return _get(
        client,
        CUSTOMER_PATH,
        _customer_headers(client, seeded["username"]),
        **params,
    )


def _read_all_pages(load, *, page_size: int) -> dict:
    """把全部页翻一遍拼成一次全量读数：跨页的顺序与去重只有拼起来才看得见。"""
    items: list[dict] = []
    page_sizes: list[int] = []
    page = 1
    total = 0
    while True:
        data = load(page=page, page_size=page_size)
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


def _shape_holds(page: dict, *, page_number: int) -> None:
    """形状只有 `{items, total, page, page_size}` 这一套，旧的语义字段名不并存。"""
    assert set(page) == {"items", "total", "page", "page_size"}
    assert page["page"] == page_number


def _indices(order: list[int], *, source: list[int]) -> list[int]:
    """把「标识序列」翻译成造数时的 index 序列（期望顺序按 index 写，更好读）。"""
    position = {identifier: index for index, identifier in enumerate(source)}
    return [position[identifier] for identifier in order]


# --- 内部「客户建议进度」 ---


def test_the_progress_list_serves_the_page_shape(
    auth_client: TestClient, seeded_advice: dict
):
    page = _read_progress(auth_client, seeded_advice, page_size=5)

    _shape_holds(page, page_number=1)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
    # 精确的 27：可见范围按客户归属收窄，另一位客户那 3 条一条都不算。
    assert page["total"] == INTERNAL_TOTAL


def test_turning_the_progress_pages_yields_every_advice_exactly_once(
    auth_client: TestClient, seeded_advice: dict
):
    read = _read_all_pages(
        lambda **params: _read_progress(auth_client, seeded_advice, **params),
        page_size=10,
    )

    assert read["page_sizes"] == _expected_page_sizes(INTERNAL_TOTAL, 10)
    ids = [row["id"] for row in read["items"]]
    assert len(ids) == len(set(ids)) == INTERNAL_TOTAL


def test_the_progress_is_ordered_by_generation_newest_first_across_pages(
    auth_client: TestClient, seeded_advice: dict
):
    """发起时间倒序跨页成立，标识只是同一秒里的兜底——顺序必须两次读出来一样。"""
    first = _read_all_pages(
        lambda **params: _read_progress(auth_client, seeded_advice, **params),
        page_size=7,
    )
    second = _read_progress(auth_client, seeded_advice, page_size=MAX_PAGE_SIZE)

    order = _indices(
        [row["id"] for row in first["items"]], source=seeded_advice["draft_ids"]
    )
    assert order == EXPECTED_INTERNAL
    assert [row["id"] for row in second["items"]] == [row["id"] for row in first["items"]]


def test_the_progress_carries_both_review_and_customer_state(
    auth_client: TestClient, seeded_advice: dict
):
    """分页只切窗口，不改行里的两个口径：审核状态一直有，客户决定只在送达之后有。"""
    rows = _read_progress(auth_client, seeded_advice, page_size=MAX_PAGE_SIZE)["items"]
    by_id = {row["id"]: row for row in rows}
    drafts = seeded_advice["draft_ids"]

    for index in range(ROW_COUNT):
        row = by_id[drafts[index]]
        assert row["review_status"] == _review_status(index)
        if _is_released(index):
            assert row["customer_status"] is not None
        else:
            assert row["customer_status"] is None

    # 客户决定那一列的取值来自现算的状态，不是审核状态。
    assert by_id[drafts[ACCEPTED_INDICES[0]]]["customer_status"] == STATUS_ACCEPTED
    assert (
        by_id[drafts[REJECTED_DECISION_INDICES[0]]]["customer_status"]
        == STATUS_REJECTED
    )
    assert by_id[drafts[EXPIRED_INDEX]]["customer_status"] == STATUS_EXPIRED


def test_the_progress_serves_queries_other_than_the_first_page(
    auth_client: TestClient, seeded_advice: dict
):
    """`page`/`page_size` 都要生效：同一批数据的第 2 页与第 1 页不重叠。"""
    first = _read_progress(auth_client, seeded_advice, page_size=10)
    second = _read_progress(auth_client, seeded_advice, page=2, page_size=10)

    _shape_holds(second, page_number=2)
    assert second["total"] == first["total"]
    assert {row["id"] for row in first["items"]}.isdisjoint(
        row["id"] for row in second["items"]
    )


def test_a_progress_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_advice: dict
):
    first = _read_progress(auth_client, seeded_advice, page_size=10)
    beyond = _read_progress(auth_client, seeded_advice, page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["page"] == 999
    assert beyond["total"] == first["total"]


def test_a_progress_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_advice: dict
):
    page = _read_progress(auth_client, seeded_advice, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE
    assert len(page["items"]) == INTERNAL_TOTAL


def test_the_defaults_are_page_one_and_twenty_rows(
    auth_client: TestClient, seeded_advice: dict
):
    """不带参数时是第 1 页、每页 10 条：默认值只有后台那一处（ADR-0024）。"""
    page = _read_progress(auth_client, seeded_advice)

    _shape_holds(page, page_number=1)
    assert page["page_size"] == DEFAULT_PAGE_SIZE
    assert len(page["items"]) == DEFAULT_PAGE_SIZE


# --- 客户「我的建议」 ---


def test_the_advice_list_serves_the_page_shape(
    auth_client: TestClient, seeded_advice: dict
):
    page = _read_mine(auth_client, seeded_advice, page_size=5)

    _shape_holds(page, page_number=1)
    assert page["page_size"] == 5
    assert len(page["items"]) == 5
    # 精确的 25：24 条已放行 + 那条过期的；待审与被驳回的在客户侧不存在。
    assert page["total"] == CUSTOMER_TOTAL


def test_turning_the_advice_pages_yields_every_advice_exactly_once(
    auth_client: TestClient, seeded_advice: dict
):
    read = _read_all_pages(
        lambda **params: _read_mine(auth_client, seeded_advice, **params),
        page_size=10,
    )

    assert read["page_sizes"] == _expected_page_sizes(CUSTOMER_TOTAL, 10)
    ids = [row["id"] for row in read["items"]]
    assert len(ids) == len(set(ids)) == CUSTOMER_TOTAL


def test_the_advice_is_ordered_by_delivery_newest_first_across_pages(
    auth_client: TestClient, seeded_advice: dict
):
    """送达时间倒序跨页成立；同一秒送达的两条靠建议标识兜底，两次读出来必须一样。"""
    first = _read_all_pages(
        lambda **params: _read_mine(auth_client, seeded_advice, **params),
        page_size=7,
    )
    second = _read_mine(auth_client, seeded_advice, page_size=MAX_PAGE_SIZE)

    order = _indices(
        [row["id"] for row in first["items"]], source=seeded_advice["draft_ids"]
    )
    assert order == EXPECTED_CUSTOMER
    assert [row["id"] for row in second["items"]] == [row["id"] for row in first["items"]]
    # 同一秒送达的是 22 与 23 那两条（翻页的边界正落在它们身上）：标识大的在前，
    # 且两者相邻、不夹进第三条。少了兜底键时这两条的先后不定，一条就会读两遍。
    assert order[-3:-1] == [23, 22]


def test_an_advice_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_advice: dict
):
    first = _read_mine(auth_client, seeded_advice, page_size=10)
    beyond = _read_mine(auth_client, seeded_advice, page=999, page_size=10)

    assert beyond["items"] == []
    assert beyond["page"] == 999
    assert beyond["total"] == first["total"]


def test_an_advice_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_advice: dict
):
    page = _read_mine(auth_client, seeded_advice, page_size=1000)

    assert page["page_size"] == MAX_PAGE_SIZE
    assert len(page["items"]) == CUSTOMER_TOTAL


# --- 客户侧的状态过滤（侧栏角标读的那个数） ---


def test_the_status_filter_counts_only_that_group(
    auth_client: TestClient, seeded_advice: dict
):
    """四个状态各自的总数——角标读的就是其中一个，而不是本页条数。"""
    expected = {
        STATUS_AWAITING: len(EXPECTED_AWAITING),
        STATUS_ACCEPTED: len(ACCEPTED_INDICES),
        STATUS_REJECTED: len(REJECTED_DECISION_INDICES),
        STATUS_EXPIRED: 1,
    }
    for status, wanted in expected.items():
        page = _read_mine(
            auth_client, seeded_advice, page_size=MAX_PAGE_SIZE, status=status
        )
        assert page["total"] == wanted, status
        assert [row["status"] for row in page["items"]] == [status] * wanted

    assert sum(expected.values()) == CUSTOMER_TOTAL


def test_the_status_filter_pages_within_the_group(
    auth_client: TestClient, seeded_advice: dict
):
    """过滤之后再分页：组内翻页同样不重不漏，顺序仍是送达时间倒序。"""
    read = _read_all_pages(
        lambda **params: _read_mine(
            auth_client, seeded_advice, status=STATUS_AWAITING, **params
        ),
        page_size=7,
    )

    assert read["total"] == len(EXPECTED_AWAITING)
    assert read["page_sizes"] == _expected_page_sizes(len(EXPECTED_AWAITING), 7)
    assert _indices(
        [row["id"] for row in read["items"]], source=seeded_advice["draft_ids"]
    ) == EXPECTED_AWAITING


def test_an_unknown_status_is_rejected(
    auth_client: TestClient, seeded_advice: dict
):
    """拼错的状态回 400，而不是一个空列表：空列表与「你还没有建议」是同一句话。"""
    response = auth_client.get(
        CUSTOMER_PATH,
        headers=_customer_headers(auth_client, seeded_advice["username"]),
        params={"status": "已完成"},
    )

    assert response.status_code == 400, response.text
    assert "状态" in response.json()["message"]
