"""规则求值的纯函数测试。

这里的用例不需要数据库、不需要 HTTP、不需要任何 fixture：`evaluate_rule` 拿到一个
`MonitoringContext` 和一条 `RuleSpec` 就出结论。20 条规则每条四个用例——命中、
不命中、恰好等于阈值、刚好越过阈值——写起来才不肉疼；如果求值埋在请求处理里，
这 80 个断言就得靠造数据库记录去凑。

另有两个结构性断言：算子集合的封闭性由数据库 CHECK 约束守着，求值链路不经过模型。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint

from app.db.models import RiskRule
from app.risk_monitoring import context as monitoring_context
from app.risk_monitoring.evaluator import evaluate_rule, match_rules
from app.risk_monitoring.fields import (
    FIELD_KEYS,
    PURCHASE,
    REDEEM,
    FIELD_REGISTRY,
)
from app.risk_monitoring.operators import OPERATOR_KEYS
from app.risk_monitoring.rules import RULE_CATEGORIES, RISK_RULE_SEEDS, rule_seeds_by_code

BASE = datetime(2026, 9, 10, 10, 0, 0)

# 求值链路上不允许出现的模块：阈值判断交给模型就变成概率性推断，比错一次就是
# 一次漏报。这条断言把「不经过模型」从约定变成可执行的检查。
FORBIDDEN_IMPORTS = ("app.llm", "app.agent", "langgraph", "langchain", "openai")


def _event(
    amount: str,
    *,
    transaction_type: str = PURCHASE,
    before: timedelta = timedelta(0),
    product_id: int = 1,
    transaction_id: int = 1,
):
    return monitoring_context.TransactionEvent(
        transaction_id=transaction_id,
        customer_id=1,
        product_id=product_id,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        occurred_at=BASE - before,
    )


def _ctx(
    amount: str,
    *,
    transaction_type: str = PURCHASE,
    at: datetime = BASE,
    product_id: int = 1,
    history: tuple = (),
    product_risk_level: str | None = None,
    risk_level: str | None = None,
    total_assets: str | None = None,
):
    return monitoring_context.MonitoringContext(
        event=monitoring_context.TransactionEvent(
            transaction_id=1,
            customer_id=1,
            product_id=product_id,
            transaction_type=transaction_type,
            amount=Decimal(amount),
            occurred_at=at,
        ),
        history=tuple(history),
        product_risk_level=product_risk_level,
        customer=monitoring_context.CustomerSnapshot(
            risk_level=risk_level,
            total_assets=Decimal(total_assets) if total_assets is not None else None,
        ),
    )


def _hours(value: float) -> timedelta:
    return timedelta(hours=value)


def _many(
    count: int,
    *,
    amount: str = "1000.00",
    transaction_type: str = PURCHASE,
    step_hours: float = 1.0,
    product_id: int = 1,
) -> tuple:
    return tuple(
        _event(
            amount,
            transaction_type=transaction_type,
            before=_hours(step_hours * (index + 1)),
            product_id=product_id,
            transaction_id=100 + index,
        )
        for index in range(count)
    )


def _spread(*product_ids: int) -> tuple:
    return tuple(
        _event("1000.00", before=_hours(index + 1), product_id=product_id, transaction_id=200 + index)
        for index, product_id in enumerate(product_ids)
    )


@dataclass(frozen=True)
class RuleCase:
    """一条规则的四个用例。

    `boundary_hit` 与 `boundary_miss` 只差一个最小单位，结论必须相反。「越过」的
    方向由算子决定：`gte` 类取刚好低于，`lte` 类（R011、R012）取刚好高于，区间外
    类（R017）取刚好落回区间内——另一侧不构成边界，因为那一侧本来就该命中。
    """

    hit: monitoring_context.MonitoringContext
    miss: monitoring_context.MonitoringContext
    boundary_hit: monitoring_context.MonitoringContext
    boundary_miss: monitoring_context.MonitoringContext
    evidence: str


SAME_DAY_HISTORY = (_event("80000.00", before=_hours(1)), _event("70000.00", before=_hours(2)))
WEEK_HISTORY = (_event("200000.00", before=_hours(48)), _event("200000.00", before=_hours(72)))

CASES: dict[str, RuleCase] = {
    # ---------------- 大额交易 ----------------
    "R001": RuleCase(
        hit=_ctx("520000.00"),
        miss=_ctx("10000.00"),
        boundary_hit=_ctx("50000.00"),
        boundary_miss=_ctx("49999.99"),
        evidence="交易金额 520000 ≥ 阈值 50000",
    ),
    "R002": RuleCase(
        hit=_ctx("1200000.00"),
        miss=_ctx("999999.99"),
        boundary_hit=_ctx("1000000.00"),
        boundary_miss=_ctx("999999.99"),
        evidence="交易金额 1200000 ≥ 阈值 1000000",
    ),
    "R003": RuleCase(
        hit=_ctx("60000.00", history=SAME_DAY_HISTORY),
        miss=_ctx("40000.00", history=SAME_DAY_HISTORY),
        boundary_hit=_ctx("50000.00", history=SAME_DAY_HISTORY),
        boundary_miss=_ctx("49999.99", history=SAME_DAY_HISTORY),
        evidence="同日交易金额合计 210000 ≥ 阈值 200000",
    ),
    "R004": RuleCase(
        hit=_ctx("100000.00", history=WEEK_HISTORY),
        miss=_ctx("99999.99", history=WEEK_HISTORY),
        boundary_hit=_ctx("100000.00", history=WEEK_HISTORY),
        boundary_miss=_ctx("99999.99", history=WEEK_HISTORY),
        evidence="168 小时内交易金额合计 500000 ≥ 阈值 500000",
    ),
    "R005": RuleCase(
        hit=_ctx("600000.00"),
        miss=_ctx("500001.00"),
        boundary_hit=_ctx("500000.00"),
        boundary_miss=_ctx("490000.00"),
        evidence="整数倍大额金额 600000 ≥ 阈值 500000",
    ),
    # ---------------- 频繁交易 ----------------
    "R006": RuleCase(
        hit=_ctx("1000.00", history=_many(12)),
        miss=_ctx("1000.00", history=_many(8)),
        boundary_hit=_ctx("1000.00", history=_many(9)),
        boundary_miss=_ctx("1000.00", history=_many(8)),
        evidence="168 小时内交易金额的笔数 13 ≥ 阈值 10",
    ),
    "R007": RuleCase(
        hit=_ctx("1000.00", history=_many(6, step_hours=0.1)),
        miss=_ctx("1000.00", history=_many(3, step_hours=0.1)),
        boundary_hit=_ctx("1000.00", history=_many(4, step_hours=0.1)),
        boundary_miss=_ctx("1000.00", history=_many(3, step_hours=0.1)),
        evidence="1 小时内交易金额的笔数 7 ≥ 阈值 5",
    ),
    "R008": RuleCase(
        hit=_ctx("1000.00", history=_many(6)),
        miss=_ctx("1000.00", history=_many(3)),
        boundary_hit=_ctx("1000.00", history=_many(4)),
        boundary_miss=_ctx("1000.00", history=_many(3)),
        evidence="同日交易金额的笔数 7 ≥ 阈值 5",
    ),
    "R009": RuleCase(
        hit=_ctx("5000.00", history=_many(21, amount="5000.00")),
        miss=_ctx("5000.00", history=_many(18, amount="5000.00")),
        boundary_hit=_ctx("5000.00", history=_many(19, amount="5000.00")),
        boundary_miss=_ctx("5000.00", history=_many(18, amount="5000.00")),
        evidence="168 小时内小额交易金额的笔数 22 ≥ 阈值 20",
    ),
    "R010": RuleCase(
        hit=_ctx("1000.00", history=_many(31)),
        miss=_ctx("1000.00", history=_many(28)),
        boundary_hit=_ctx("1000.00", history=_many(29)),
        boundary_miss=_ctx("1000.00", history=_many(28)),
        evidence="720 小时内交易金额的笔数 32 ≥ 阈值 30",
    ),
    # ---------------- 快进快出 ----------------
    "R011": RuleCase(
        hit=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(20)),)),
        miss=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(30)),)),
        boundary_hit=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(24)),)),
        boundary_miss=_ctx(
            "1000.00",
            transaction_type=REDEEM,
            history=(_event("1000.00", before=timedelta(hours=24, seconds=1)),),
        ),
        evidence="同产品反向交易间隔 20 ≤ 阈值 24",
    ),
    "R012": RuleCase(
        hit=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(1.5)),)),
        miss=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(3)),)),
        boundary_hit=_ctx("1000.00", transaction_type=REDEEM, history=(_event("1000.00", before=_hours(2)),)),
        boundary_miss=_ctx(
            "1000.00",
            transaction_type=REDEEM,
            history=(_event("1000.00", before=timedelta(hours=2, seconds=1)),),
        ),
        evidence="同产品反向交易间隔 1.5 ≤ 阈值 2",
    ),
    "R013": RuleCase(
        hit=_ctx("1000.00", history=_many(3)),
        miss=_ctx("1000.00", history=(_many(1)[0], _event("1000.00", transaction_type=REDEEM, before=_hours(2)))),
        boundary_hit=_ctx("1000.00", history=_many(2)),
        boundary_miss=_ctx("1000.00", history=(_many(1)[0], _event("1000.00", transaction_type=REDEEM, before=_hours(2)))),
        evidence="24 小时内申购金额的笔数 4 ≥ 阈值 3",
    ),
    "R014": RuleCase(
        hit=_ctx("1000.00", transaction_type=REDEEM, history=_many(3, transaction_type=REDEEM)),
        miss=_ctx(
            "1000.00",
            transaction_type=REDEEM,
            history=(_many(1, transaction_type=REDEEM)[0], _event("1000.00", before=_hours(2))),
        ),
        boundary_hit=_ctx("1000.00", transaction_type=REDEEM, history=_many(2, transaction_type=REDEEM)),
        boundary_miss=_ctx(
            "1000.00",
            transaction_type=REDEEM,
            history=(_many(1, transaction_type=REDEEM)[0], _event("1000.00", before=_hours(2))),
        ),
        evidence="24 小时内赎回金额的笔数 4 ≥ 阈值 3",
    ),
    # ---------------- 拆分规避 ----------------
    "R015": RuleCase(
        hit=_ctx(
            "49000.00",
            history=(
                _event("46000.00", before=_hours(1)),
                _event("47000.00", before=_hours(2)),
                _event("48000.00", before=_hours(3)),
            ),
        ),
        miss=_ctx("49000.00", history=(_event("46000.00", before=_hours(1)),)),
        boundary_hit=_ctx(
            "49000.00",
            history=(_event("46000.00", before=_hours(1)), _event("47000.00", before=_hours(2))),
        ),
        boundary_miss=_ctx("49000.00", history=(_event("46000.00", before=_hours(1)),)),
        evidence="24 小时内贴近大额申报阈值的金额的笔数 4 ≥ 阈值 3",
    ),
    "R016": RuleCase(
        hit=_ctx("1000.00", product_id=6, history=_spread(1, 2, 3, 4, 5)),
        miss=_ctx("1000.00", product_id=4, history=_spread(1, 2, 3)),
        boundary_hit=_ctx("1000.00", product_id=5, history=_spread(1, 2, 3, 4)),
        boundary_miss=_ctx("1000.00", product_id=4, history=_spread(1, 2, 3)),
        evidence="24 小时内产品标识的去重数 6 ≥ 阈值 5",
    ),
    # ---------------- 异常时段 ----------------
    "R017": RuleCase(
        hit=_ctx("1000.00", at=BASE.replace(hour=2)),
        miss=_ctx("1000.00", at=BASE.replace(hour=10)),
        boundary_hit=_ctx("1000.00", at=BASE.replace(hour=7)),
        boundary_miss=_ctx("1000.00", at=BASE.replace(hour=8)),
        evidence="交易发生时间（小时） 2 ∉ 阈值 [8, 20]",
    ),
    # ---------------- 资产错配 ----------------
    "R018": RuleCase(
        hit=_ctx("90000.00", total_assets="100000.00"),
        miss=_ctx("70000.00", total_assets="100000.00"),
        boundary_hit=_ctx("80000.00", total_assets="100000.00"),
        boundary_miss=_ctx("79999.00", total_assets="100000.00"),
        evidence="单笔金额占客户总资产比例 90 ≥ 阈值 80",
    ),
    # ---------------- 适当性 ----------------
    "R019": RuleCase(
        hit=_ctx("1000.00", product_risk_level="R5", risk_level="C1"),
        miss=_ctx("1000.00", product_risk_level="R1", risk_level="C1"),
        boundary_hit=_ctx("1000.00", product_risk_level="R2", risk_level="C1"),
        boundary_miss=_ctx("1000.00", product_risk_level="R1", risk_level="C1"),
        evidence="产品风险等级与风险承受等级之差 4 ≥ 阈值 1",
    ),
    # ---------------- 大额赎回 ----------------
    "R020": RuleCase(
        hit=_ctx("800000.00", transaction_type=REDEEM),
        miss=_ctx("800000.00", transaction_type=PURCHASE),
        boundary_hit=_ctx("500000.00", transaction_type=REDEEM),
        boundary_miss=_ctx("499999.99", transaction_type=REDEEM),
        evidence="赎回金额 800000 ≥ 阈值 500000",
    ),
}


def _case_for(rule_code: str):
    case = CASES.get(rule_code)
    assert case is not None, f"规则 {rule_code} 缺少用例"
    return case


def test_twenty_rules_are_defined():
    assert len(RISK_RULE_SEEDS) == 20
    assert len(rule_seeds_by_code()) == 20
    assert [spec.rule_code for spec in RISK_RULE_SEEDS] == [
        f"R{index:03d}" for index in range(1, 21)
    ]


def test_every_rule_has_a_case():
    assert set(CASES) == set(rule_seeds_by_code())


def test_every_rule_references_a_known_field_and_operator():
    for spec in RISK_RULE_SEEDS:
        assert spec.field in FIELD_KEYS, spec.rule_code
        assert spec.operator in OPERATOR_KEYS, spec.rule_code
        assert spec.category in RULE_CATEGORIES, spec.rule_code
        assert spec.alert_level in {"轻度", "中度", "重度"}, spec.rule_code
        assert spec.weight > 0, spec.rule_code


def _check_constraint_values(name: str) -> set[str]:
    for arg in RiskRule.__table_args__:
        if isinstance(arg, CheckConstraint) and arg.name == name:
            return set(re.findall(r"'([^']+)'", str(arg.sqltext)))
    raise AssertionError(f"缺少约束 {name}")


def test_operator_and_field_sets_are_closed_by_database_constraints():
    """算子、字段与分类的封闭性不能只写在代码里。

    库里那三条 CHECK 约束列的是同一份清单，所以想加一种判定方式必须改代码并出
    迁移——规则数据自己变不出新的形状；分类同理，专员只能在给定的七个里挑。
    """
    assert _check_constraint_values("ck_risk_rule_operator") == set(OPERATOR_KEYS)
    assert _check_constraint_values("ck_risk_rule_field") == set(FIELD_KEYS)
    assert _check_constraint_values("ck_risk_rule_category") == set(RULE_CATEGORIES)

    # 时间窗算子没有窗长就无从回溯，这条也由库守着。
    window_constraint = _check_constraint_values("ck_risk_rule_window_hours")
    assert window_constraint == {
        "window_count_gte",
        "window_sum_gte",
        "window_max_gte",
        "window_distinct_count_gte",
    }


@pytest.mark.parametrize("rule_code", sorted(CASES))
def test_rule_matches_the_transaction_it_describes(rule_code: str):
    rule = rule_seeds_by_code()[rule_code]
    case = _case_for(rule_code)

    hit = evaluate_rule(rule, case.hit)
    assert hit is not None, f"{rule_code} 应在构造的交易上命中"
    assert hit.evidence == case.evidence
    assert hit.rule_code == rule_code
    assert hit.threshold in case.evidence


@pytest.mark.parametrize("rule_code", sorted(CASES))
def test_rule_ignores_the_transaction_it_does_not_describe(rule_code: str):
    rule = rule_seeds_by_code()[rule_code]
    case = _case_for(rule_code)

    assert evaluate_rule(rule, case.miss) is None, f"{rule_code} 不应在这次构造上命中"


@pytest.mark.parametrize("rule_code", sorted(CASES))
def test_rule_boundary_value_matches_exactly_at_the_threshold(rule_code: str):
    """恰好等于阈值时命中。

    阈值判断是确定性的数值比较，「等于」归哪一侧必须有唯一答案，而且这个答案要
    写在测试里——它决定了漏报还是多报。
    """
    rule = rule_seeds_by_code()[rule_code]
    case = _case_for(rule_code)

    assert evaluate_rule(rule, case.boundary_hit) is not None


@pytest.mark.parametrize("rule_code", sorted(CASES))
def test_rule_boundary_value_does_not_match_just_beyond_the_threshold(rule_code: str):
    """刚好越过阈值时不命中——与上一个用例只差一个最小单位。"""
    rule = rule_seeds_by_code()[rule_code]
    case = _case_for(rule_code)

    assert evaluate_rule(rule, case.boundary_miss) is None


@pytest.mark.parametrize("rule_code", sorted(CASES))
def test_disabled_rule_never_matches(rule_code: str):
    rule = replace(rule_seeds_by_code()[rule_code], enabled=False)
    case = _case_for(rule_code)

    assert evaluate_rule(rule, case.hit) is None
    assert match_rules([rule], case.hit) == []


def test_match_rules_collects_every_hit_of_one_transaction():
    """一条交易同时触发多条规则时全部返回——分级要靠这个条数。"""
    context = _ctx("600000.00", history=_many(11))
    hits = match_rules(RISK_RULE_SEEDS, context)
    codes = {hit.rule_code for hit in hits}

    assert {"R001", "R005", "R006"} <= codes
    for hit in hits:
        assert hit.evidence
        assert hit.field_label
        assert hit.observed_value


def test_field_that_does_not_apply_never_matches():
    """字段不适用不是「值为零」。

    缺客户画像不能被当成总资产为零，否则会凭空命中一堆规则。
    """
    rule = rule_seeds_by_code()["R018"]
    assert evaluate_rule(rule, _ctx("90000.00")) is None

    gap_rule = rule_seeds_by_code()["R019"]
    assert evaluate_rule(gap_rule, _ctx("1000.00", product_risk_level="R5")) is None
    assert evaluate_rule(gap_rule, _ctx("1000.00", risk_level="C1")) is None
    assert evaluate_rule(gap_rule, _ctx("1000.00", product_risk_level="R5", risk_level="C9")) is None


def test_window_operator_without_a_window_is_a_configuration_error():
    """窗长缺失是配置错了，要炸出来而不是当成不命中——静默漏报在风控里最贵。"""
    rule = replace(rule_seeds_by_code()["R006"], window_hours=None)
    with pytest.raises(ValueError, match="窗长"):
        evaluate_rule(rule, _ctx("1000.00"))


def test_unknown_field_or_operator_is_a_configuration_error():
    with pytest.raises(ValueError, match="字段"):
        evaluate_rule(replace(rule_seeds_by_code()["R001"], field="不存在的字段"), _ctx("1.00"))
    with pytest.raises(ValueError, match="算子"):
        evaluate_rule(replace(rule_seeds_by_code()["R001"], operator="随便写"), _ctx("1.00"))


def test_evaluation_path_never_imports_the_model_layer():
    """阈值判断的任何环节都不经过模型。"""
    package_dir = Path(monitoring_context.__file__).parent
    files = sorted(package_dir.glob("*.py"))
    assert files

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert not module.startswith(FORBIDDEN_IMPORTS), f"{path.name} 引入了 {module}"


def test_every_field_has_a_label_and_a_description():
    for key, spec in FIELD_REGISTRY.items():
        assert spec.key == key
        assert spec.label and spec.description
