"""工单与知识文档两个列表的分页与排序下推（ADR-0024，`list-pagination` #06）。

两份列表都是从前的纯 `.all()` 读取路径，套统一契约是机械改动——但这个文件要钉住三件
单看一页看不出来的事：

- 形状恒为 `{items, total, page, page_size}`，且 `total` 是**过滤后**的总数（工单按状态筛、
  文档按类型 / 状态筛，都算在内）；
- 翻页不重不漏、越界页空 `items` 而 `total` 不变、页长超上限被钳制而不是报错；
- 排序键稳定：建单时间与入库时间都是秒精度，排在第一位的键分不出先后的那些记录靠标识
  兜底。顺序不稳定时，翻页会把同一条读两次、另一条谁也读不到，而每一页看起来都正常。

造数直接写两张表（`biz_work_order`、`fin_knowledge_meta`）：这里要断的是读侧；走受理侧
建 25 张工单只会把用例拖长，而建单路径自己另有断言（`test_work_order_derivation_and_handling`）。

**造数时间取在「现在」之后**（2027 年）：测试库里的知识元数据长期堆积（下架的文档只改
状态、不删行，写入量以千计），取当前时刻造数的话本次造的行会排在几千行之后，翻不到也
断言不了。把本次造的行放在最前，断言就只依赖这次造出来的东西，同时 `total` 改用与库里
同口径的行数对照（见 `_db_row_count`）——这样既不受残留影响，又钉住了 `total` 的口径。

清场：工单与工单流转全清（与 `test_risk_lists_pagination` 同一做法，这两张表里没有需要
跨用例保留的东西）；文档只清本次按前缀造出来的行——下架文档的分块镜像还在
`fin_knowledge_chunk` 里，按状态大删会撞外键，也不是这个用例该管的事。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer, Employee, KnowledgeMeta, WorkOrder, WorkOrderTransition
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
INTERNAL_USERNAME = "advisor1"
RISK_OFFICER_USERNAME = "risk1"
CUSTOMER_USERNAME = "wangc1"

WORK_ORDERS_PATH = "/api/internal/work-orders"
DOCUMENTS_PATH = "/api/internal/knowledge/documents"

# 本次造数的标记前缀：断言与清场都认这两个前缀，不与别的用例的行混淆。
WORK_ORDER_NO_PREFIX = "WO2704"
SOURCE_FILE_PREFIX = "pagination-case-"

# 默认页长与上限（ADR-0024）。
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 25 行：刻意凑成「一页装不下、两页有余」。
ROW_COUNT = 25
# 前 22 行各占一秒，最后三行挤在同一秒里——同秒是排序兜底唯一会暴露的地方。
SAME_SECOND_FROM = 22

WINDOW_START = datetime(2027, 4, 1, 9, 0, 0)

STATUS_PENDING = "待处理"
STATUS_IN_PROGRESS = "处理中"
PENDING_COUNT = 13

# 每五张工单挂一位客户：按客户筛的出 5 张，够翻两页（页长 3）。
CUSTOMER_LINKED_STEP = 5
CUSTOMER_LINKED_COUNT = 5

ORDER_TYPE_COMPLAINT = "客户投诉"

KNOWLEDGE_TYPES = ("FAQ", "政策", "产品")
POLICY_TYPE = "政策"
POLICY_COUNT = 8
STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"

# 额外两份已下架的文档：默认列表要把它们排掉，显式按 expired 筛才看得到。
EXPIRED_COUNT = 2


def _created_at(index: int) -> datetime:
    return WINDOW_START + timedelta(seconds=min(index, SAME_SECOND_FROM))


def _work_order_no(index: int) -> str:
    return f"{WORK_ORDER_NO_PREFIX}{index:04d}"


def _source_file(index: int) -> str:
    return f"{SOURCE_FILE_PREFIX}{index:04d}.txt"


def _engine():
    return create_engine(get_settings().test_database_url)


def _employee_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Employee.id).where(Employee.username == username))
    assert value is not None
    return int(value)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _purge(engine) -> None:
    """清掉工单与本次造出来的文档。留痕表先删：它指着工单，反过来删会撞外键。"""
    with OrmSession(engine) as session:
        session.execute(delete(WorkOrderTransition))
        session.execute(delete(WorkOrder))
        session.execute(
            delete(KnowledgeMeta).where(KnowledgeMeta.source_file.like(f"{SOURCE_FILE_PREFIX}%"))
        )
        session.commit()


def _add_work_orders(engine, *, handler_id: int, customer_id: int) -> None:
    """25 张外部来源的工单：状态轮着来（待处理 13 张、处理中 12 张），每五张挂一位客户。

    来源预警一律留空——唯一约束只挡「一条预警一张工单」，留空的列可以有任意多行。
    """
    with OrmSession(engine) as session:
        for index in range(ROW_COUNT):
            status = STATUS_PENDING if index % 2 == 0 else STATUS_IN_PROGRESS
            session.add(
                WorkOrder(
                    work_order_no=_work_order_no(index),
                    order_type=ORDER_TYPE_COMPLAINT,
                    sub_type=None,
                    source_alert_id=None,
                    customer_id=customer_id if index % CUSTOMER_LINKED_STEP == 0 else None,
                    submitter_identity="internal",
                    submitter_id=handler_id,
                    handler_id=handler_id,
                    current_node=status,
                    priority="普通",
                    status=status,
                    biz_content={"description": f"用例造数 {index}"},
                    handle_reason=f"用例造数 {index}",
                    handle_result=None,
                    create_time=_created_at(index),
                    update_time=_created_at(index),
                )
            )
        session.commit()


def _add_documents(engine) -> None:
    """25 份在架文档（类型轮着来：FAQ 9 份、政策 8 份、产品 8 份）+ 2 份已下架。"""
    with OrmSession(engine) as session:
        for index in range(ROW_COUNT):
            session.add(
                KnowledgeMeta(
                    knowledge_type=KNOWLEDGE_TYPES[index % len(KNOWLEDGE_TYPES)],
                    title=f"用例文档 {index}",
                    source_file=_source_file(index),
                    minio_path=None,
                    milvus_collection=None,
                    version="1",
                    status=STATUS_ACTIVE,
                    stage=None,
                    failure_reason=None,
                    chunk_count=1,
                    expire_at=None,
                    create_time=_created_at(index),
                    update_time=_created_at(index),
                )
            )
        for offset in range(EXPIRED_COUNT):
            index = ROW_COUNT + offset
            session.add(
                KnowledgeMeta(
                    knowledge_type="FAQ",
                    title=f"用例文档（已下架）{index}",
                    source_file=_source_file(index),
                    minio_path=None,
                    milvus_collection=None,
                    version="1",
                    status=STATUS_EXPIRED,
                    stage=None,
                    failure_reason=None,
                    chunk_count=0,
                    expire_at=_created_at(index),
                    create_time=_created_at(index),
                    update_time=_created_at(index),
                )
            )
        session.commit()


@pytest.fixture
def seeded_lists(auth_client: TestClient) -> Iterator[None]:
    """本用例的 25 张工单 + 27 份文档，跑完清掉。"""
    engine = _engine()
    _purge(engine)
    _add_work_orders(
        engine,
        handler_id=_employee_id(engine, RISK_OFFICER_USERNAME),
        customer_id=_customer_id(engine, CUSTOMER_USERNAME),
    )
    _add_documents(engine)
    try:
        yield
    finally:
        _purge(engine)
        engine.dispose()


def _get(client: TestClient, path: str, *, username: str = INTERNAL_USERNAME, **params) -> dict:
    response = client.get(path, headers=_headers(client, username), params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _read_all_pages(
    client: TestClient,
    path: str,
    *,
    page_size: int,
    username: str = INTERNAL_USERNAME,
    **params,
) -> dict:
    """把全部页翻一遍再拼起来：排序与「不重不漏」只有拼起来才看得见。"""
    items: list[dict] = []
    page = 1
    while True:
        data = _get(client, path, username=username, page=page, page_size=page_size, **params)
        items.extend(data["items"])
        if page * page_size >= data["total"]:
            return {"items": items, "total": data["total"]}
        page += 1


def _db_row_count(where) -> int:
    """库里与同一组筛选条件相符的行数——`total` 要对照的那个数。

    断言是「接口给的 `total` 与库里的行数一致」：口径写两遍（一遍在接口里，一遍在这个
    谓词里），若接口把 `total` 错当成「全表行数」或「本页条数」，两个数就对不上。
    """
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return len(list(session.scalars(select(KnowledgeMeta.id).where(where))))
    finally:
        engine.dispose()


def _work_order_ids(rows: list[dict]) -> list[int]:
    return [row["id"] for row in rows]


def _document_ids(rows: list[dict]) -> list[int]:
    return [row["knowledge_id"] for row in rows]


def _seeded_document_ids(engine, *, status: str | None = None) -> set[int]:
    where = [KnowledgeMeta.source_file.like(f"{SOURCE_FILE_PREFIX}%")]
    if status is not None:
        where.append(KnowledgeMeta.status == status)
    with OrmSession(engine) as session:
        return set(session.scalars(select(KnowledgeMeta.id).where(*where)))


# --- 响应形状与 total 的口径 ---


def test_both_lists_answer_with_the_same_page_shape(
    auth_client: TestClient, seeded_lists: None
):
    """两个列表形状一致：只有 `items`/`total`/`page`/`page_size`，没有第二套字段名。"""
    work_orders = _get(auth_client, WORK_ORDERS_PATH, username=RISK_OFFICER_USERNAME)
    documents = _get(auth_client, DOCUMENTS_PATH)

    for page in (work_orders, documents):
        assert set(page) == {"items", "total", "page", "page_size"}
        assert page["page"] == 1
        assert page["page_size"] == DEFAULT_PAGE_SIZE
        assert len(page["items"]) == DEFAULT_PAGE_SIZE

    assert work_orders["total"] == ROW_COUNT
    # 默认列表不含下架的文档，`total` 不把它们算进来——与库里同口径的行数一致。
    assert documents["total"] == _db_row_count(KnowledgeMeta.status != STATUS_EXPIRED)


def test_the_total_is_the_filtered_count_not_the_page_or_the_whole_table(
    auth_client: TestClient, seeded_lists: None
):
    """`total` 跟着筛选走：待处理 13 张、政策 8 份，都是过滤后的条数而不是本页条数。"""
    pending = _get(
        auth_client, WORK_ORDERS_PATH, username=RISK_OFFICER_USERNAME, status=STATUS_PENDING
    )
    assert pending["total"] == PENDING_COUNT
    assert {row["status"] for row in pending["items"]} == {STATUS_PENDING}

    policy = _get(auth_client, DOCUMENTS_PATH, knowledge_type=POLICY_TYPE)
    assert policy["total"] >= POLICY_COUNT
    assert policy["total"] == _db_row_count(
        (KnowledgeMeta.knowledge_type == POLICY_TYPE) & (KnowledgeMeta.status != STATUS_EXPIRED)
    )
    assert {row["knowledge_type"] for row in policy["items"]} == {POLICY_TYPE}

    expired = _get(auth_client, DOCUMENTS_PATH, status=STATUS_EXPIRED)
    assert expired["total"] == _db_row_count(KnowledgeMeta.status == STATUS_EXPIRED)
    assert {row["status"] for row in expired["items"]} == {STATUS_EXPIRED}


def test_the_default_document_list_hides_what_was_taken_off_the_shelf(
    auth_client: TestClient, seeded_lists: None
):
    """下架的文档默认不出现，但显式按 expired 筛时仍然查得到（下架不是销毁）。

    造数时间（2027 年）比历史残留（历次测试运行造出来的、已被下架的那些行）要晚，所以
    本次下架的那两份是 expired 列表里最新的两条——只读第一页就够，往下翻的是几千行历史
    下架文档，与本用例无关。
    """
    engine = _engine()
    try:
        expired_seeded = _seeded_document_ids(engine, status=STATUS_EXPIRED)
    finally:
        engine.dispose()

    default = _read_all_pages(auth_client, DOCUMENTS_PATH, page_size=MAX_PAGE_SIZE)
    expired = _get(auth_client, DOCUMENTS_PATH, status=STATUS_EXPIRED)

    assert len(expired_seeded) == EXPIRED_COUNT
    assert _document_ids(expired["items"])[:EXPIRED_COUNT] == sorted(expired_seeded, reverse=True)
    assert set(_document_ids(default["items"])).isdisjoint(expired_seeded)


# --- 翻页不重不漏 ---


def test_turning_the_pages_yields_every_work_order_exactly_once(
    auth_client: TestClient, seeded_lists: None
):
    read = _read_all_pages(
        auth_client, WORK_ORDERS_PATH, page_size=10, username=RISK_OFFICER_USERNAME
    )

    assert read["total"] == ROW_COUNT
    ids = _work_order_ids(read["items"])
    # 25 个互不相同的标识：少一个或重一个都会在这里现形。
    assert len(ids) == len(set(ids)) == ROW_COUNT


def test_turning_the_pages_yields_every_document_exactly_once(
    auth_client: TestClient, seeded_lists: None
):
    engine = _engine()
    try:
        active_seeded = _seeded_document_ids(engine, status=STATUS_ACTIVE)
    finally:
        engine.dispose()

    read = _read_all_pages(auth_client, DOCUMENTS_PATH, page_size=10)
    ids = _document_ids(read["items"])

    assert len(active_seeded) == ROW_COUNT
    # 本次造出来的 25 份在翻页里各出现一次；同一个标识出现两次同样是错的。
    assert active_seeded <= set(ids)
    assert len(ids) == len(set(ids)) == read["total"]


def test_the_filter_stays_on_while_paging(auth_client: TestClient, seeded_lists: None):
    """翻页只换页码：第 2 页仍是「待处理的第 2 页」，不是「全部工单的第 2 页」。"""
    first = _get(
        auth_client,
        WORK_ORDERS_PATH,
        username=RISK_OFFICER_USERNAME,
        status=STATUS_PENDING,
        page=1,
        page_size=10,
    )
    second = _get(
        auth_client,
        WORK_ORDERS_PATH,
        username=RISK_OFFICER_USERNAME,
        status=STATUS_PENDING,
        page=2,
        page_size=10,
    )

    assert first["total"] == second["total"] == PENDING_COUNT
    assert {row["status"] for row in second["items"]} == {STATUS_PENDING}
    assert set(_work_order_ids(first["items"])).isdisjoint(_work_order_ids(second["items"]))


def test_the_customer_filter_stays_on_across_the_pages(
    auth_client: TestClient, seeded_lists: None
):
    """按客户筛：`total` 是这位客户的单数，第 2 页仍是同一条件的第 2 页。

    客户经理的可见范围（只看名下客户）走的就是这条筛选，所以它比状态筛选更值得钉住：
    范围一丢，第 2 页会变成「所有人的第 2 页」，而屏幕上没有任何一处会说这件事。
    """
    engine = _engine()
    try:
        customer_id = _customer_id(engine, CUSTOMER_USERNAME)
    finally:
        engine.dispose()

    first = _get(
        auth_client,
        WORK_ORDERS_PATH,
        username=RISK_OFFICER_USERNAME,
        customer_id=customer_id,
        page=1,
        page_size=3,
    )
    second = _get(
        auth_client,
        WORK_ORDERS_PATH,
        username=RISK_OFFICER_USERNAME,
        customer_id=customer_id,
        page=2,
        page_size=3,
    )

    assert first["total"] == second["total"] == CUSTOMER_LINKED_COUNT
    assert [len(first["items"]), len(second["items"])] == [3, 2]
    assert {row["customer_id"] for row in second["items"]} == {customer_id}
    assert set(_work_order_ids(first["items"])).isdisjoint(_work_order_ids(second["items"]))


def test_a_page_beyond_the_last_one_is_empty_but_the_total_stands(
    auth_client: TestClient, seeded_lists: None
):
    """越界页给空 `items`，`total` 不变——翻过头不是「没有工单」。"""
    for path, total, username in (
        (WORK_ORDERS_PATH, ROW_COUNT, RISK_OFFICER_USERNAME),
        (DOCUMENTS_PATH, _db_row_count(KnowledgeMeta.status != STATUS_EXPIRED), INTERNAL_USERNAME),
    ):
        page = _get(auth_client, path, username=username, page=99)

        assert page["items"] == [], path
        assert page["total"] == total, path
        assert page["page"] == 99, path


def test_a_page_size_above_the_ceiling_is_clamped_not_rejected(
    auth_client: TestClient, seeded_lists: None
):
    """页长超上限是钳制到 100 而不是报错：客户端多要几行不该让翻页整个失效。"""
    for path, username in (
        (WORK_ORDERS_PATH, RISK_OFFICER_USERNAME),
        (DOCUMENTS_PATH, INTERNAL_USERNAME),
    ):
        page = _get(auth_client, path, username=username, page_size=1000)
        assert page["page_size"] == MAX_PAGE_SIZE, path

    # 工单只有本次造出来的 25 张：一次要完能全部拿到。
    work_orders = _get(
        auth_client, WORK_ORDERS_PATH, username=RISK_OFFICER_USERNAME, page_size=1000
    )
    assert work_orders["total"] == ROW_COUNT
    assert len(work_orders["items"]) == ROW_COUNT


# --- 排序下推：整体有序与稳定排序键 ---


def test_the_work_order_list_stays_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: None
):
    read = _read_all_pages(
        auth_client, WORK_ORDERS_PATH, page_size=10, username=RISK_OFFICER_USERNAME
    )

    created_at = [row["created_at"] for row in read["items"]]
    assert created_at == sorted(created_at, reverse=True)

    # 同一秒建的三张单：读两次拿到的顺序逐字相同，靠 `id` 兜底而不是查询计划的偶然。
    first = _get(
        auth_client, WORK_ORDERS_PATH, username=RISK_OFFICER_USERNAME, page_size=MAX_PAGE_SIZE
    )
    second = _get(
        auth_client, WORK_ORDERS_PATH, username=RISK_OFFICER_USERNAME, page_size=MAX_PAGE_SIZE
    )
    assert _work_order_ids(first["items"]) == _work_order_ids(second["items"])
    assert len({row["created_at"] for row in first["items"][:3]}) == 1


def test_the_document_list_stays_newest_first_across_the_page_boundary(
    auth_client: TestClient, seeded_lists: None
):
    read = _read_all_pages(auth_client, DOCUMENTS_PATH, page_size=10)

    create_time = [row["create_time"] for row in read["items"]]
    assert create_time == sorted(create_time, reverse=True)

    first = _get(auth_client, DOCUMENTS_PATH, page_size=MAX_PAGE_SIZE)
    second = _get(auth_client, DOCUMENTS_PATH, page_size=MAX_PAGE_SIZE)
    assert _document_ids(first["items"]) == _document_ids(second["items"])
    # 同一秒入库的三份：顺序在两次读之间必须一致——不一致时，翻页会漏读或重读。
    assert len({row["create_time"] for row in first["items"][:3]}) == 1
