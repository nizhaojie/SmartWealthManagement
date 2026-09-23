"""规则的读写与匹配入口。

写操作只有两个：启停与阈值调整，两者都留痕——它们改变的是一批交易的判定结论，
只看到结论看不出它是初始口径还是上周被谁调过。阈值调整要求非空理由（spec：
「阈值可调整且调整有记录」）；启停的理由可以留空，但谁、什么时候、从什么改成
什么一定记下来。

匹配入口 `match_enabled_rules` 只读启用的规则，求值交给纯函数——这里不做任何
判定，也不碰模型。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Employee, RiskRule, RiskRuleChange
from app.exceptions import AppError
from app.pagination import PageParams, count_matching
from app.risk_monitoring.context import MonitoringContext, RuleHit, RuleSpec
from app.risk_monitoring.evaluator import match_rules
from app.risk_monitoring.fields import FIELD_REGISTRY
from app.risk_monitoring.operators import (
    OPERATOR_REGISTRY,
    InvalidThresholdError,
    UnknownOperatorError,
    format_threshold,
    normalize_threshold,
)

CHANGE_TYPE_THRESHOLD = "阈值调整"
CHANGE_TYPE_ENABLED = "启停变更"

RULE_NOT_FOUND_MESSAGE = "风控规则不存在"
EMPTY_REASON_MESSAGE = "调整理由不能为空"
INVALID_THRESHOLD_MESSAGE = "阈值与算子不匹配"


def spec_from_model(rule: RiskRule) -> RuleSpec:
    """把库里的规则行转成求值用的纯数据。"""
    return RuleSpec(
        rule_code=rule.rule_code,
        rule_name=rule.rule_name,
        category=rule.category,
        description=rule.description,
        field=rule.field,
        operator=rule.operator,
        threshold=dict(rule.threshold or {}),
        window_hours=rule.window_hours,
        alert_level=rule.alert_level,
        weight=rule.weight,
        enabled=bool(rule.enabled),
    )


def list_rules(db: Session, *, page: PageParams) -> tuple[list[RiskRule], int]:
    """规则的一页，按编号升序，外加规则总数。

    排序键是 `rule_code`：它 `unique`，本身就是一个稳定全序，不必再补兜底列。规则是
    按编号命名的配置项，编号顺序就是它该有的顺序——换成「时间倒序」只会把 R001 到
    R020 打散，且不换来任何稳定性（产品列表沿用编号升序是同一条理由）。
    """
    base = select(RiskRule)
    total = count_matching(db, base)
    rules = list(
        db.scalars(
            base.order_by(RiskRule.rule_code.asc()).offset(page.offset).limit(page.page_size)
        ).all()
    )
    return rules, total


def get_rule(db: Session, rule_id: int) -> RiskRule:
    rule = db.get(RiskRule, rule_id)
    if rule is None:
        raise AppError(404, RULE_NOT_FOUND_MESSAGE)
    return rule


def list_rule_changes(db: Session, rule_id: int) -> list[RiskRuleChange]:
    return list(
        db.scalars(
            select(RiskRuleChange)
            .where(RiskRuleChange.rule_id == rule_id)
            .order_by(RiskRuleChange.id.asc())
        ).all()
    )


def enabled_rule_specs(db: Session) -> list[RuleSpec]:
    """库里启用的规则，按编号排序。停用的规则不参与匹配。

    单独拿出来是因为匹配之外还有人要看这批规则：计算历史该回溯多久要读它们的
    时间窗（见 `alerting.history_lookback_hours`）。两处读同一批规则，就不会
    出现「匹配用了 30 天窗、历史只取了 7 天」这种静默漏报。
    """
    rules = db.scalars(
        select(RiskRule)
        .where(RiskRule.enabled.is_(True))
        .order_by(RiskRule.rule_code.asc())
    ).all()
    return [spec_from_model(rule) for rule in rules]


def match_enabled_rules(db: Session, context: MonitoringContext) -> list[RuleHit]:
    """拿库里所有启用的规则对一笔交易事件求值。"""
    return match_rules(enabled_rule_specs(db), context)


def _require_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise AppError(400, EMPTY_REASON_MESSAGE)
    return reason.strip()


def _record_change(
    db: Session,
    *,
    rule: RiskRule,
    change_type: str,
    old_value: dict,
    new_value: dict,
    employee: Employee,
    reason: str,
    now: datetime,
) -> None:
    db.add(
        RiskRuleChange(
            rule_id=rule.id,
            change_type=change_type,
            old_value=old_value,
            new_value=new_value,
            changed_by=employee.id,
            reason=reason,
            changed_at=now,
        )
    )
    db.commit()


def set_rule_enabled(
    db: Session,
    *,
    rule_id: int,
    enabled: bool,
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """单独启停一条规则。停用后它不再参与匹配，已有预警不受影响。"""
    rule = get_rule(db, rule_id)
    if bool(rule.enabled) == enabled:
        return rule
    old_value = {"enabled": bool(rule.enabled)}
    rule.enabled = enabled
    _record_change(
        db,
        rule=rule,
        change_type=CHANGE_TYPE_ENABLED,
        old_value=old_value,
        new_value={"enabled": enabled},
        employee=employee,
        reason=reason.strip(),
        now=now,
    )
    return rule


def update_rule_threshold(
    db: Session,
    *,
    rule_id: int,
    threshold: dict,
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """调整一条规则的阈值。形状必须与它的算子匹配，否则拒绝——配错要当场说。"""
    rule = get_rule(db, rule_id)
    try:
        normalized = normalize_threshold(rule.operator, threshold)
    except (UnknownOperatorError, InvalidThresholdError) as exc:
        raise AppError(400, INVALID_THRESHOLD_MESSAGE) from exc

    checked_reason = _require_reason(reason)
    old_value = dict(rule.threshold or {})
    rule.threshold = _json_safe(normalized)
    _record_change(
        db,
        rule=rule,
        change_type=CHANGE_TYPE_THRESHOLD,
        old_value={"threshold": old_value},
        new_value={"threshold": _json_safe(normalized)},
        employee=employee,
        reason=checked_reason,
        now=now,
    )
    return rule


def _json_safe(normalized: dict) -> dict:
    """归一化后的阈值里可能有 Decimal，JSON 列存不下，落成字符串。

    读取侧统一走 `normalize_threshold`，所以「库里是字符串、传入是数字」两种形态
    求值结果一致。
    """
    result: dict = {}
    for key, value in normalized.items():
        if isinstance(value, list):
            result[key] = [str(item) for item in value]
        elif isinstance(value, Decimal):
            result[key] = str(value)
        else:
            result[key] = value
    return result


def rule_response(rule: RiskRule) -> dict:
    return {
        "id": rule.id,
        "rule_code": rule.rule_code,
        "rule_name": rule.rule_name,
        "category": rule.category,
        "description": rule.description,
        "field": rule.field,
        "field_label": FIELD_REGISTRY[rule.field].label,
        "operator": rule.operator,
        "operator_label": OPERATOR_REGISTRY[rule.operator].label,
        "threshold": rule.threshold,
        "threshold_text": format_threshold(rule.operator, rule.threshold or {}),
        "window_hours": rule.window_hours,
        "alert_level": rule.alert_level,
        "weight": float(rule.weight),
        "enabled": bool(rule.enabled),
    }


def change_response(change: RiskRuleChange, *, rule_code: str, changed_by_name: str) -> dict:
    return {
        "id": change.id,
        "rule_code": rule_code,
        "change_type": change.change_type,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "changed_by": change.changed_by,
        "changed_by_name": changed_by_name,
        "reason": change.reason,
        "changed_at": change.changed_at.isoformat(),
    }
