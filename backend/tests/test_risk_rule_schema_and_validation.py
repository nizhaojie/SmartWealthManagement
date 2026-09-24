"""字段 × 算子允许矩阵、阈值值域，以及把两者下发给前端的 `GET /schema`。

规则可以创建之后，`fin_risk_rule` 的每一列都有 CHECK 守着，两列的**搭配**却没有：`field =
product_id` 配 `operator = gt` 两列各自合法，库里收下，而它是一条没有任何含义的规则——
拿产品标识比数值，既不是监管口径，也永远筛不出该筛的东西；阈值落在物理值域之外的规则
同样安静——它永远不会命中。两种都不会报错，只会在库里躺着。三档校验（名录 → 搭配 →
值域）挡的就是这两种规则（ADR-0026），这份文件断言它真的挡得住，且**挡在写入之前**。

schema 端点与校验必须读同一份注册表：前端禁掉的选项与后端拒掉的组合一旦漂移，表现是
「下拉里能选、一提交被拒」——不会有断言失败，只会有人反复试。所以下面的断言是双向的：
schema 列出的每个组合后端都收，没列出的每个组合后端都拒。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import RiskRule
from app.exceptions import AppError
from app.risk_monitoring import validation
from app.risk_monitoring.fields import FIELD_KEYS, FIELD_REGISTRY, ValueRange
from app.risk_monitoring.operators import (
    DAILY_SUM_GTE,
    GT,
    OPERATOR_KEYS,
    OPERATOR_REGISTRY,
    WINDOW_DISTINCT_COUNT_GTE,
    WINDOW_SUM_GTE,
)
from app.risk_monitoring.rules import RISK_RULE_SEEDS, RULE_CATEGORIES
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER_USERNAME = "risk1"
ADVISOR_USERNAME = "advisor1"

# 字段 × 值域的两侧：刚好合法的那一批与刚好越界的那一批。边界值必须写出来——「≥ 0 且
# ≤ 23」到底含不含端点，只有这两张表能回答。
IN_RANGE_THRESHOLDS = [
    ("amount", "gte", {"value": "1"}),
    ("purchase_amount", "between", {"min": "1000", "max": "50000"}),
    ("redeem_amount", "gt", {"value": "0.01"}),
    ("hour_of_day", "gte", {"value": "0"}),
    ("hour_of_day", "lte", {"value": "23"}),
    ("hour_of_day", "outside", {"min": "0", "max": "23"}),
    ("amount_to_assets_ratio", "gte", {"value": "0.0001"}),
    ("risk_level_gap", "gte", {"value": "-4"}),
    ("risk_level_gap", "lte", {"value": "4"}),
    ("reverse_interval_hours", "lte", {"value": "0.5"}),
    ("threshold_avoidance_amount", "gte", {"value": "45000"}),
    ("small_amount", "lte", {"value": "10000"}),
    ("large_round_amount", "gte", {"value": "100000"}),
]

OUT_OF_RANGE_THRESHOLDS = [
    # 「时」不是「点」：30 点在库里不存在，这条规则永远不会命中。
    ("hour_of_day", "gte", {"value": "30"}),
    ("hour_of_day", "lt", {"value": "-1"}),
    ("hour_of_day", "between", {"min": "0", "max": "30"}),
    ("hour_of_day", "outside", {"min": "-1", "max": "23"}),
    ("risk_level_gap", "gte", {"value": "5"}),
    ("risk_level_gap", "lte", {"value": "-5"}),
    # 比例与间隔都是正的：0 是开区间的下界，「比例 > -1%」「间隔 < 0 小时」都不成立。
    ("amount_to_assets_ratio", "gte", {"value": "0"}),
    ("amount_to_assets_ratio", "lt", {"value": "-1"}),
    ("reverse_interval_hours", "lte", {"value": "0"}),
    ("amount", "gte", {"value": "0"}),
    ("amount", "lt", {"value": "-50000"}),
    ("redeem_amount", "gte", {"value": "0"}),
    ("threshold_avoidance_amount", "gt", {"value": "-1"}),
    ("small_amount", "lte", {"value": "0"}),
    ("large_round_amount", "gte", {"value": "0"}),
]

# 求和类聚合对哪些字段没有意义：取值语义是小时、百分比或等级差。
NON_ADDITIVE_FIELDS = (
    "hour_of_day",
    "amount_to_assets_ratio",
    "risk_level_gap",
    "reverse_interval_hours",
)


def _headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _rule_count() -> int:
    engine = create_engine(get_settings().test_database_url)
    try:
        with OrmSession(engine) as session:
            return session.scalar(select(func.count()).select_from(RiskRule)) or 0
    finally:
        engine.dispose()


def _threshold_for(operator_key: str, value_range: dict[str, Any] | None) -> dict[str, str]:
    """按算子要求的键造一份落在值域里的阈值——「前端能选、后端必须收」的那份输入。"""
    lower = Decimal("1")
    if value_range is not None and value_range["min"] is not None:
        lower = Decimal(value_range["min"]) + (0 if value_range["min_inclusive"] else 1)
    keys = OPERATOR_REGISTRY[operator_key].threshold_keys
    return {key: str(lower + offset) for offset, key in enumerate(keys)}


def _range(lower: str | None, upper: str | None, *, lower_inclusive: bool = True) -> ValueRange:
    """一份值域声明，用来与注册表里的那一份逐字段比。"""
    return ValueRange(
        lower=Decimal(lower) if lower is not None else None,
        upper=Decimal(upper) if upper is not None else None,
        lower_inclusive=lower_inclusive,
    )


def _shape(**overrides: Any) -> validation.RuleShape:
    """一份合法的判定形状，按需覆盖其中几项——用来把某一档单独搞错。"""
    arguments: dict[str, Any] = {
        "category": RULE_CATEGORIES[0],
        "field": "amount",
        "operator": "gte",
        "alert_level": "轻度",
        "threshold": {"value": "50000"},
    }
    arguments.update(overrides)
    return validation.validate_rule_definition(**arguments)


def test_every_seeded_rule_passes_the_write_validation():
    """20 条种子规则必须过得了写入侧校验。

    过不了就说明矩阵或值域与规则引擎自己的口径冲突了——那会是「专员能改的 20 条，他自己
    一条也配不出来」这种荒谬状态，而不是某个边角组合的问题。
    """
    for spec in RISK_RULE_SEEDS:
        shape = validation.validate_rule_definition(
            category=spec.category,
            field=spec.field,
            operator=spec.operator,
            alert_level=spec.alert_level,
            threshold=spec.threshold,
            window_hours=spec.window_hours,
        )
        assert shape.field == spec.field, spec.rule_code
        assert shape.window_hours == spec.window_hours, spec.rule_code


def test_every_field_declares_operators_that_exist():
    """矩阵的每一行都要有值，且只能列注册表里有的算子（拼错在导入时就该炸）。"""
    assert set(FIELD_REGISTRY) == set(FIELD_KEYS)
    for key, spec in FIELD_REGISTRY.items():
        assert spec.allowed_operators, key
        assert set(spec.allowed_operators) <= set(OPERATOR_KEYS), key


def test_a_field_whose_value_is_an_identifier_only_combines_with_distinct_count():
    """`product_id` 的取值是产品标识（代理键），不是一个可以比大小或求和的量。

    拿它比数值不会抛错——它是个整数，`to_comparable` 会把它转成 `Decimal` 正常比完——但
    比出来的东西没有任何含义：「产品 5 号比 3 号大」既不是监管口径，也筛不出该筛的东西。
    因此这里只留下去重计数（窗内涉及几种产品，是拆分规避的真实口径）；计数类的语义与
    字段无关，那等于在数交易笔数，该写在 `amount` 上。
    """
    assert FIELD_REGISTRY["product_id"].allowed_operators == (WINDOW_DISTINCT_COUNT_GTE,)

    with pytest.raises(AppError) as excinfo:
        validation.validate_rule_shape(
            field="product_id", operator=GT, threshold={"value": "1"}
        )

    assert excinfo.value.code == 400
    assert "搭配" in excinfo.value.message
    assert "product_id" in excinfo.value.message
    assert GT in excinfo.value.message


def test_the_rejected_combination_never_reaches_the_database(auth_client: TestClient):
    """被拒的组合一行都落不下。

    校验入口在任何写入之前（#03 的 `POST` 先走它、通过了才 `db.add`），所以「库里不落行」
    在这里就是「规则表一行没多」。
    """
    before = _rule_count()

    with pytest.raises(AppError):
        validation.validate_rule_shape(field="product_id", operator=GT, threshold={"value": "1"})

    assert _rule_count() == before


@pytest.mark.parametrize("field_key", NON_ADDITIVE_FIELDS)
@pytest.mark.parametrize("operator_key", (WINDOW_SUM_GTE, DAILY_SUM_GTE))
def test_sum_aggregates_are_refused_where_adding_the_values_up_means_nothing(
    field_key: str, operator_key: str
):
    """小时、百分比、等级差不允许求和。

    「窗内时刻合计 ≥ 30」这种规则配出来不会有任何含义：它要么永远不命中，要么命中得
    莫名其妙，而库里看不出是哪一种。
    """
    with pytest.raises(AppError) as excinfo:
        validation.validate_rule_shape(
            field=field_key, operator=operator_key, threshold={"value": "1"}
        )

    assert "搭配" in excinfo.value.message
    assert field_key in excinfo.value.message


def test_money_fields_still_take_sum_aggregates():
    """排除的只是非加性字段：金额的合计是拆分规避的主口径，必须留着。"""
    assert (
        validation.validate_rule_shape(
            field="amount", operator=WINDOW_SUM_GTE, threshold={"value": "500000"}
        )
        == {"value": Decimal("500000")}
    )


@pytest.mark.parametrize(("field_key", "operator_key", "threshold"), IN_RANGE_THRESHOLDS)
def test_thresholds_inside_the_declared_value_range_are_accepted(
    field_key: str, operator_key: str, threshold: dict[str, str]
):
    assert validation.validate_rule_shape(
        field=field_key, operator=operator_key, threshold=threshold
    )


@pytest.mark.parametrize(("field_key", "operator_key", "threshold"), OUT_OF_RANGE_THRESHOLDS)
def test_thresholds_outside_the_declared_value_range_are_rejected(
    field_key: str, operator_key: str, threshold: dict[str, str]
):
    with pytest.raises(AppError) as excinfo:
        validation.validate_rule_shape(
            field=field_key, operator=operator_key, threshold=threshold
        )

    assert excinfo.value.code == 400
    assert "值域" in excinfo.value.message
    assert field_key in excinfo.value.message


def test_the_declared_value_ranges_are_the_physical_ones():
    """值域声明本身：四条来自取值语义的边界，加金额类的「> 0」。"""
    assert FIELD_REGISTRY["hour_of_day"].value_range == _range("0", "23")
    assert FIELD_REGISTRY["risk_level_gap"].value_range == _range("-4", "4")
    for field_key in ("amount_to_assets_ratio", "reverse_interval_hours"):
        assert FIELD_REGISTRY[field_key].value_range == _range("0", None, lower_inclusive=False)

    money_fields = (
        "amount",
        "purchase_amount",
        "redeem_amount",
        "threshold_avoidance_amount",
        "small_amount",
        "large_round_amount",
    )
    for field_key in money_fields:
        assert FIELD_REGISTRY[field_key].value_range == _range("0", None, lower_inclusive=False)


def test_the_three_tiers_run_in_order_and_say_which_one_failed():
    """名录 → 搭配 → 值域：谁先失败就报谁，而且报得出是哪一档、哪个字段。

    同一条请求里三档都错时，专员要先看到最早那一档——否则他改完值域提交，才发现分类
    本来就是错的。
    """
    with pytest.raises(AppError) as registry_error:
        _shape(category="随便", field="product_id", operator=GT, threshold={"value": "1"})
    assert "名录" in registry_error.value.message
    assert "规则分类" in registry_error.value.message

    with pytest.raises(AppError) as pair_error:
        _shape(field="product_id", operator=GT, threshold={"value": "1"})
    assert "搭配" in pair_error.value.message

    with pytest.raises(AppError) as range_error:
        _shape(field="hour_of_day", threshold={"value": "30"})
    assert "值域" in range_error.value.message


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"category": "随便"}, ("名录", "规则分类", "随便")),
        ({"field": "不存在的字段"}, ("名录", "规则字段", "不存在的字段")),
        ({"operator": "不存在的算子"}, ("名录", "规则算子", "不存在的算子")),
        ({"alert_level": "特重"}, ("名录", "预警等级", "特重")),
    ],
)
def test_each_registry_column_is_checked_by_its_own_name(
    overrides: dict[str, Any], expected: tuple[str, str, str]
):
    """名录这一档四列各报各的：一句「参数不合法」说不出该改哪一列。"""
    with pytest.raises(AppError) as excinfo:
        _shape(**overrides)

    assert excinfo.value.code == 400
    for fragment in expected:
        assert fragment in excinfo.value.message


def test_the_threshold_shape_comes_from_the_evaluation_side():
    """形状仍由 `normalize_threshold` 说了算，但消息里带上算子与缺失的键。

    本 slice 新增的第二、三档之前，这里只有一句「阈值与算子不匹配」——专员知道错了，
    但不知道该改哪个键。
    """
    shape = _shape(field="amount", operator="between", threshold={"min": "1000", "max": "5000"})
    assert shape.threshold == {"min": Decimal("1000"), "max": Decimal("5000")}

    with pytest.raises(AppError) as missing_key:
        _shape(field="amount", operator="gte", threshold={"min": "1", "max": "2"})
    assert "阈值形状校验未通过" in missing_key.value.message
    assert "gte" in missing_key.value.message
    assert "value" in missing_key.value.message

    with pytest.raises(AppError) as not_a_number:
        _shape(field="amount", threshold={"value": "五十万"})
    assert "阈值形状校验未通过" in not_a_number.value.message

    with pytest.raises(AppError) as reversed_range:
        _shape(field="amount", operator="between", threshold={"min": "5000", "max": "1000"})
    assert "下界大于上界" in reversed_range.value.message


@pytest.mark.parametrize("window_hours", [None, 0, -1, 2.5, True])
def test_a_window_operator_needs_a_positive_whole_hour_window(window_hours: Any):
    with pytest.raises(AppError) as excinfo:
        _shape(operator="window_count_gte", threshold={"value": "10"}, window_hours=window_hours)

    assert "时间窗" in excinfo.value.message
    assert "window_count_gte" in excinfo.value.message


def test_a_single_scope_operator_drops_the_window():
    """非时间窗算子带窗长不是错误，是多余——落库前置空（spec 的参数清单）。"""
    shape = _shape(operator="gte", threshold={"value": "50000"}, window_hours=24)

    assert shape.window_hours is None


def test_schema_hands_the_form_every_category_field_and_operator(auth_client: TestClient):
    """schema 是前端唯一的选项来源：分类、字段（含允许的算子与值域）、算子。"""
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    response = auth_client.get("/api/internal/risk-rules/schema", headers=headers)

    assert response.status_code == 200
    schema = response.json()["data"]

    assert schema["categories"] == list(RULE_CATEGORIES)
    assert {field["key"] for field in schema["fields"]} == set(FIELD_KEYS)
    assert {operator["key"] for operator in schema["operators"]} == set(OPERATOR_KEYS)

    for field in schema["fields"]:
        assert field["label"] and field["description"], field["key"]
    for operator in schema["operators"]:
        assert operator["label"] and operator["symbol"], operator["key"]
        assert operator["scope"] in {"single", "window", "daily"}, operator["key"]
        assert operator["threshold_keys"] == list(
            OPERATOR_REGISTRY[operator["key"]].threshold_keys
        ), operator["key"]


def test_schema_lists_exactly_the_operators_the_matrix_allows(auth_client: TestClient):
    """逐项一致，而且是双向的：schema 列的组合后端全收，没列的全都拒。

    前端自己再抄一份清单时，漂移不会让任何断言失败——它只会让专员在「下拉里能选、一提交
    被拒」之间反复试。因此这里比的是 schema 与校验**同一个来源**的两个方向。
    """
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    schema = auth_client.get("/api/internal/risk-rules/schema", headers=headers).json()["data"]

    for field in schema["fields"]:
        field_key = field["key"]
        declared = list(field["allowed_operators"])
        assert declared == list(FIELD_REGISTRY[field_key].allowed_operators), field_key

        for operator_key in declared:
            assert validation.validate_rule_shape(
                field=field_key,
                operator=operator_key,
                threshold=_threshold_for(operator_key, field["value_range"]),
            ), (field_key, operator_key)

        for operator_key in set(OPERATOR_KEYS) - set(declared):
            with pytest.raises(AppError):
                validation.validate_rule_shape(
                    field=field_key,
                    operator=operator_key,
                    threshold=_threshold_for(operator_key, field["value_range"]),
                )


def test_schema_publishes_the_value_ranges_the_validation_enforces(auth_client: TestClient):
    """值域也要一致：schema 说「最多 23」的那个字段，24 一定被拒。"""
    headers = _headers(auth_client, RISK_OFFICER_USERNAME)
    schema = auth_client.get("/api/internal/risk-rules/schema", headers=headers).json()["data"]

    ranges = {field["key"]: field["value_range"] for field in schema["fields"]}
    hour_of_day = ranges["hour_of_day"]
    assert hour_of_day == {
        "min": "0",
        "max": "23",
        "min_inclusive": True,
        "max_inclusive": True,
        "text": "≥ 0 且 ≤ 23",
    }
    # 没有数值值域的字段是显式的 null，不是缺字段——前端要能分辨「不限制」与「没下发」。
    assert ranges["product_id"] is None

    with pytest.raises(AppError):
        validation.validate_rule_shape(
            field="hour_of_day", operator="lte", threshold={"value": "24"}
        )


def test_schema_is_gated_like_the_rule_list(auth_client: TestClient):
    """门控跟列表一致：内部员工都能读（表单对非专员只读），但没有凭证读不到。"""
    assert auth_client.get("/api/internal/risk-rules/schema").status_code == 401

    headers = _headers(auth_client, ADVISOR_USERNAME)
    assert auth_client.get("/api/internal/risk-rules/schema", headers=headers).status_code == 200
