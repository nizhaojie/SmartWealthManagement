"""历史会话与分析历史两条「写死上限」的列表升级为真分页（ADR-0024，`list-pagination` #08）。

这两条不是纯 `.all()` 读取路径：它们各带一个硬编码上限（`LIST_LIMIT = 100`、
`_HISTORY_LIMIT = 50`），浏览历史时多出来的会话与留痕被静默截断——屏幕上看起来仍是
一份完整的列表，只是最早的那些永远翻不到。这个文件要钉住四件事：

- 上限确实没了：造出 105 场会话 / 55 条留痕，`total` 是全部条数，翻页能把最早的一条
  也读出来；
- 形状恒为 `{items, total, page, page_size}`，`total` 是**过滤后**的总数（会话按客户 /
  员工筛、留痕按提问人筛，都算在内）——会话列表按会话分组，`total` 是「多少场会话」
  而不是归档行数；
- 翻页不重不漏、越界页空 `items` 而 `total` 不变、页长超上限被钳制而不是报错；
- 排序键稳定：最后一次发言时间与留痕时间都是秒精度，排在第一位的键分不出先后的那些
  记录靠会话标识 / 留痕标识兜底。顺序不稳定时，翻页会把同一条读两次、另一条谁也读不到，
  而每一页看起来都正常。

会话详情内嵌的 `messages` 保持不分页（issue 原文）：它是会话回看本身，一次会话的消息量
与页长无关——这里也顺带钉一条。

造数直接写 `conversation_archive` 与 `biz_analytics_query_audit`：要断的是读侧，走客服
对话造 105 场会话只会把用例拖长，而落库路径自己另有断言（`test_customer_service_agent`、
`test_conversation_archive_queries`）。

清场：两张表整表清掉——它们都是纯追加的留痕，且每个相关用例都在自己内部造数再断言
（`test_trace_tiers_and_purge`、`test_customer_conversations` 都按自己的 session_id 造与
删）。只有清干净了，`total` 才有一个确切的数可对照，而不是「≥ 造出来的行数」。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import AnalyticsQueryAudit, ConversationArchive, Customer, Employee
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"

CONVERSATIONS_PATH = "/api/internal/conversations"
CUSTOMER_CONVERSATIONS_PATH = "/api/customer/conversations"
HISTORY_PATH = "/api/internal/analytics/history"

CUSTOMER_USERNAME = "wangc1"
OTHER_CUSTOMER_USERNAME = "zhaoc4"
ADVISOR_USERNAME = "advisor1"
MANAGER_USERNAME = "manager1"

# 超过旧上限的造数：会话 105 场（> LIST_LIMIT 100）、留痕 55 条（> _HISTORY_LIMIT 50）。
SESSION_COUNT = 105
OTHER_SESSION_COUNT = 6
HISTORY_COUNT = 55

# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 前 102 场会话各占一秒，最后三场挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 102
# 留痕同理：最后三条挤在同一秒里。
HISTORY_SAME_SECOND_FROM = 52

# 会话详情不分页的证据：其中一场会话有 25 条消息，翻页与它无关。
DEEP_SESSION_INDEX = 0
DEEP_MESSAGE_COUNT = 25

SESSION_PREFIX = "pagination-case-"
OTHER_SESSION_PREFIX = "pagination-other-"
QUESTION_PREFIX = "分页用例提问"
HISTORY_QUESTION_PREFIX = "分页用例留痕"

# 造数时间取在「现在」之后（2027 年）：测试库里的留痕跨运行持久，取当前时刻造数的话
# 本次造的行会排在历史残留之后。放在最前，断言就只依赖这次造出来的东西。
WINDOW_START = datetime(2027, 5, 1, 9, 0, 0)

AGENT_TYPE = "customer_service"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

STATUS_SUCCESS = "成功"


def _session_id(index: int) -> str:
    return f"{SESSION_PREFIX}{index:04d}"


def _other_session_id(index: int) -> str:
    return f"{OTHER_SESSION_PREFIX}{index:04d}"


def _spoken_at(index: int) -> datetime:
    return WINDOW_START + timedelta(seconds=min(index, SAME_SECOND_FROM))


def _recorded_at(index: int) -> datetime:
    return WINDOW_START + timedelta(seconds=min(index, HISTORY_SAME_SECOND_FROM))


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _employee_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Employee.id).where(Employee.username == username))
    assert value is not None
    return int(value)


def _internal_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str) -> tuple[dict[str, str], str]:
    """客户登录：返回请求头与**当前会话标识**（历史列表要把它排除在外）。"""
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["data"]["access_token"]
    payload = pyjwt.decode(token, options={"verify_signature": False})
    return {"Authorization": f"Bearer {token}"}, payload["sid"]


def _purge(engine) -> None:
    """两张纯追加的留痕表整表清掉，见模块开头「清场」一段。"""
    with OrmSession(engine) as session:
        session.execute(delete(ConversationArchive))
        session.execute(delete(AnalyticsQueryAudit))
        session.commit()


def _add_sessions(
    engine, *, user_id: int, prefix: str, count: int, deep_index: int | None = None
) -> None:
    """`count` 场会话，每场一问一答两条归档；`deep_index` 那一场刻意给 25 条消息。

    同一场会话的两条归档共用同一个时间戳：`last_at`（本次发言 = 最后一条的时间）因此
    与场次一一对应，跨页排序断言的参照物就是它。
    """
    with OrmSession(engine) as session:
        for index in range(count):
            session_id = f"{prefix}{index:04d}"
            spoken_at = _spoken_at(index)
            message_count = DEEP_MESSAGE_COUNT if index == deep_index else 2
            for position in range(message_count):
                session.add(
                    ConversationArchive(
                        session_id=session_id,
                        identity_domain="customer",
                        user_id=user_id,
                        agent_type=AGENT_TYPE,
                        role=ROLE_USER if position == 0 else ROLE_ASSISTANT,
                        content=f"{QUESTION_PREFIX}{index} 第 {position} 条"
                        if position == 0
                        else f"回答第 {position} 条",
                        create_time=spoken_at,
                    )
                )
        session.commit()


def _add_history_rows(engine, *, employee_id: int, count: int) -> None:
    """`count` 条留痕：状态一律「成功」，与本用例的断点无关的字段给最小值。"""
    with OrmSession(engine) as session:
        for index in range(count):
            session.add(
                AnalyticsQueryAudit(
                    employee_id=employee_id,
                    question=f"{HISTORY_QUESTION_PREFIX}{index}",
                    generated_sql="SELECT 1",
                    status=STATUS_SUCCESS,
                    row_count=1,
                    truncated=False,
                    error_code=None,
                    create_time=_recorded_at(index),
                )
            )
        session.commit()


@pytest.fixture
def seeded_lists(auth_client: TestClient) -> Iterator[None]:
    """105 场会话（其中一场 25 条消息）+ 另一位客户的 6 场会话 + 55 条留痕，跑完清掉。"""
    engine = _engine()
    _purge(engine)
    own_id = _customer_id(engine, CUSTOMER_USERNAME)
    other_id = _customer_id(engine, OTHER_CUSTOMER_USERNAME)
    _add_sessions(
        engine,
        user_id=own_id,
        prefix=SESSION_PREFIX,
        count=SESSION_COUNT,
        deep_index=DEEP_SESSION_INDEX,
    )
    _add_sessions(
        engine,
        user_id=other_id,
        prefix=OTHER_SESSION_PREFIX,
        count=OTHER_SESSION_COUNT,
    )
    _add_history_rows(
        engine, employee_id=_employee_id(engine, ADVISOR_USERNAME), count=HISTORY_COUNT
    )
    try:
        yield
    finally:
        _purge(engine)
        engine.dispose()


def _get(
    client: TestClient, path: str, *, headers: dict[str, str], **params
) -> dict:
    response = client.get(path, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_all_pages(
    client: TestClient, path: str, *, headers: dict[str, str], page_size: int
) -> dict:
    """把全部页翻一遍再拼起来：排序与「不重不漏」只有拼起来才看得见。"""
    items: list[dict] = []
    page = 1
    while True:
        data = _get(client, path, headers=headers, page=page, page_size=page_size)
        items.extend(data["items"])
        if page * page_size >= data["total"]:
            return {"items": items, "total": data["total"]}
        page += 1


def _session_ids(rows: list[dict]) -> list[str]:
    return [row["session_id"] for row in rows]


def _history_ids(rows: list[dict]) -> list[int]:
    return [row["id"] for row in rows]


# --- 响应形状与 total 的口径 ---


def test_both_conversation_lists_answer_with_the_same_page_shape(
    auth_client: TestClient, seeded_lists: None
):
    """内部端与客户端的会话列表形状一致，只有 `items`/`total`/`page`/`page_size`。"""
    internal = _get(
        auth_client,
        CONVERSATIONS_PATH,
        headers=_internal_headers(auth_client, ADVISOR_USERNAME),
    )
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)
    mine = _get(auth_client, CUSTOMER_CONVERSATIONS_PATH, headers=customer_headers)

    for page in (internal, mine):
        assert set(page) == {"items", "total", "page", "page_size"}
        assert page["page"] == 1
        assert page["page_size"] == DEFAULT_PAGE_SIZE
        assert len(page["items"]) == DEFAULT_PAGE_SIZE

    # 内部端不受限，看到全部；客户端只看得到自己的 105 场。
    assert internal["total"] == SESSION_COUNT + OTHER_SESSION_COUNT
    assert mine["total"] == SESSION_COUNT


def test_the_total_counts_sessions_not_archive_rows(
    auth_client: TestClient, seeded_lists: None
):
    """`total` 是「多少场会话」，不是归档行数：105 场共 129 条归档（其中一场 25 条消息）。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            archive_rows = len(list(session.scalars(select(ConversationArchive.id))))
    finally:
        engine.dispose()

    page = _get(
        auth_client,
        CONVERSATIONS_PATH,
        headers=_internal_headers(auth_client, ADVISOR_USERNAME),
    )

    assert archive_rows == (SESSION_COUNT - 1) * 2 + DEEP_MESSAGE_COUNT + OTHER_SESSION_COUNT * 2
    assert archive_rows > page["total"]
    assert page["total"] == SESSION_COUNT + OTHER_SESSION_COUNT


def test_the_internal_list_can_be_narrowed_to_one_customer(
    auth_client: TestClient, seeded_lists: None
):
    """按客户筛：`total` 是那位客户的场数，不是全部场数。"""
    engine = _engine()
    try:
        other_id = _customer_id(engine, OTHER_CUSTOMER_USERNAME)
    finally:
        engine.dispose()

    page = _get(
        auth_client,
        CONVERSATIONS_PATH,
        headers=_internal_headers(auth_client, ADVISOR_USERNAME),
        user_id=other_id,
    )

    assert page["total"] == OTHER_SESSION_COUNT
    assert set(_session_ids(page["items"])) == {
        _other_session_id(index) for index in range(OTHER_SESSION_COUNT)
    }


# --- 旧上限确实没了 ---


def test_the_old_hundred_session_ceiling_is_gone(
    auth_client: TestClient, seeded_lists: None
):
    """105 场会话一次要得完：`total` 是 105、第二页有 5 场，最早的会话也读得到。

    造数正好越过从前的 `LIST_LIMIT = 100`：上限还在的话，`total` 会是 100，第 101 场
    之后永远翻不到，而屏幕上看起来仍是一份完整的列表。
    """
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)

    first = _get(
        auth_client,
        CUSTOMER_CONVERSATIONS_PATH,
        headers=customer_headers,
        page=1,
        page_size=MAX_PAGE_SIZE,
    )
    second = _get(
        auth_client,
        CUSTOMER_CONVERSATIONS_PATH,
        headers=customer_headers,
        page=2,
        page_size=MAX_PAGE_SIZE,
    )

    assert first["total"] == second["total"] == SESSION_COUNT
    assert [len(first["items"]), len(second["items"])] == [MAX_PAGE_SIZE, SESSION_COUNT - MAX_PAGE_SIZE]
    # 第 101 场之后的那几场确实读得到，最早的一场（索引 0）在最后一页的最后。
    assert _session_ids(second["items"])[-1] == _session_id(DEEP_SESSION_INDEX)


def test_the_old_fifty_row_history_ceiling_is_gone(
    auth_client: TestClient, seeded_lists: None
):
    """55 条留痕一次要得完：`total` 是 55，最早的一条也读得到。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    page = _get(
        auth_client, HISTORY_PATH, headers=headers, page=1, page_size=MAX_PAGE_SIZE
    )

    assert page["total"] == HISTORY_COUNT
    assert len(page["items"]) == HISTORY_COUNT
    assert page["items"][-1]["question"] == f"{HISTORY_QUESTION_PREFIX}0"


def test_the_history_total_is_the_employees_own(
    auth_client: TestClient, seeded_lists: None
):
    """留痕按提问人筛：另一位员工看到的是他自己的（0 条），而不是 advisor1 的 55 条。"""
    advisor = _get(
        auth_client,
        HISTORY_PATH,
        headers=_internal_headers(auth_client, ADVISOR_USERNAME),
    )
    manager = _get(
        auth_client,
        HISTORY_PATH,
        headers=_internal_headers(auth_client, MANAGER_USERNAME),
    )

    assert advisor["total"] == HISTORY_COUNT
    assert manager["total"] == 0
    assert manager["items"] == []


# --- 翻页不重不漏 ---


def test_turning_the_pages_yields_every_session_exactly_once(
    auth_client: TestClient, seeded_lists: None
):
    """三页翻完不重不漏：并集是全部 111 场会话，两两不相交。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    read = _read_all_pages(
        auth_client, CONVERSATIONS_PATH, headers=headers, page_size=50
    )

    expected = {_session_id(index) for index in range(SESSION_COUNT)} | {
        _other_session_id(index) for index in range(OTHER_SESSION_COUNT)
    }
    seen = _session_ids(read["items"])
    assert read["total"] == len(expected)
    assert set(seen) == expected
    assert len(seen) == len(set(seen)) == len(expected)


def test_the_customer_only_sees_their_own_sessions_across_the_pages(
    auth_client: TestClient, seeded_lists: None
):
    """客户侧翻页时可见范围不丢：每一页都只有自己的会话，`total` 也不含别人的。"""
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)

    read = _read_all_pages(
        auth_client,
        CUSTOMER_CONVERSATIONS_PATH,
        headers=customer_headers,
        page_size=50,
    )

    assert read["total"] == SESSION_COUNT
    assert all(session_id.startswith(SESSION_PREFIX) for session_id in _session_ids(read["items"]))


def test_turning_the_pages_yields_every_history_row_exactly_once(
    auth_client: TestClient, seeded_lists: None
):
    """六页翻完不重不漏：并集是全部 55 条留痕。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    read = _read_all_pages(auth_client, HISTORY_PATH, headers=headers, page_size=10)

    ids = _history_ids(read["items"])
    assert read["total"] == HISTORY_COUNT
    assert len(ids) == len(set(ids)) == HISTORY_COUNT


def test_a_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: None
):
    """越界页给空 `items`，`total` 不变——翻过头不是「没有历史」。"""
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)
    advisor_headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    for path, headers, total in (
        (CONVERSATIONS_PATH, advisor_headers, SESSION_COUNT + OTHER_SESSION_COUNT),
        (CUSTOMER_CONVERSATIONS_PATH, customer_headers, SESSION_COUNT),
        (HISTORY_PATH, advisor_headers, HISTORY_COUNT),
    ):
        page = _get(auth_client, path, headers=headers, page=99)

        assert page["items"] == [], path
        assert page["total"] == total, path
        assert page["page"] == 99, path


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_lists: None
):
    """页长超上限是钳制到 100 而不是报错：客户端多要几行不该让翻页整个失效。"""
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)
    advisor_headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    for path, headers in (
        (CONVERSATIONS_PATH, advisor_headers),
        (CUSTOMER_CONVERSATIONS_PATH, customer_headers),
        (HISTORY_PATH, advisor_headers),
    ):
        page = _get(auth_client, path, headers=headers, page_size=1000)
        assert page["page_size"] == MAX_PAGE_SIZE, path


# --- 排序下推：整体有序与稳定排序键 ---


def test_the_session_list_stays_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: None
):
    """排序跨页成立：把三页拼起来，最后发言时间仍然一路倒序。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    read = _read_all_pages(
        auth_client, CONVERSATIONS_PATH, headers=headers, page_size=50
    )

    ended_at = [row["ended_at"] for row in read["items"]]
    assert ended_at == sorted(ended_at, reverse=True)


def test_sessions_within_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_lists: None
):
    """同一秒里结束的会话顺序固定：发言时间是秒精度，兜底键把它定死。

    最后三场挤在同一秒里：它们跨页时在排序键的第一位上分不出先后，靠会话标识兜底。
    读两次拿到的顺序必须逐字相同。
    """
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    first = _get(
        auth_client, CONVERSATIONS_PATH, headers=headers, page_size=MAX_PAGE_SIZE
    )
    second = _get(
        auth_client, CONVERSATIONS_PATH, headers=headers, page_size=MAX_PAGE_SIZE
    )

    assert _session_ids(first["items"]) == _session_ids(second["items"])
    assert len({row["ended_at"] for row in first["items"][:3]}) == 1
    assert _session_ids(first["items"])[:3] == sorted(
        (
            _session_id(SESSION_COUNT - 3),
            _session_id(SESSION_COUNT - 2),
            _session_id(SESSION_COUNT - 1),
        )
    )


def test_the_history_stays_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: None
):
    """排序跨页成立：六页拼起来，留痕时间仍然一路倒序。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    read = _read_all_pages(auth_client, HISTORY_PATH, headers=headers, page_size=10)

    create_time = [row["create_time"] for row in read["items"]]
    assert create_time == sorted(create_time, reverse=True)


def test_history_rows_within_the_same_second_have_one_fixed_order(
    auth_client: TestClient, seeded_lists: None
):
    """同一秒里的留痕顺序固定：靠标识倒序兜底，两次读到的顺序逐字相同。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)

    first = _get(
        auth_client, HISTORY_PATH, headers=headers, page_size=MAX_PAGE_SIZE
    )
    second = _get(
        auth_client, HISTORY_PATH, headers=headers, page_size=MAX_PAGE_SIZE
    )

    assert _history_ids(first["items"]) == _history_ids(second["items"])
    assert len({row["create_time"] for row in first["items"][:3]}) == 1
    # 同一秒的三条按标识倒序：后写下的在前。
    assert _history_ids(first["items"])[:3] == sorted(
        _history_ids(first["items"])[:3], reverse=True
    )


# --- 会话详情内嵌的 messages 保持不分页 ---


def test_the_session_detail_still_returns_the_whole_transcript(
    auth_client: TestClient, seeded_lists: None
):
    """25 条消息的会话，详情一次给全：回看的是这一场会话，与列表的页长无关。"""
    headers = _internal_headers(auth_client, ADVISOR_USERNAME)
    session_id = _session_id(DEEP_SESSION_INDEX)

    detail = _get(
        auth_client, f"{CONVERSATIONS_PATH}/{session_id}", headers=headers
    )

    assert detail["session_id"] == session_id
    assert detail["message_count"] == DEEP_MESSAGE_COUNT
    assert len(detail["messages"]) == DEEP_MESSAGE_COUNT


def test_the_customer_session_detail_still_returns_the_whole_transcript(
    auth_client: TestClient, seeded_lists: None
):
    """客户侧详情同样不分页。"""
    customer_headers, _ = _customer_headers(auth_client, CUSTOMER_USERNAME)
    session_id = _session_id(DEEP_SESSION_INDEX)

    detail = _get(
        auth_client, f"{CUSTOMER_CONVERSATIONS_PATH}/{session_id}", headers=customer_headers
    )

    assert len(detail["messages"]) == DEEP_MESSAGE_COUNT
