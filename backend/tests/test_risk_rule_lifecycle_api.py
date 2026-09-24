"""规则的创建、修改、删除三个写入口，以及它们各自的那一条留痕。

规则可以创建之后，「改了什么就不再是同一条规则」必须当场答清楚（ADR-0026）：判定形状与
阈值、启停都不在 `PATCH /{id}` 里——带着 `field` / `operator` / `window_hours` /
`threshold` / `enabled` 任一字段来的请求一律 400，因为静默忽略会让专员以为自己改掉了判定
形状，而判定形状是规则的身份。删除是软删（ADR-0027）：行留在库里、变更记录仍可读、历史
预警快照一字不动、编号不复用。

一次写操作一条留痕，五个动作各一种 `change_type`，五个入口都要求非空理由。留痕里装的是
快照而不是「这次动了哪一列」：新建与删除各装**整份配置**（无 → 有、有 → 无），修改装
**整份可编辑配置**——只带 `rule_name` 的请求若把留痕写成只含名称，「这条规则当时是什么样」
在记录里就断了。

新规则从**下一笔交易**起生效（Q18）：本文件里凡涉及预警的用例都走真实链路提交交易，
不依赖任何回算。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    Product,
    RiskAlert,
    RiskRule,
    RiskRuleChange,
    Transaction,
    WorkOrder,
    WorkOrderTransition,
)
from app.risk_monitoring.rules import RISK_RULE_SEEDS
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"
RISK_OFFICER_NAME = "周风控"

BASE_PATH = "/api/internal/risk-rules"
SUBMIT_PATH = "/api/internal/transaction-events"
ALERTS_PATH = "/api/internal/risk-alerts"

# 测试库跨运行持久，交易与预警按「本条用例造出来的那批」清：种子里那五笔历史成交的
# `create_time` 是 2018–2022 年，落在下界之前。
TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

SEED_CODES = frozenset(spec.rule_code for spec in RISK_RULE_SEEDS)

# 一份合法的创建请求：金额 ≥ 30 万。每条用例按需要覆盖其中一两项，把某一档单独搞错。
CREATE_BODY: dict[str, Any] = {
    "rule_name": "本机构客户单笔大额转入",
    "category": "大额交易",
    "description": "",
    "field": "amount",
    "operator": "gte",
    "threshold": {"value": "300000"},
    "alert_level": "中度",
    "reason": "本地口径：本机构客户的大额口径高于申报阈值",
}

# 历史预警那条断言要的那笔交易（与 test_risk_alert_queries 用同一组种子数据）：
# 5 万只命中 R001，单条命中即轻度。
CUSTOMER_USERNAME = "wangc1"
PRODUCT_CODE = "F000001"
LIGHT_AMOUNT = "50000.00"


def _engine():
    return create_engine(get_settings().test_database_url)


@contextmanager
def _session() -> Iterator[OrmSession]:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            yield session
    finally:
        engine.dispose()


def _purge_test_artifacts() -> None:
    """把库恢复成「只有 20 条种子规则、没有多出来的交易与预警」的样子。

    测试库跨运行持久，而本文件造出来的规则、交易与预警都会留下：一个多出来的 `R021`
    会让「列表里正好 20 条」那条断言失败，一条留下的预警会让预警列表看到别人的行。因此
    清理在每条用例前后各做一次——前一次兜住上一次中断运行的残留。

    删规则时先删它的变更记录（子表指着它），删预警时先删工单（`source_alert_id` 指着
    预警）。标识一律先取进 Python 再删：MySQL 不允许在 DELETE 的子查询里再读同一张表
    （错误 1093，`seed._discard_previous_replay` 那里有同一条说明）。
    """
    with _session() as session:
        rules = session.scalars(select(RiskRule)).all()
        seed_ids = [rule.id for rule in rules if rule.rule_code in SEED_CODES]
        extra_ids = [rule.id for rule in rules if rule.rule_code not in SEED_CODES]
        if extra_ids:
            session.execute(delete(RiskRuleChange).where(RiskRuleChange.rule_id.in_(extra_ids)))
            session.execute(delete(RiskRule).where(RiskRule.id.in_(extra_ids)))
        if seed_ids:
            session.execute(delete(RiskRuleChange).where(RiskRuleChange.rule_id.in_(seed_ids)))
            session.execute(
                update(RiskRule).where(RiskRule.id.in_(seed_ids)).values(deleted_at=None)
            )

        alert_ids = list(session.scalars(select(RiskAlert.id)))
        if alert_ids:
            order_ids = list(
                session.scalars(
                    select(WorkOrder.id).where(WorkOrder.source_alert_id.in_(alert_ids))
                )
            )
            if order_ids:
                session.execute(
                    delete(WorkOrderTransition).where(
                        WorkOrderTransition.work_order_id.in_(order_ids)
                    )
                )
            session.execute(delete(WorkOrder).where(WorkOrder.source_alert_id.in_(alert_ids)))
            session.execute(delete(RiskAlert).where(RiskAlert.id.in_(alert_ids)))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.commit()


@pytest.fixture(autouse=True)
def _no_leftovers(auth_client: TestClient) -> Iterator[None]:
    _purge_test_artifacts()
    try:
        yield
    finally:
        _purge_test_artifacts()


def _headers(client: TestClient, username: str = RISK_OFFICER_USERNAME) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _post(client: TestClient, headers: dict[str, str], **overrides: Any):
    return client.post(BASE_PATH, headers=headers, json={**CREATE_BODY, **overrides})


def _create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict:
    response = _post(client, headers, **overrides)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _patch(client: TestClient, headers: dict[str, str], rule_id: int, **body: Any):
    return client.patch(f"{BASE_PATH}/{rule_id}", headers=headers, json=body)


def _delete(client: TestClient, headers: dict[str, str], rule_id: int, *, reason: str):
    """删除带请求体：`httpx.Client.delete` 不收 `json`，理由走通用请求入口。"""
    return client.request(
        "DELETE", f"{BASE_PATH}/{rule_id}", headers=headers, json={"reason": reason}
    )


def _changes(client: TestClient, headers: dict[str, str], rule_id: int) -> list[dict]:
    response = client.get(f"{BASE_PATH}/{rule_id}/changes", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _listing(
    client: TestClient, headers: dict[str, str], *, include_deleted: bool | None = None
) -> dict:
    params: dict[str, Any] = {"page_size": 100}
    if include_deleted is not None:
        params["include_deleted"] = include_deleted
    response = client.get(BASE_PATH, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _rule_codes(client: TestClient, headers: dict[str, str]) -> set[str]:
    return {rule["rule_code"] for rule in _listing(client, headers)["items"]}


def _rule_id(client: TestClient, rule_code: str, headers: dict[str, str]) -> int:
    return next(
        rule["id"] for rule in _listing(client, headers)["items"] if rule["rule_code"] == rule_code
    )


def _rule_count() -> int:
    with _session() as session:
        return session.scalar(select(func.count()).select_from(RiskRule)) or 0


def _change_count() -> int:
    with _session() as session:
        return session.scalar(select(func.count()).select_from(RiskRuleChange)) or 0


def _rule_row(rule_id: int) -> dict[str, Any]:
    with _session() as session:
        rule = session.get(RiskRule, rule_id)
        assert rule is not None, f"规则 {rule_id} 应当还在库里（软删不删行）"
        return {
            "rule_code": rule.rule_code,
            "rule_name": rule.rule_name,
            "category": rule.category,
            "description": rule.description,
            "field": rule.field,
            "operator": rule.operator,
            "threshold": dict(rule.threshold or {}),
            "window_hours": rule.window_hours,
            "alert_level": rule.alert_level,
            "weight": rule.weight,
            "enabled": bool(rule.enabled),
            "deleted_at": rule.deleted_at,
        }


def _expected_next_code() -> str:
    """按「曾经出现过的最大值 + 1」算出下一条编号。已软删的编号照样占位。"""
    with _session() as session:
        codes = list(session.scalars(select(RiskRule.rule_code)))
    highest = max(int(code.removeprefix("R")) for code in codes)
    return f"R{highest + 1:03d}"


def _submit_alert(client: TestClient, headers: dict[str, str], *, amount: str) -> dict:
    """走真实链路造一条预警：提交交易 → 落库 → 过规则引擎。"""
    with _session() as session:
        customer_id = session.scalar(
            select(Customer.id).where(Customer.username == CUSTOMER_USERNAME)
        )
        product_id = session.scalar(select(Product.id).where(Product.product_code == PRODUCT_CODE))
    assert customer_id is not None and product_id is not None

    response = client.post(
        SUBMIT_PATH,
        headers=headers,
        json={
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": "申购",
            "amount": amount,
            "occurred_at": TRADE_AT.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    alerts = response.json()["data"]["alerts"]
    assert alerts, "这笔交易本该命中规则"
    return alerts[0]


def _alert_detail(client: TestClient, headers: dict[str, str], alert_id: int) -> dict:
    response = client.get(f"{ALERTS_PATH}/{alert_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


# --- 创建 ---


def test_create_assigns_the_next_code_and_records_the_whole_configuration(
    auth_client: TestClient,
):
    headers = _headers(auth_client)
    expected_code = _expected_next_code()
    before = _rule_count()

    created = _create(auth_client, headers)

    assert created["rule_code"] == expected_code
    assert created["enabled"] is True
    assert created["weight"] == 1.0
    # 描述留空 → 按判定形状自动生成，与预警里的命中依据同一套词。
    assert created["description"] == "交易金额 ≥ 阈值 300000"
    assert _rule_count() == before + 1

    records = _changes(auth_client, headers, created["id"])
    assert [record["change_type"] for record in records] == ["规则新建"]
    record = records[0]
    assert record["old_value"] == {}
    assert record["new_value"] == {
        "rule_code": expected_code,
        "rule_name": CREATE_BODY["rule_name"],
        "category": "大额交易",
        "description": "交易金额 ≥ 阈值 300000",
        "field": "amount",
        "operator": "gte",
        "threshold": {"value": "300000"},
        "window_hours": None,
        "alert_level": "中度",
        "weight": 1.0,
        "enabled": True,
    }
    assert record["reason"] == CREATE_BODY["reason"]
    assert record["changed_by_name"] == RISK_OFFICER_NAME


def test_create_generates_the_description_from_the_shape_and_keeps_a_written_one(
    auth_client: TestClient,
):
    """留空才自动生成；写了就照用（去空白）。

    自动生成的那句是 spec 里给的例子：「7 小时内交易金额的笔数 ≥ 阈值 10」。
    """
    headers = _headers(auth_client)

    generated = _create(
        auth_client,
        headers,
        operator="window_count_gte",
        threshold={"value": "10"},
        window_hours=7,
    )
    assert generated["description"] == "7 小时内交易金额的笔数 ≥ 阈值 10"

    written = _create(auth_client, headers, description="  口径由本地风控会议确定  ")
    assert written["description"] == "口径由本地风控会议确定"


@pytest.mark.parametrize(
    ("override", "fragments"),
    [
        ({"category": "随便"}, ("名录", "规则分类", "随便")),
        ({"field": "不存在的字段"}, ("名录", "规则字段", "不存在的字段")),
        ({"operator": "不存在的算子"}, ("名录", "规则算子", "不存在的算子")),
        ({"alert_level": "特重"}, ("名录", "预警等级", "特重")),
    ],
)
def test_create_refuses_a_value_outside_each_registry(
    auth_client: TestClient, override: dict[str, Any], fragments: tuple[str, str, str]
):
    """名录这一档四列各报各的，且**库里不落行**。"""
    headers = _headers(auth_client)

    response = _post(auth_client, headers, **override)

    assert response.status_code == 400
    for fragment in fragments:
        assert fragment in response.json()["message"]
    assert _rule_count() == len(RISK_RULE_SEEDS)
    assert _change_count() == 0


def test_create_refuses_a_pair_the_matrix_does_not_allow(auth_client: TestClient):
    """`product_id` 配 `gt` 是「各列都合法、搭配不成立」的那一类：拒掉，且一行不落。"""
    headers = _headers(auth_client)

    response = _post(
        auth_client, headers, field="product_id", operator="gt", threshold={"value": "1"}
    )

    assert response.status_code == 400
    assert "搭配" in response.json()["message"]
    assert _rule_count() == len(RISK_RULE_SEEDS)
    assert _change_count() == 0


def test_create_refuses_a_threshold_outside_the_field_value_range(auth_client: TestClient):
    """「24 点」在库里不存在：拒掉，不留一条永远不会命中的规则。"""
    headers = _headers(auth_client)

    response = _post(
        auth_client, headers, field="hour_of_day", operator="gte", threshold={"value": "30"}
    )

    assert response.status_code == 400
    assert "值域" in response.json()["message"]
    assert _rule_count() == len(RISK_RULE_SEEDS)


def test_create_refuses_a_threshold_whose_shape_the_operator_does_not_take(
    auth_client: TestClient,
):
    """形状仍由 `normalize_threshold` 说了算，消息里要带上算子与缺失的键。"""
    headers = _headers(auth_client)

    response = _post(auth_client, headers, operator="gte", threshold={"min": "1", "max": "2"})

    assert response.status_code == 400
    message = response.json()["message"]
    assert "阈值形状" in message
    assert "gte" in message
    assert "value" in message


def test_create_needs_a_window_only_for_the_window_operators(auth_client: TestClient):
    headers = _headers(auth_client)

    missing = _post(
        auth_client,
        headers,
        operator="window_count_gte",
        threshold={"value": "10"},
        field="amount",
    )
    assert missing.status_code == 400
    assert "时间窗" in missing.json()["message"]

    # 非时间窗算子带窗长不是错误，是多余：落库前置空（spec 的参数清单）。
    created = _create(auth_client, headers, window_hours=24)

    assert created["window_hours"] is None
    assert _rule_row(created["id"])["window_hours"] is None


@pytest.mark.parametrize("weight", ["0.40", "5.01"])
def test_create_refuses_a_weight_outside_the_writable_range(
    auth_client: TestClient, weight: str
):
    headers = _headers(auth_client)

    response = _post(auth_client, headers, weight=weight)

    assert response.status_code == 400
    assert "权重" in response.json()["message"]
    assert _rule_count() == len(RISK_RULE_SEEDS)


def test_create_accepts_a_weight_on_the_boundary_and_a_number_written_as_text(
    auth_client: TestClient,
):
    """「权重 2.5」与「权重 "2.5"」是同一个数：两端的界都要含。"""
    headers = _headers(auth_client)

    lowest = _create(auth_client, headers, weight="0.50")
    highest = _create(auth_client, headers, weight=5.00)

    assert lowest["weight"] == 0.5
    assert highest["weight"] == 5.0


def test_create_refuses_a_blank_rule_name(auth_client: TestClient):
    headers = _headers(auth_client)

    response = _post(auth_client, headers, rule_name="   ")

    assert response.status_code == 400
    assert "规则名称" in response.json()["message"]


def test_create_refuses_a_parameter_that_is_not_part_of_the_form(auth_client: TestClient):
    """`rule_code` 由系统分配、全程只读（Q6）：带着它来一律拒，不是静默丢掉。

    静默丢掉会让专员以为自己指定了编号——返回的那串 `R0xx` 就说不清是谁给的。这一条与
    `PATCH` 对表外参数的拒绝是同一个口径。
    """
    headers = _headers(auth_client)

    response = _post(auth_client, headers, rule_code="R999")

    assert response.status_code == 400
    assert _rule_count() == len(RISK_RULE_SEEDS)
    assert _change_count() == 0


# --- 修改基本信息 ---


def test_update_changes_the_basic_information_and_leaves_the_shape_alone(
    auth_client: TestClient,
):
    headers = _headers(auth_client)
    created = _create(auth_client, headers)

    response = _patch(
        auth_client,
        headers,
        created["id"],
        rule_name="本机构客户单笔大额转入（试行）",
        category="频繁交易",
        description="口径改为试行版",
        alert_level="重度",
        weight="2.50",
        reason="口径表述跟上业务",
    )

    assert response.status_code == 200, response.text
    updated = response.json()["data"]
    assert updated["rule_name"] == "本机构客户单笔大额转入（试行）"
    assert updated["category"] == "频繁交易"
    assert updated["description"] == "口径改为试行版"
    assert updated["alert_level"] == "重度"
    assert updated["weight"] == 2.5
    for key in ("field", "operator", "threshold", "window_hours"):
        assert updated[key] == created[key], key
    assert updated["enabled"] is True
    assert updated["rule_code"] == created["rule_code"]

    row = _rule_row(created["id"])
    assert (row["field"], row["operator"], row["threshold"], row["window_hours"]) == (
        created["field"],
        created["operator"],
        created["threshold"],
        created["window_hours"],
    )


def test_update_records_the_whole_editable_configuration_not_only_the_changed_field(
    auth_client: TestClient,
):
    """只带 `rule_name` 的请求，留痕里仍是五项的整份快照。

    若按「哪些字段非空就更新哪些」的写法，这条记录里只会剩名称——「这条规则当时是什么
    样」在记录里就断了。
    """
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    before = {
        "rule_name": created["rule_name"],
        "category": created["category"],
        "description": created["description"],
        "alert_level": created["alert_level"],
        "weight": created["weight"],
    }

    response = _patch(auth_client, headers, created["id"], rule_name="改个名字", reason="名字不准")

    assert response.status_code == 200, response.text
    record = _changes(auth_client, headers, created["id"])[-1]
    assert record["change_type"] == "规则修改"
    assert set(record["old_value"]) == {
        "rule_name",
        "category",
        "description",
        "alert_level",
        "weight",
    }
    assert record["old_value"] == before
    assert record["new_value"] == {**before, "rule_name": "改个名字"}
    assert record["reason"] == "名字不准"
    assert record["changed_by_name"] == RISK_OFFICER_NAME


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("field", "amount"),
        ("operator", "gte"),
        ("window_hours", 24),
        ("threshold", {"value": "1"}),
        ("enabled", False),
    ],
)
def test_update_refuses_the_fields_that_have_their_own_entry(
    auth_client: TestClient, key: str, value: Any
):
    """判定形状、阈值与启停不接受在这个入口改——带了就 400，不是静默忽略。

    取值与现值相同也照样拒：界线画在「这个入口管不管这一列」，不在「值有没有变」。
    """
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    records_before = _changes(auth_client, headers, created["id"])

    response = _patch(auth_client, headers, created["id"], reason="想改判定形状", **{key: value})

    assert response.status_code == 400
    assert key in response.json()["message"]
    assert _changes(auth_client, headers, created["id"]) == records_before
    row = _rule_row(created["id"])
    shape = (row["field"], row["operator"], row["threshold"], row["window_hours"], row["enabled"])
    assert shape == (
        created["field"],
        created["operator"],
        created["threshold"],
        created["window_hours"],
        created["enabled"],
    )


def test_update_refuses_a_field_that_is_not_editable(auth_client: TestClient):
    """白名单之外同样拒绝：`rule_code` 全程只读，静默丢掉会让专员以为自己改掉了编号。"""
    headers = _headers(auth_client)
    created = _create(auth_client, headers)

    response = _patch(auth_client, headers, created["id"], rule_code="R999", reason="想改编号")

    assert response.status_code == 400
    assert "rule_code" in response.json()["message"]
    assert _rule_row(created["id"])["rule_code"] == created["rule_code"]


def test_update_without_any_change_is_rejected(auth_client: TestClient):
    """一条什么都没改的「修改」不该产生一条读不出内容的留痕。"""
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    records_before = _changes(auth_client, headers, created["id"])

    response = _patch(auth_client, headers, created["id"], reason="什么都没改")

    assert response.status_code == 400
    assert _changes(auth_client, headers, created["id"]) == records_before


# --- 删除 ---


def test_delete_is_a_soft_delete_that_keeps_the_row_and_its_history(auth_client: TestClient):
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    _patch(auth_client, headers, created["id"], rule_name="改个名字", reason="名字不准")
    records_before = _changes(auth_client, headers, created["id"])

    response = _delete(auth_client, headers, created["id"], reason="口径不再适用")

    assert response.status_code == 200, response.text
    assert response.json()["data"]["deleted_at"] is not None

    # 行还在：软删只写 `deleted_at`，内容一字不动。
    row = _rule_row(created["id"])
    assert row["deleted_at"] is not None
    assert row["rule_code"] == created["rule_code"]
    assert row["rule_name"] == "改个名字"

    # 列表默认过滤，`include_deleted=true` 时带着软删标记回来（过滤在服务端，ADR-0024）。
    assert created["rule_code"] not in _rule_codes(auth_client, headers)
    with_deleted = _listing(auth_client, headers, include_deleted=True)
    deleted_row = next(
        rule for rule in with_deleted["items"] if rule["rule_code"] == created["rule_code"]
    )
    assert deleted_row["deleted_at"] is not None

    # 变更记录仍可读，且恰好比删除前多一条「规则删除」——软删没有级联删掉历史。
    records_after = _changes(auth_client, headers, created["id"])
    assert records_after[: len(records_before)] == records_before
    assert len(records_after) == len(records_before) + 1
    assert records_after[-1]["change_type"] == "规则删除"
    assert records_after[-1]["reason"] == "口径不再适用"
    assert records_after[-1]["changed_by_name"] == RISK_OFFICER_NAME


def test_delete_records_the_whole_configuration_as_the_before_value(auth_client: TestClient):
    """删除是新建那条的镜像：`old_value` 装整份配置，`new_value` 为空。"""
    headers = _headers(auth_client)
    created = _create(auth_client, headers)

    _delete(auth_client, headers, created["id"], reason="口径不再适用")

    record = _changes(auth_client, headers, created["id"])[-1]
    assert record["old_value"] == {
        "rule_code": created["rule_code"],
        "rule_name": created["rule_name"],
        "category": created["category"],
        "description": created["description"],
        "field": created["field"],
        "operator": created["operator"],
        "threshold": created["threshold"],
        "window_hours": created["window_hours"],
        "alert_level": created["alert_level"],
        "weight": created["weight"],
        "enabled": True,
    }
    assert record["new_value"] == {}


def test_the_code_of_a_deleted_rule_is_not_reused(auth_client: TestClient):
    """编号永不复用（ADR-0027）：下一条取曾经的最大值 + 1，不是被删掉的那个。"""
    headers = _headers(auth_client)
    first = _create(auth_client, headers)
    _delete(auth_client, headers, first["id"], reason="口径不再适用")

    second = _create(auth_client, headers)

    assert second["rule_code"] != first["rule_code"]
    assert int(second["rule_code"][1:]) == int(first["rule_code"][1:]) + 1


def test_a_deleted_rule_refuses_every_further_write(auth_client: TestClient):
    """删除是终态：阈值、启停、改名、再删一次，一律 400 且不留痕（ADR-0027）。"""
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    rule_id = created["id"]
    _delete(auth_client, headers, rule_id, reason="口径不再适用")
    records = _changes(auth_client, headers, rule_id)

    responses = [
        _patch(auth_client, headers, rule_id, rule_name="再改一次", reason="想改"),
        _delete(auth_client, headers, rule_id, reason="再删一次"),
        auth_client.patch(
            f"{BASE_PATH}/{rule_id}/enabled",
            headers=headers,
            json={"enabled": False, "reason": "想停"},
        ),
        auth_client.patch(
            f"{BASE_PATH}/{rule_id}/threshold",
            headers=headers,
            json={"threshold": {"value": "1"}, "reason": "想调"},
        ),
    ]

    for response in responses:
        assert response.status_code == 400, response.text
        assert "已删除" in response.json()["message"]
    assert _changes(auth_client, headers, rule_id) == records
    assert _rule_row(rule_id)["enabled"] is True


# --- 理由必填：五个写动作一致 ---


@pytest.mark.parametrize("action", ["create", "update", "delete", "threshold", "enabled"])
def test_every_rule_write_requires_a_reason(auth_client: TestClient, action: str):
    """五个写动作理由为空一律 400，且一个字节都不写。

    启停也在其中：它原来是唯一一个理由可空的入口，那会让五种留痕形状里有一个不一致
    ——下一个人读到会把它当成漏写补上（spec 的 Further Notes）。
    """
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    rule_id = created["id"]
    records_before = _changes(auth_client, headers, rule_id)

    if action == "create":
        response = _post(auth_client, headers, reason="   ")
    elif action == "update":
        response = _patch(auth_client, headers, rule_id, rule_name="改个名字", reason="   ")
    elif action == "delete":
        response = _delete(auth_client, headers, rule_id, reason="   ")
    elif action == "threshold":
        response = auth_client.patch(
            f"{BASE_PATH}/{rule_id}/threshold",
            headers=headers,
            json={"threshold": {"value": "1"}, "reason": "  "},
        )
    else:
        response = auth_client.patch(
            f"{BASE_PATH}/{rule_id}/enabled",
            headers=headers,
            json={"enabled": False, "reason": ""},
        )

    assert response.status_code == 400, response.text
    assert "理由" in response.json()["message"]
    assert _changes(auth_client, headers, rule_id) == records_before
    # 创建被拒的话库里也不该多出一行——被拒的请求在任何写入之前就返回了。
    assert _rule_count() == len(RISK_RULE_SEEDS) + 1


# --- 门控 ---


def test_only_risk_officers_can_create_update_or_delete(auth_client: TestClient):
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    advisor = _headers(auth_client, ADVISOR_USERNAME)

    assert _post(auth_client, advisor).status_code == 403
    assert _patch(auth_client, advisor, created["id"], rule_name="改", reason="想改").status_code == (
        403
    )
    assert _delete(auth_client, advisor, created["id"], reason="想删").status_code == 403

    # 读得到、改不了：列表对内部员工开放。
    assert auth_client.get(BASE_PATH, headers=advisor).status_code == 200
    assert _rule_row(created["id"])["deleted_at"] is None
    assert _rule_row(created["id"])["rule_name"] == created["rule_name"]


def test_the_three_write_endpoints_reject_unauthenticated_calls(auth_client: TestClient):
    assert auth_client.post(BASE_PATH, json=CREATE_BODY).status_code == 401
    renamed = auth_client.patch(f"{BASE_PATH}/1", json={"rule_name": "改", "reason": "想改"})
    deleted = auth_client.request("DELETE", f"{BASE_PATH}/1", json={"reason": "想删"})
    assert renamed.status_code == 401
    assert deleted.status_code == 401


def test_unknown_rule_cannot_be_updated_or_deleted(auth_client: TestClient):
    headers = _headers(auth_client)

    missing = _patch(auth_client, headers, 999999, rule_name="改", reason="想改")
    also_missing = _delete(auth_client, headers, 999999, reason="想删")

    assert missing.status_code == 404
    assert also_missing.status_code == 404


# --- 删除之后，历史预警仍是命中那一刻的事实 ---


def test_deleting_a_rule_does_not_disturb_the_alerts_it_already_hit(auth_client: TestClient):
    """预警是事实记录：规则删掉之后，它的命中依据一字不变。

    命中依据是命中那一刻固化到 `fin_risk_alert.rule_hits` / `rule_codes` 的快照，详情
    不去回查规则表——所以「删了规则，昨天的预警还解释得清」不是靠约定，是靠这份快照。
    """
    headers = _headers(auth_client)
    alert = _submit_alert(auth_client, headers, amount=LIGHT_AMOUNT)
    rule_id = _rule_id(auth_client, "R001", headers)
    before = _alert_detail(auth_client, headers, alert["id"])

    _delete(auth_client, headers, rule_id, reason="口径不再适用")

    after = _alert_detail(auth_client, headers, alert["id"])
    assert after["rule_codes"] == before["rule_codes"] == ["R001"]
    assert after["rule_hits"] == before["rule_hits"]
    assert after["alert_level"] == before["alert_level"]
    assert [hit["field_label"] for hit in after["rule_hits"]] == ["交易金额"]

    # 已删规则的变更记录照常读得到（列表里默认看不到它）。
    assert [record["change_type"] for record in _changes(auth_client, headers, rule_id)][-1] == (
        "规则删除"
    )
