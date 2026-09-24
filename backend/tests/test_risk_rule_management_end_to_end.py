"""规则编辑器到预警的端到端：新建的规则只对**下一笔**交易生效。

Seam 与 `test_end_to_end_customer_journey.py` 同一个口径——后端 HTTP 层，不引入浏览器，
也不打桩规则引擎：登录 → 写规则 → 补录交易 → 预警，全程真实链路（规则落
`fin_risk_rule`、交易落 `fin_transaction`、命中依据固化到 `fin_risk_alert`）。界面那一
半（已删行置灰只读、判定口径只读、删除理由为空发不出去）由 `RiskRulesTab.vue` 的组件
测试守着，这里钉住的是它背后的 API。

三件事在这里收口：

1. **新规则只判定下一笔交易**（Q18 的不回算）：建一条「单笔金额 ≥ 1」这种对库里每一笔
   都成立的规则之后，**已有交易一条都不产生新预警**；下一笔补录进来则当场命中，且命中
   依据落到字段与值。
2. **一次写操作一条留痕**：新建 → 改名 → 调阈值 → 停用 → 删除，五条记录按时间顺序可
   读，每条都有理由与操作人姓名。
3. **删除是软删**：默认列表看不到，`include_deleted=true` 看得到（行上带软删标记，界面
   据此置灰只读），而它的变更记录仍然打得开。

测试库跨运行持久，所以本文件造出来的规则、交易与预警在用例前后各清一次（`_purge_test_artifacts`）。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import (
    Customer,
    Product,
    RiskAlert,
    RiskFocus,
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
RISK_OFFICER_NAME = "周风控"

BASE_PATH = "/api/internal/risk-rules"
SUBMIT_PATH = "/api/internal/transaction-events"
ALERTS_PATH = "/api/internal/risk-alerts"

# 一位带历史交易与历史预警的种子客户：端到端要的就是「库里本来就有交易」这个前提。
CUSTOMER_USERNAME = "wangc1"
PRODUCT_CODE = "F000001"
EXISTING_AMOUNT = "50000.00"

# 测试库跨运行持久：种子里那五笔历史成交落在 2018–2022 年，本条用例造出来的一切
# （交易、预警、风险关注）都晚于这个下界。
TEST_EPOCH = datetime(2026, 1, 1)
TRADE_AT = datetime(2026, 9, 10, 11, 0, 0)

SEED_CODES = frozenset(spec.rule_code for spec in RISK_RULE_SEEDS)

# 一条必然命中的规则：金额 ≥ 1 对库里每一笔交易都成立。它配在这里是有意的——
# 若哪天有人把回算顺手做进来，第一条用例里的「预警总数不变」会第一个炸。
CREATE_BODY: dict[str, Any] = {
    "rule_name": "演示：单笔金额不低于一元",
    "category": "大额交易",
    "description": "",
    "field": "amount",
    "operator": "gte",
    "threshold": {"value": "1"},
    "alert_level": "轻度",
    "reason": "本地口径：一元门槛只为了让演示当天一定命中",
}


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
    """把库恢复成「只有种子规则、没有本文件造出来的交易与预警」的样子。

    测试库跨运行持久：一条多出来的 `R021` 会让下一次的编号分配对不上，一行留下的预警会
    让「已有交易不产生新预警」在第二次运行时失真。因此每条用例前后各清一次。

    交易与预警只清**这位测试客户**名下、晚于下界的那批——本文件的断言读的是这一位的
    预警，别的文件留下的行删掉它们只会扩大误伤面（`test_risk_rule_lifecycle_api` 的
    清理是全库的，这里刻意更窄）。

    删规则先删它的变更记录（子表指着它），删预警先删从它派生的工单
    （`biz_work_order.source_alert_id` 指着预警）。标识一律先取进 Python 再删：MySQL 不
    允许在 DELETE 的子查询里再读同一张表（错误 1093）。
    """
    with _session() as session:
        customer_id = (
            select(Customer.id).where(Customer.username == CUSTOMER_USERNAME).scalar_subquery()
        )
        extra_ids = [
            rule.id
            for rule in session.scalars(select(RiskRule))
            if rule.rule_code not in SEED_CODES
        ]
        if extra_ids:
            session.execute(delete(RiskRuleChange).where(RiskRuleChange.rule_id.in_(extra_ids)))
            session.execute(delete(RiskRule).where(RiskRule.id.in_(extra_ids)))

        alert_ids = list(
            session.scalars(
                select(RiskAlert.id).where(
                    RiskAlert.customer_id == customer_id,
                    RiskAlert.create_time >= TEST_EPOCH,
                )
            )
        )
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
        # 补录会经事件总线留下一条风险关注；种子回放的那几条落在下界之前。
        session.execute(
            delete(RiskFocus).where(
                RiskFocus.customer_id == customer_id,
                RiskFocus.occurred_at >= TEST_EPOCH,
            )
        )
        session.execute(
            delete(Transaction).where(
                Transaction.customer_id == customer_id,
                Transaction.create_time >= TEST_EPOCH,
            )
        )
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


def _customer_and_product() -> tuple[int, int]:
    with _session() as session:
        customer_id = session.scalar(
            select(Customer.id).where(Customer.username == CUSTOMER_USERNAME)
        )
        product_id = session.scalar(select(Product.id).where(Product.product_code == PRODUCT_CODE))
    assert customer_id is not None and product_id is not None
    return int(customer_id), int(product_id)


def _alerts_of(client: TestClient, headers: dict[str, str], customer_id: int) -> list[dict]:
    response = client.get(
        ALERTS_PATH, headers=headers, params={"customer_id": customer_id, "page_size": 100}
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["items"]


def _alert_detail(client: TestClient, headers: dict[str, str], alert_id: int) -> dict:
    response = client.get(f"{ALERTS_PATH}/{alert_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    customer_id: int,
    product_id: int,
    amount: str,
    occurred_at: datetime,
) -> dict:
    """走真实入海口补录一笔交易：落库 → 过规则引擎 → 命中就产生预警。"""
    response = client.post(
        SUBMIT_PATH,
        headers=headers,
        json={
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": "申购",
            "amount": amount,
            "occurred_at": occurred_at.isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _hit_of(alert: dict, rule_code: str) -> dict:
    """这条预警里由 `rule_code` 贡献的那一份命中依据。"""
    return next(hit for hit in alert["rule_hits"] if hit["rule_code"] == rule_code)


def _alert_count() -> int:
    with _session() as session:
        return session.scalar(select(func.count()).select_from(RiskAlert)) or 0


def _create(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict:
    response = client.post(BASE_PATH, headers=headers, json={**CREATE_BODY, **overrides})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _patch(client: TestClient, headers: dict[str, str], rule_id: int, **body: Any) -> dict:
    response = client.patch(f"{BASE_PATH}/{rule_id}", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _adjust_threshold(
    client: TestClient, headers: dict[str, str], rule_id: int, threshold: dict, reason: str
) -> dict:
    response = client.patch(
        f"{BASE_PATH}/{rule_id}/threshold",
        headers=headers,
        json={"threshold": threshold, "reason": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _set_enabled(
    client: TestClient, headers: dict[str, str], rule_id: int, *, enabled: bool, reason: str
) -> dict:
    response = client.patch(
        f"{BASE_PATH}/{rule_id}/enabled",
        headers=headers,
        json={"enabled": enabled, "reason": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


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


def test_a_new_rule_judges_the_next_transaction_only(auth_client: TestClient):
    """新建 → 已有交易不产生新预警 → 下一笔补录当场命中，依据落到字段与值。

    「已有交易」是库里的既成事实：种子里那五笔历史成交，加上本用例先补录的这一笔。
    不回算的意思正是它们一笔都不重新判定（Q18）——预警是命中那一刻的事实记录，回放会
    同时撞上幂等、分级顺序与广播三处。
    """
    headers = _headers(auth_client)
    customer_id, product_id = _customer_and_product()

    existing = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount=EXISTING_AMOUNT,
        occurred_at=TRADE_AT,
    )
    assert existing["alerts"], "这笔补录本该命中种子里的规则"
    alerts_before = _alert_count()

    created = _create(auth_client, headers)
    rule_code = created["rule_code"]
    assert created["enabled"] is True
    # 描述留空按判定形状自动生成，因此这条规则在列表上也是可读的。
    assert created["description"] == "交易金额 ≥ 阈值 1"

    # 不回算：新建规则不重新判定任何一笔已经落库的交易。
    assert _alert_count() == alerts_before

    later = _submit(
        auth_client,
        headers,
        customer_id=customer_id,
        product_id=product_id,
        amount=EXISTING_AMOUNT,
        occurred_at=TRADE_AT.replace(hour=15),
    )
    triggered = next(
        alert for alert in later["alerts"] if rule_code in alert["rule_codes"]
    )
    alert_id = triggered["id"]

    # 预警列表里出现由该规则触发的这一条（列表行带 rule_codes，编号是它的外部标识）。
    listed = next(
        row for row in _alerts_of(auth_client, headers, customer_id) if row["id"] == alert_id
    )
    assert rule_code in listed["rule_codes"]

    # 命中依据落到字段与值：详情里的一行能读出「拿哪个字段、什么实测值、比什么阈值」。
    hit = _hit_of(_alert_detail(auth_client, headers, alert_id), rule_code)
    assert hit["field"] == "amount"
    assert hit["field_label"] == "交易金额"
    assert hit["operator"] == "gte"
    assert hit["operator_symbol"] == "≥"
    assert hit["threshold"] == "1"
    assert hit["observed_value"] == "50000"
    assert hit["evidence"] == "交易金额 50000 ≥ 阈值 1"


def test_five_writes_leave_five_changes_in_chronological_order(auth_client: TestClient):
    """新建 → 改名 → 调阈值 → 停用 → 删除：五条留痕按时间顺序可读，条条有署名。

    五个写入口各留一条记录，形状一致（`old_value` / `new_value` 装快照、理由必填、
    `changed_by` 记人）。「这条规则当时是什么样」因此不必去翻别处。
    """
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    rule_id = created["id"]

    _patch(auth_client, headers, rule_id, rule_name="演示：改名后的规则", reason="口径表述跟上业务")
    _adjust_threshold(
        auth_client, headers, rule_id, {"value": "10"}, reason="一元的门槛太松，收到十元"
    )
    _set_enabled(auth_client, headers, rule_id, enabled=False, reason="误报过多，先停掉")
    deleted = _delete(auth_client, headers, rule_id, reason="口径不再适用")
    assert deleted.status_code == 200, deleted.text

    changes = _changes(auth_client, headers, rule_id)
    assert [change["change_type"] for change in changes] == [
        "规则新建",
        "规则修改",
        "阈值调整",
        "启停变更",
        "规则删除",
    ]

    # 时间顺序：留痕按写入次序追加，时间戳允许同秒（写入口之间没有 sleep）。
    timestamps = [datetime.fromisoformat(change["changed_at"]) for change in changes]
    assert timestamps == sorted(timestamps)
    assert all(change["reason"] for change in changes)
    assert {change["changed_by_name"] for change in changes} == {RISK_OFFICER_NAME}
    assert all(change["rule_code"] == created["rule_code"] for change in changes)

    written, renamed, threshold_change, enabled_change, removed = changes
    # 新建与删除是彼此的镜像：无 → 有、有 → 无，各装整份配置。
    assert written["old_value"] == {}
    assert written["new_value"]["rule_code"] == created["rule_code"]
    assert removed["old_value"]["rule_name"] == "演示：改名后的规则"
    assert removed["new_value"] == {}
    # 修改装的是整份可编辑配置的前后两份快照，不是只装改过的那一列。
    assert set(renamed["old_value"]) == {
        "rule_name",
        "category",
        "description",
        "alert_level",
        "weight",
    }
    assert renamed["old_value"]["rule_name"] == CREATE_BODY["rule_name"]
    assert renamed["new_value"]["rule_name"] == "演示：改名后的规则"
    # 阈值与启停各有专门入口，留痕就装那一列的前后两份取值。
    assert threshold_change["old_value"] == {"threshold": {"value": "1"}}
    assert threshold_change["new_value"] == {"threshold": {"value": "10"}}
    assert enabled_change["old_value"] == {"enabled": True}
    assert enabled_change["new_value"] == {"enabled": False}


def test_a_deleted_rule_leaves_the_listing_but_keeps_its_changes_readable(
    auth_client: TestClient,
):
    """删除是软删的一半在服务端：默认看不到、`include_deleted` 看得到、留痕还打得开。

    另一半在界面上（置灰只读、只留「查看变更记录」），由 `RiskRulesTab.vue` 的组件测试
    守着。行留在库里是历史预警能继续解析规则名、留痕表的外键不作废的前提（ADR-0027）。
    """
    headers = _headers(auth_client)
    created = _create(auth_client, headers)
    rule_id = created["id"]
    rule_code = created["rule_code"]

    default_codes = {rule["rule_code"] for rule in _listing(auth_client, headers)["items"]}
    assert rule_code in default_codes

    assert _delete(auth_client, headers, rule_id, reason="口径不再适用").status_code == 200

    default_page = _listing(auth_client, headers)
    assert rule_code not in {rule["rule_code"] for rule in default_page["items"]}
    assert all(rule["deleted_at"] is None for rule in default_page["items"])

    with_deleted = _listing(auth_client, headers, include_deleted=True)
    row = next(rule for rule in with_deleted["items"] if rule["rule_code"] == rule_code)
    assert row["deleted_at"] is not None
    assert with_deleted["total"] == default_page["total"] + 1

    # 已删除的规则照样打得开它的变更记录：删除本身也留痕、也可查。
    changes = _changes(auth_client, headers, rule_id)
    assert [change["change_type"] for change in changes] == ["规则新建", "规则删除"]
