"""规则的读写与匹配入口。

写操作都留痕：它们改变的是一批交易的判定结论，只看到结论看不出它是初始口径还是上周
被谁调过。阈值调整要求非空理由（spec：「阈值可调整且调整有记录」）；启停的理由可以
留空，但谁、什么时候、从什么改成什么一定记下来。规则可创建、修改、删除之后，那三种
动作也各记一笔——五种类型对应五件事，不是同一件事的五个名字。

写入侧的判定形状校验不在这里：三档（名录 → 搭配 → 值域）都在
`app/risk_monitoring/validation.py`，本模块的每个写入口都经过它（ADR-0026）。

匹配入口 `match_enabled_rules` 只读启用的规则，求值交给纯函数——这里不做任何
判定，也不碰模型。

删除是**软删**（ADR-0027）：`deleted_at` 非空的行默认从列表消失、不再参与匹配，
但行还在，变更记录与历史预警快照都还指得到它。
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Employee, RiskRule, RiskRuleChange
from app.exceptions import AppError
from app.pagination import PageParams, count_matching
from app.risk_monitoring import validation
from app.risk_monitoring.context import MonitoringContext, RuleHit, RuleSpec
from app.risk_monitoring.evaluator import match_rules
from app.risk_monitoring.fields import FIELD_REGISTRY
from app.risk_monitoring.operators import OPERATOR_REGISTRY, format_threshold
from app.risk_monitoring.rules import RULE_CATEGORIES

CHANGE_TYPE_CREATE = "规则新建"
CHANGE_TYPE_UPDATE = "规则修改"
CHANGE_TYPE_DELETE = "规则删除"
CHANGE_TYPE_THRESHOLD = "阈值调整"
CHANGE_TYPE_ENABLED = "启停变更"

# 规则编号的形状：`R` + 数字，宽度不足三位时左补零（R001…R020…）。
RULE_CODE_PREFIX = "R"
RULE_CODE_DIGITS = 3
_RULE_CODE_PATTERN = re.compile(rf"^{RULE_CODE_PREFIX}(\d+)$")

RULE_NOT_FOUND_MESSAGE = "风控规则不存在"
EMPTY_REASON_MESSAGE = "调整理由不能为空"


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


def next_rule_code(db: Session) -> str:
    """下一个规则编号：**曾经出现过的最大值 + 1**，已软删的编号照样占位。

    编号不复用（ADR-0027）。`fin_risk_alert.rule_codes` 是命中那一刻的快照且永不回收，
    编号一旦被它引用就不再只是「这一行的名字」，而是一个跨表的外部标识——回收它会让
    两条不同的规则共用一个标识，按编号回查历史预警就指向错的那一条。

    因此这里的查询**不过滤 `deleted_at`**：占位的是列里出现过的全部编号，删掉的行也在
    其中。数字在 Python 侧解析而不是交给 SQL 的 `max()`：`max()` 比的是字符串，宽度一
    旦超过三位（R999 之后），字典序就不再等于数值序。
    """
    codes = db.scalars(select(RiskRule.rule_code)).all()
    numbers = [
        int(match.group(1))
        for code in codes
        if (match := _RULE_CODE_PATTERN.match(code)) is not None
    ]
    return f"{RULE_CODE_PREFIX}{max(numbers, default=0) + 1:0{RULE_CODE_DIGITS}d}"


def list_rules(
    db: Session,
    *,
    page: PageParams,
    include_deleted: bool = False,
) -> tuple[list[RiskRule], int]:
    """规则的一页，按编号升序，外加规则总数。

    排序键是 `rule_code`：它 `unique`，本身就是一个稳定全序，不必再补兜底列。规则是
    按编号命名的配置项，编号顺序就是它该有的顺序——换成「时间倒序」只会把 R001 到
    R020 打散，且不换来任何稳定性（产品列表沿用编号升序是同一条理由）。

    默认不含已删除的规则；`include_deleted=True` 时它们照常出现在列表里（要不要置灰
    是界面的事）。过滤只写在这里：`total` 与当前页由同一条 `base` 派生（ADR-0024），
    留给接口或前端过滤会让「共 N 条」与翻到底能看到的条数对不上。
    """
    base = select(RiskRule)
    if not include_deleted:
        base = base.where(RiskRule.deleted_at.is_(None))
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
    """库里启用的规则，按编号排序。停用的与已删除的规则都不参与匹配。

    单独拿出来是因为匹配之外还有人要看这批规则：计算历史该回溯多久要读它们的
    时间窗（见 `alerting.history_lookback_hours`）。两处读同一批规则，就不会
    出现「匹配用了 30 天窗、历史只取了 7 天」这种静默漏报。

    软删在这里与停用合流：都让规则退出匹配。区别是软删的行还留着供回查，且不会再
    回到列表里——它是「这条规则不该存在」，不是「暂时不判定」。已有预警不受影响：
    预警是命中那一刻固化的事实记录。
    """
    rules = db.scalars(
        select(RiskRule)
        .where(RiskRule.enabled.is_(True), RiskRule.deleted_at.is_(None))
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
    """调整一条规则的阈值。形状、搭配与值域三档校验都走写入侧入口。

    阈值是这个入口唯一能改的东西，它必须落在这条规则的字段声明的值域里——否则创建时
    被拒的「永远不命中」可以在这里补写回去（`app/risk_monitoring/validation.py`）。
    """
    rule = get_rule(db, rule_id)
    normalized = validation.validate_rule_shape(
        field=rule.field, operator=rule.operator, threshold=threshold
    )

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
        # 软删标记：列表只有带上它，`include_deleted` 下的行才分得出哪些已经删了。
        "deleted_at": rule.deleted_at.isoformat() if rule.deleted_at is not None else None,
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


def rule_schema() -> dict:
    """规则编辑器要的下拉项与允许组合：分类、字段（含允许的算子与值域）、算子。

    这份载荷与写入侧校验读的是**同一份注册表**（`fields.FIELD_REGISTRY` /
    `operators.OPERATOR_REGISTRY` / `rules.RULE_CATEGORIES`），所以前端禁掉的选项与后端
    拒掉的组合不会漂移。两份清单互抄时，漂移的表现是「下拉里能选、一提交被拒」——没有
    任何断言会失败，只会有人反复试（见 `validation.py` 的开篇）。
    """
    return {
        "categories": list(RULE_CATEGORIES),
        "fields": [
            {
                "key": spec.key,
                "label": spec.label,
                "description": spec.description,
                "allowed_operators": list(spec.allowed_operators),
                "value_range": spec.value_range.as_payload() if spec.value_range else None,
            }
            for spec in FIELD_REGISTRY.values()
        ],
        "operators": [
            {
                "key": spec.key,
                "label": spec.label,
                "symbol": spec.symbol,
                "scope": spec.scope,
                "threshold_keys": list(spec.threshold_keys),
            }
            for spec in OPERATOR_REGISTRY.values()
        ],
    }
