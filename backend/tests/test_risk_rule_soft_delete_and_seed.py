"""软删、编号不复用、种子只在空表播种——规则生命周期数据层的三条语义。

这三件事必须一起成立才有意义：删除之所以可查，是因为行还留在库里（软删）；编号之所以
能当跨表标识，是因为它永不复用（`fin_risk_alert.rule_codes` 是命中那一刻的快照，永不
回收）；而种子之所以不再让删除失去意义，是因为它只在**表为空**时播种——判空若按
「未删行数」来数，20 条全被软删后表会被判为空，重新插入 R001–R020 撞上
`uk_risk_rule_code`，服务起不来（ADR-0027）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from re import findall
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    CheckConstraint,
    Select,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Employee, RiskRule, RiskRuleChange
from app.db.seed import seed
from app.risk_monitoring import service
from app.risk_monitoring.context import CustomerSnapshot, MonitoringContext, TransactionEvent
from app.risk_monitoring.rules import RULE_CATEGORIES
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"

# 软删写入的时间戳固定下来：用例只关心「这一列非空」，不关心它具体是哪一刻。
SOFT_DELETE_TIME = datetime(2026, 9, 24, 10, 0, 0)

# MySQL 的「CHECK 约束被违反」错误码。
CHECK_VIOLATION_ERRNO = 3819

BASE_TIME = datetime(2026, 9, 10, 10, 0, 0)


def _test_url() -> str:
    url = get_settings().test_database_url
    assert "wealth_test" in url
    return url


def _engine() -> Engine:
    return create_engine(_test_url())


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _listing(
    client: TestClient,
    headers: dict[str, str],
    *,
    include_deleted: bool | None = None,
) -> dict[str, Any]:
    """规则列表的一页。`include_deleted=None` 表示**不带这个参数**，走默认值。"""
    params: dict[str, Any] = {"page_size": 100}
    if include_deleted is not None:
        params["include_deleted"] = include_deleted
    response = client.get("/api/internal/risk-rules", headers=headers, params=params)
    assert response.status_code == 200
    return response.json()["data"]


def _codes(page: dict[str, Any]) -> set[str]:
    return {rule["rule_code"] for rule in page["items"]}


def _rule_id(client: TestClient, rule_code: str, headers: dict[str, str]) -> int:
    page = _listing(client, headers)
    return next(rule["id"] for rule in page["items"] if rule["rule_code"] == rule_code)


@contextmanager
def _session() -> Iterator[OrmSession]:
    """一次数据库会话。测试库跨运行持久，所以每个 helper 自己开关一次连接。"""
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            yield session
    finally:
        engine.dispose()


def _soft_delete_rule(rule_id: int) -> None:
    with _session() as session:
        session.execute(
            update(RiskRule).where(RiskRule.id == rule_id).values(deleted_at=SOFT_DELETE_TIME)
        )
        session.commit()


def _soft_delete_every_rule() -> int:
    with _session() as session:
        result = session.execute(update(RiskRule).values(deleted_at=SOFT_DELETE_TIME))
        session.commit()
        return result.rowcount


def _restore_deleted_rules() -> None:
    """把 `deleted_at` 抹回空。

    软删是行上的一个时间戳，跨用例残留会让别的用例看不到规则（测试库跨运行持久）。
    """
    with _session() as session:
        session.execute(update(RiskRule).values(deleted_at=None))
        session.commit()


def _rule_counts() -> tuple[int, int]:
    """(总行数, 未删行数)。两个数分开取，是为了让「表非空」与「没有活着的规则」可分辨。"""
    with _session() as session:
        total = session.scalar(select(func.count()).select_from(RiskRule)) or 0
        alive = (
            session.scalar(
                select(func.count())
                .select_from(RiskRule)
                .where(RiskRule.deleted_at.is_(None))
            )
            or 0
        )
    return total, alive


def _matched_rule_codes(amount: str) -> set[str]:
    with _session() as session:
        context = MonitoringContext(
            event=TransactionEvent(
                transaction_id=1,
                customer_id=1,
                product_id=1,
                transaction_type="申购",
                amount=Decimal(amount),
                occurred_at=BASE_TIME,
            ),
            history=(),
            product_risk_level=None,
            customer=CustomerSnapshot(),
        )
        return {hit.rule_code for hit in service.match_enabled_rules(session, context)}


def _check_constraint_values(model: Any, name: str) -> set[str]:
    for arg in model.__table_args__:
        if isinstance(arg, CheckConstraint) and arg.name == name:
            return set(findall(r"'([^']+)'", str(arg.sqltext)))
    raise AssertionError(f"缺少约束 {name}")


def _write_is_rejected(statement: Any) -> bool:
    """这条写入在库里被拒绝了吗——只问库收不收，回滚不留行。

    模型的 `__table_args__` 只能证明代码里写着这条约束，库里的那一份要由数据库自己
    拒绝一个越界取值来证明：迁移漏写时，这里是唯一会失败的地方。

    MySQL 把 CHECK 违反报成 errno 3819，SQLAlchemy 把它归进 `DBAPIError`（不是
    `IntegrityError`），所以按错误码认——别的故障照旧冒出来，不会被当成「拒绝了」。

    会话不 `commit`：关掉时这条写入随事务一起回滚，库里不留行。
    """
    with _session() as session:
        try:
            session.execute(statement)
        except DBAPIError as exc:
            assert exc.orig is not None, exc
            assert exc.orig.args[0] == CHECK_VIOLATION_ERRNO, exc
            return True
        return False


def _change_row(change_type: str) -> Any:
    return insert(RiskRuleChange).values(
        rule_id=_rule_id_of("R001"),
        change_type=change_type,
        old_value={},
        new_value={},
        changed_by=select(func.min(Employee.id)).scalar_subquery(),
        reason="约束自测",
        changed_at=SOFT_DELETE_TIME,
    )


def _category_is_rejected(category: str) -> bool:
    return _write_is_rejected(
        update(RiskRule).where(RiskRule.rule_code == "R001").values(category=category)
    )


def _rule_id_of(rule_code: str) -> Select:
    return select(RiskRule.id).where(RiskRule.rule_code == rule_code).scalar_subquery()


@pytest.fixture(autouse=True)
def _no_leftover_soft_deletes(auth_client: TestClient) -> Iterator[None]:
    _restore_deleted_rules()
    try:
        yield
    finally:
        _restore_deleted_rules()


def test_a_soft_deleted_rule_leaves_the_default_listing(auth_client: TestClient):
    """软删的规则默认不出现，`include_deleted=true` 时带着软删标记回来。

    过滤在服务端：分页的 `total` 与当前页由同一条查询派生（ADR-0024），谁过滤谁就得
    同时管住这两个数字，留给前端只会让「共 N 条」与翻到底能看到的条数对不上。
    """
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    total_before = _listing(auth_client, headers)["total"]

    _soft_delete_rule(_rule_id(auth_client, "R001", headers))

    default_page = _listing(auth_client, headers)
    assert default_page["total"] == total_before - 1
    assert "R001" not in _codes(default_page)

    with_deleted = _listing(auth_client, headers, include_deleted=True)
    assert with_deleted["total"] == total_before
    assert "R001" in _codes(with_deleted)
    deleted_row = next(rule for rule in with_deleted["items"] if rule["rule_code"] == "R001")
    assert deleted_row["deleted_at"] is not None

    alive_row = next(rule for rule in _listing(auth_client, headers)["items"])
    assert alive_row["deleted_at"] is None


def test_a_soft_deleted_rule_no_longer_participates_in_matching(auth_client: TestClient):
    """软删的规则不再参与匹配——它是「这条规则不该存在」，不是「暂时不判定」。

    `enabled` 承担的是后者。已有预警不受影响：预警是命中那一刻固化的事实记录。
    """
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    assert _matched_rule_codes("60000.00") == {"R001"}

    _soft_delete_rule(_rule_id(auth_client, "R001", headers))

    assert _matched_rule_codes("60000.00") == set()


def test_seeding_a_table_full_of_soft_deleted_rules_is_a_no_op(auth_client: TestClient):
    """20 条全被软删后重启：不重新播种，也不撞 `uk_risk_rule_code`。

    判空若按 `deleted_at is null` 数行数，这张表会被判为「空」，种子重新插入
    R001–R020 撞上唯一约束，`commit` 当场抛 IntegrityError——线上是服务起不来。
    """
    total_before, _ = _rule_counts()
    assert _soft_delete_every_rule() == total_before
    assert _rule_counts() == (total_before, 0)

    try:
        # 「重启」：迁移不会重跑，重跑的是种子这一步。回放会重新写入交易（此刻没有
        # 规则可命中，因此不产生预警），结尾的 finally 会把这次重启撤掉。
        # 若判空按未删行数来数，这一步会重新插入 R001–R020 并抛 IntegrityError。
        seed(_test_url())

        assert _rule_counts() == (total_before, 0)
    finally:
        _restore_deleted_rules()
        seed(_test_url())


def test_soft_deleting_the_highest_code_does_not_free_it(auth_client: TestClient):
    """编号不复用：下一条取**曾经出现过的最大值 + 1**，已软删的编号照样占位。

    种子刚播下时最大值是 R020，所以这条断言的形状就是「删掉 R020 之后拿到的不是
    R020」。已软删的行不过滤掉，是因为 `fin_risk_alert.rule_codes` 里的 `R0xx` 是
    外部标识：复用编号会让按编号回查的历史预警指向另一条规则（ADR-0027）。
    """
    with _session() as session:
        codes = sorted(session.scalars(select(RiskRule.rule_code)).all())
        highest = codes[-1]
        expected_next = f"R{int(highest.removeprefix('R')) + 1:03d}"

        assert service.next_rule_code(session) == expected_next

        session.execute(
            update(RiskRule)
            .where(RiskRule.rule_code == highest)
            .values(deleted_at=SOFT_DELETE_TIME)
        )
        session.commit()

        assert service.next_rule_code(session) == expected_next
        assert service.next_rule_code(session) != highest


def test_the_change_type_list_covers_the_five_rule_writes():
    """五个写动作各是一种留痕类型，库里的清单与代码里的常量是同一份（0015 的体例）。"""
    assert _check_constraint_values(RiskRuleChange, "ck_risk_rule_change_type") == {
        service.CHANGE_TYPE_CREATE,
        service.CHANGE_TYPE_UPDATE,
        service.CHANGE_TYPE_DELETE,
        service.CHANGE_TYPE_THRESHOLD,
        service.CHANGE_TYPE_ENABLED,
    }


def test_the_category_and_change_type_lists_are_enforced_by_the_database():
    """两条清单都要真的落在库里，且与代码里的注册表逐字一致。

    分类是专员在表单上选的下拉，此前是唯一没有约束的那一列；`change_type` 从 2 个值
    扩到 5 个。逐值走一遍而不是抽查两个：清单是三份硬编码副本（迁移、模型、`rules.py`），
    漏掉或写错某一个值时，只有这里会失败。
    """
    for change_type in (
        service.CHANGE_TYPE_CREATE,
        service.CHANGE_TYPE_UPDATE,
        service.CHANGE_TYPE_DELETE,
        service.CHANGE_TYPE_THRESHOLD,
        service.CHANGE_TYPE_ENABLED,
    ):
        assert _write_is_rejected(_change_row(change_type)) is False, change_type
    assert _write_is_rejected(_change_row("随便")) is True

    for category in RULE_CATEGORIES:
        assert _category_is_rejected(category) is False, category
    assert _category_is_rejected("随便") is True
