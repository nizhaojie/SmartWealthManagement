"""规则接口：列表、启停、阈值调整与留痕。

规则改的是判定结论的口径，所以写操作只放开给风控专员，且每次变更都要有理由。
这几条断言覆盖了「阈值可调整且调整有记录」与「停用后不再参与匹配」——后者是纯
函数测试之外的一层：确认库里那条 `enabled` 真的被读进去了。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import RiskRule, RiskRuleChange
from app.risk_monitoring import service
from app.risk_monitoring.context import CustomerSnapshot, MonitoringContext, TransactionEvent
from app.risk_monitoring.rules import RISK_RULE_SEEDS
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"

BASE_TIME = datetime(2026, 9, 10, 10, 0, 0)


def _engine():
    return create_engine(get_settings().test_database_url)


def _reset_rules(engine) -> None:
    """把阈值与启停恢复成种子值，并清掉调整记录。

    阈值的变更是跨用例的副作用，一个用例调过的阈值会让另一个用例的断言失去意义。
    """
    with OrmSession(engine) as session:
        session.execute(delete(RiskRuleChange))
        by_code = {rule.rule_code: rule for rule in session.scalars(select(RiskRule)).all()}
        for spec in RISK_RULE_SEEDS:
            rule = by_code.get(spec.rule_code)
            if rule is None:
                continue
            rule.threshold = dict(spec.threshold)
            rule.enabled = spec.enabled
        session.commit()


@pytest.fixture(autouse=True)
def _restore_rules(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    _reset_rules(engine)
    try:
        yield
    finally:
        _reset_rules(engine)
        engine.dispose()


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _rule_id(client: TestClient, rule_code: str, headers: dict[str, str]) -> int:
    rules = client.get("/api/internal/risk-rules", headers=headers).json()["data"]
    return next(rule["id"] for rule in rules if rule["rule_code"] == rule_code)


def _context(amount: str) -> MonitoringContext:
    return MonitoringContext(
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


def _matched_rule_codes(amount: str) -> set[str]:
    engine = _engine()
    try:
        with OrmSession(engine) as session:
            return {
                hit.rule_code for hit in service.match_enabled_rules(session, _context(amount))
            }
    finally:
        engine.dispose()


def test_rule_list_returns_the_twenty_rules_with_their_configuration(
    auth_client: TestClient,
):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    response = auth_client.get("/api/internal/risk-rules", headers=headers)

    assert response.status_code == 200
    rules = response.json()["data"]
    assert len(rules) == 20

    first = rules[0]
    for key in (
        "id",
        "rule_code",
        "rule_name",
        "category",
        "description",
        "field",
        "operator",
        "threshold",
        "threshold_text",
        "window_hours",
        "alert_level",
        "weight",
        "enabled",
    ):
        assert key in first, key

    assert all(rule["enabled"] is True for rule in rules)
    assert {rule["alert_level"] for rule in rules} <= {"轻度", "中度", "重度"}
    assert all(rule["weight"] > 0 for rule in rules)


def test_disabled_rule_no_longer_participates_in_matching(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    assert _matched_rule_codes("60000.00") == {"R001"}

    disabled = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/enabled",
        headers=headers,
        json={"enabled": False, "reason": "误报过多，暂停观察"},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["enabled"] is False

    assert _matched_rule_codes("60000.00") == set()

    re_enabled = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/enabled",
        headers=headers,
        json={"enabled": True, "reason": "误报已定位，恢复启用"},
    )
    assert re_enabled.json()["data"]["enabled"] is True
    assert _matched_rule_codes("60000.00") == {"R001"}


def test_threshold_adjustment_changes_the_matching_result(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    adjusted = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=headers,
        json={"threshold": {"value": "100000"}, "reason": "监管口径上调"},
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["data"]["threshold"] == {"value": "100000"}

    assert _matched_rule_codes("60000.00") == set()
    assert _matched_rule_codes("150000.00") == {"R001"}


def test_threshold_adjustment_is_recorded_with_old_and_new_values(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=headers,
        json={"threshold": {"value": "80000"}, "reason": "监管口径上调"},
    )

    changes = auth_client.get(f"/api/internal/risk-rules/{rule_id}/changes", headers=headers)
    assert changes.status_code == 200
    records = changes.json()["data"]
    assert len(records) == 1

    record = records[0]
    assert record["change_type"] == "阈值调整"
    assert record["old_value"] == {"threshold": {"value": "50000"}}
    assert record["new_value"] == {"threshold": {"value": "80000"}}
    assert record["changed_by_name"] == "周风控"
    assert record["reason"] == "监管口径上调"
    assert record["changed_at"]


def test_threshold_adjustment_without_a_reason_is_rejected(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    response = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=headers,
        json={"threshold": {"value": "80000"}, "reason": "   "},
    )

    assert response.status_code == 400
    assert "理由" in response.json()["message"]
    assert auth_client.get(
        f"/api/internal/risk-rules/{rule_id}/changes", headers=headers
    ).json()["data"] == []


def test_threshold_that_does_not_fit_the_operator_is_rejected(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    response = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=headers,
        json={"threshold": {"min": "1", "max": "2"}, "reason": "试试区间"},
    )

    assert response.status_code == 400
    assert "算子" in response.json()["message"]


def test_threshold_that_is_not_a_number_is_rejected(auth_client: TestClient):
    """非数值阈值挡在写入侧。

    放它进库，下一次匹配就会在比较时抛异常，整笔交易的判定跟着失败。
    """
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    response = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=headers,
        json={"threshold": {"value": "五十万"}, "reason": "手写错字"},
    )

    assert response.status_code == 400
    assert auth_client.get(
        f"/api/internal/risk-rules/{rule_id}/changes", headers=headers
    ).json()["data"] == []
    assert _matched_rule_codes("60000.00") == {"R001"}


def test_enabling_change_is_recorded_without_requiring_a_reason(auth_client: TestClient):
    """启停留痕不强制理由——spec 只对阈值调整要求「调整有记录」。"""
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    rule_id = _rule_id(auth_client, "R001", headers)

    response = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/enabled",
        headers=headers,
        json={"enabled": False},
    )
    assert response.status_code == 200

    records = auth_client.get(f"/api/internal/risk-rules/{rule_id}/changes", headers=headers).json()[
        "data"
    ]
    assert len(records) == 1
    assert records[0]["change_type"] == "启停变更"
    assert records[0]["old_value"] == {"enabled": True}
    assert records[0]["new_value"] == {"enabled": False}
    assert records[0]["changed_by_name"] == "周风控"


def test_only_risk_officers_can_change_rules(auth_client: TestClient):
    risk_headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    advisor_headers = _headers(auth_client, ADVISOR_USERNAME)
    rule_id = _rule_id(auth_client, "R001", risk_headers)

    forbidden = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/enabled",
        headers=advisor_headers,
        json={"enabled": False, "reason": "我觉得可以停"},
    )
    assert forbidden.status_code == 403

    also_forbidden = auth_client.patch(
        f"/api/internal/risk-rules/{rule_id}/threshold",
        headers=advisor_headers,
        json={"threshold": {"value": "1"}, "reason": "我觉得可以调"},
    )
    assert also_forbidden.status_code == 403

    listing = auth_client.get("/api/internal/risk-rules", headers=advisor_headers)
    assert listing.status_code == 200


def test_rule_endpoints_reject_unauthenticated_calls(auth_client: TestClient):
    assert auth_client.get("/api/internal/risk-rules").status_code == 401
    assert (
        auth_client.patch(
            "/api/internal/risk-rules/1/enabled", json={"enabled": False, "reason": "x"}
        ).status_code
        == 401
    )


def test_unknown_rule_is_reported_as_missing(auth_client: TestClient):
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    response = auth_client.get("/api/internal/risk-rules/999999/changes", headers=headers)
    assert response.status_code == 404
