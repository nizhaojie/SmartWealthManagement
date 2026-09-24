"""规则的读写与匹配入口。

写操作都留痕：它们改变的是一批交易的判定结论，只看到结论看不出它是初始口径还是上周
被谁调过。规则可创建、修改、删除之后，那三种动作与既有的阈值调整、启停变更各记一笔
——五种类型对应五件事，不是同一件事的五个名字；而**五个入口都要求非空理由**，留痕的
形状一致，读者才不必记住哪一个可以不署名。

留痕里装的是快照，不是「这次动了哪一列」：新建与删除各装**整份配置**（无 → 有、有 →
无），修改装**整份可编辑配置**（名称 / 分类 / 描述 / 等级 / 权重）。一个只带 `rule_name`
的 `PATCH` 若把留痕写成只含名称，「这条规则当时是什么样」在记录里就断了——半年后没人能
从那条记录里读出它的分类与权重。阈值与启停各有专门入口，各自只记自己那一列。

写入侧的判定形状校验不在这里：三档（名录 → 搭配 → 值域）都在
`app/risk_monitoring/validation.py`，本模块的每个写入口都经过它（ADR-0026）。

匹配入口 `match_enabled_rules` 只读启用的规则，求值交给纯函数——这里不做任何
判定，也不碰模型。

删除是**软删**（ADR-0027）：`deleted_at` 非空的行默认从列表消失、不再参与匹配，
但行还在，变更记录与历史预警快照都还指得到它。已删除的规则不再接受任何写操作
——删除是终态，可逆的「让它不生效」由 `enabled` 承担。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Employee, RiskRule, RiskRuleChange
from app.exceptions import AppError
from app.pagination import PageParams, count_matching
from app.risk_monitoring import validation
from app.risk_monitoring.context import MonitoringContext, RuleHit, RuleSpec
from app.risk_monitoring.evaluator import UNKNOWN_FIELD_MESSAGE, match_rules, rule_description
from app.risk_monitoring.fields import FIELD_REGISTRY
from app.risk_monitoring.operators import OPERATOR_REGISTRY, format_threshold
from app.risk_monitoring.rules import RULE_CATEGORIES

CHANGE_TYPE_CREATE = "规则新建"
CHANGE_TYPE_UPDATE = "规则修改"
CHANGE_TYPE_DELETE = "规则删除"
CHANGE_TYPE_THRESHOLD = "阈值调整"
CHANGE_TYPE_ENABLED = "启停变更"

# 带着其中任一字段来的 `PATCH /{id}` 一律 400——不接受比静默忽略更能说清界线：静默忽略
# 会让专员以为自己改掉了判定形状。能改的那几列见下面的 `RULE_FIELD_WRITERS`。
NON_EDITABLE_RULE_FIELDS: tuple[str, ...] = (
    "field",
    "operator",
    "window_hours",
    "threshold",
    "enabled",
)

# 规则编号的形状：`R` + 数字，宽度不足三位时左补零（R001…R020…）。
RULE_CODE_PREFIX = "R"
RULE_CODE_DIGITS = 3
_RULE_CODE_PATTERN = re.compile(rf"^{RULE_CODE_PREFIX}(\d+)$")

RULE_NOT_FOUND_MESSAGE = "风控规则不存在"
EMPTY_REASON_MESSAGE = "规则变更理由不能为空"
DELETED_RULE_MESSAGE = "风控规则已删除，不能再修改"
NOTHING_TO_UPDATE_MESSAGE = "规则修改至少要带上一个可改字段"


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


RULE_LIST_STATUS_ALL = "全部"
RULE_LIST_STATUS_ENABLED = "已启用"
RULE_LIST_STATUS_DISABLED = "已停用"
RULE_LIST_STATUS_DELETED = "已删除"
RULE_LIST_STATUSES = (
    RULE_LIST_STATUS_ALL,
    RULE_LIST_STATUS_ENABLED,
    RULE_LIST_STATUS_DISABLED,
    RULE_LIST_STATUS_DELETED,
)
UNKNOWN_RULE_LIST_STATUS_MESSAGE = "未知的规则状态"


def list_rules(
    db: Session,
    *,
    page: PageParams,
    status: str | None = None,
    field: str | None = None,
) -> tuple[list[RiskRule], int]:
    """规则的一页，按编号升序，外加规则总数。

    排序键是 `rule_code`：它 `unique`，本身就是一个稳定全序，不必再补兜底列。规则是
    按编号命名的配置项，编号顺序就是它该有的顺序——换成「时间倒序」只会把 R001 到
    R020 打散，且不换来任何稳定性（产品列表沿用编号升序是同一条理由）。

    `status` 四档互斥。缺省与「全部」都不含已删除：已启用是正在参与匹配，已停用是还在
    但暂时不判定，已删除只看终态。已删除规则库里留下的 `enabled` 不是启停。
    `field` 是判定字段的名录键，与状态取交集。

    过滤只写在这里：`total` 与当前页由同一条 `base` 派生（ADR-0024），留给接口或前端
    过滤会让「共 N 条」与翻到底能看到的条数对不上。
    """
    if status is not None and status not in RULE_LIST_STATUSES:
        raise AppError(400, UNKNOWN_RULE_LIST_STATUS_MESSAGE)
    if field is not None and field not in FIELD_REGISTRY:
        raise AppError(400, UNKNOWN_FIELD_MESSAGE)
    base = select(RiskRule)
    if status == RULE_LIST_STATUS_DELETED:
        base = base.where(RiskRule.deleted_at.is_not(None))
    elif status == RULE_LIST_STATUS_ENABLED:
        base = base.where(RiskRule.deleted_at.is_(None), RiskRule.enabled.is_(True))
    elif status == RULE_LIST_STATUS_DISABLED:
        base = base.where(RiskRule.deleted_at.is_(None), RiskRule.enabled.is_(False))
    else:
        base = base.where(RiskRule.deleted_at.is_(None))
    if field is not None:
        base = base.where(RiskRule.field == field)
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


def _editable_snapshot(rule: RiskRule) -> dict:
    """整份**可编辑**配置的快照（`EDITABLE_RULE_FIELDS`）。

    取整份而不是只取这次动过的字段：一个只带 `rule_name` 的请求若把留痕写成只含名称，
    「这条规则当时是什么样」在记录里就断了。没被这次请求触及的字段照常出现在前后两份
    快照里，于是「改了什么」与「当时是什么样」在一条记录里同时可读。
    """
    return {
        "rule_name": rule.rule_name,
        "category": rule.category,
        "description": rule.description,
        "alert_level": rule.alert_level,
        "weight": float(rule.weight),
    }


def _config_snapshot(rule: RiskRule) -> dict:
    """整份配置的快照：新建与删除各装一份（无 → 有、有 → 无）。

    含系统分配的编号与自动生成的描述，因此这条记录单独就能回答「当时是什么样」，
    不必再去读那行（它可能已经不存在，或者早被改过）。
    """
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
        "weight": float(rule.weight),
        "enabled": bool(rule.enabled),
    }


def _description_of(
    description: str,
    *,
    field: str,
    operator: str,
    threshold: Mapping[str, Any],
    window_hours: int | None,
) -> str:
    """描述留空时按判定形状自动生成一句话（spec 的参数清单）。

    生成的口径与预警里的命中依据同源（`evaluator.rule_description`）：两处各写一套时，
    规则列表上的描述与命中依据会是同一件事的两种说法。
    """
    checked = (description or "").strip()
    if checked:
        return checked
    return rule_description(
        field=field, operator=operator, threshold=threshold, window_hours=window_hours
    )


# ---------------- `PATCH /{id}` 能改的那几列 ----------------
#
# 一张表，一行一列：加一个可改字段是往这张表加一行，不是在 `update_rule` 里补一个 `if`
# （`fields.py` 与 `validation.py` 的注册表是同一条理由）。它既是「可改的是哪几列」，也是
# 「每一列怎么落地」——可改清单 `EDITABLE_RULE_FIELDS` 由它推导，于是不会出现「清单里加了、
# 落地处忘了写」的半截状态。


def _write_rule_name(rule: RiskRule, value: Any) -> None:
    rule.rule_name = validation.normalize_rule_name(value)


def _write_category(rule: RiskRule, value: Any) -> None:
    rule.category = validation.normalize_category(value)


def _write_description(rule: RiskRule, value: Any) -> None:
    """描述不参与判定形状（它只是那句话），所以自动生成时读的是这条规则**既有的**字段与
    算子——判定形状在这个入口上根本改不了。"""
    rule.description = _description_of(
        value,
        field=rule.field,
        operator=rule.operator,
        threshold=rule.threshold or {},
        window_hours=rule.window_hours,
    )


def _write_alert_level(rule: RiskRule, value: Any) -> None:
    rule.alert_level = validation.normalize_alert_level(value)


def _write_weight(rule: RiskRule, value: Any) -> None:
    rule.weight = validation.normalize_weight(value)


RULE_FIELD_WRITERS: dict[str, Callable[[RiskRule, Any], None]] = {
    "rule_name": _write_rule_name,
    "category": _write_category,
    "description": _write_description,
    "alert_level": _write_alert_level,
    "weight": _write_weight,
}

# 规则的基本信息（CONTEXT：判定形状之外的、可改的那部分）。
EDITABLE_RULE_FIELDS: tuple[str, ...] = tuple(RULE_FIELD_WRITERS)


def _require_writable(db: Session, rule_id: int, reason: str) -> tuple[RiskRule, str]:
    """四个改已有规则的写入口共用的两道前置：规则在且没被删、理由非空。

    已删除的规则不再接受写操作：删除是终态（ADR-0027），可逆的「让它不生效」由
    `enabled` 承担。删掉之后再调阈值或改启停，会让读者分不清这条规则到底还算不算存在
    ——留痕里也会多出几条没有来处的记录。

    理由的校验排在入参校验之前，是因为它是每个写入口的前置条件，不是某一列的值：一句
    「理由不能为空」比「阈值形状不对」更先该被看到——否则改完那条再看，还是没署名。
    """
    rule = get_rule(db, rule_id)
    if rule.deleted_at is not None:
        raise AppError(400, DELETED_RULE_MESSAGE)
    return rule, _require_reason(reason)


def _reject_unsupported_fields(changes: Mapping[str, Any]) -> None:
    """`PATCH /{id}` 的参数白名单。

    判定形状、阈值与启停各有归属，带着它们来的请求一律 400——**不接受**比静默忽略更能
    说清界线（ADR-0026）：静默忽略会让专员以为自己改掉了判定形状，而判定形状是规则的
    身份，改它等于换一条规则。
    """
    rejected = [key for key in NON_EDITABLE_RULE_FIELDS if key in changes]
    if rejected:
        raise AppError(
            400,
            f"规则修改不接受 {'、'.join(rejected)}：判定形状、阈值与启停各有归属，"
            "要换判定方式请删除后重建",
        )
    unknown = [key for key in changes if key not in EDITABLE_RULE_FIELDS]
    if unknown:
        raise AppError(400, f"规则修改不接受参数：{'、'.join(unknown)}")


def create_rule(
    db: Session,
    *,
    rule_name: str,
    category: str,
    description: str,
    field: str,
    operator: str,
    threshold: Mapping[str, Any],
    window_hours: int | None,
    alert_level: str,
    weight: Any,
    enabled: bool,
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """创建一条规则：校验 → 落行 → 留一条「规则新建」。

    校验在任何写入之前（ADR-0026）：被拒的组合一行都落不下。编号由系统分配
    （`next_rule_code`），专员不填也看不见它怎么来的——它一旦被预警快照引用就是跨表
    标识，由人来挑编号只会让「永不复用」这件事变得难保证。

    新规则从**下一笔交易**起生效：这里不碰任何已入库的交易，也不回算（Q18）。
    """
    checked_reason = _require_reason(reason)
    shape = validation.validate_rule_definition(
        category=category,
        field=field,
        operator=operator,
        alert_level=alert_level,
        threshold=threshold,
        window_hours=window_hours,
    )
    normalized_threshold = _json_safe(shape.threshold)

    rule = RiskRule(
        rule_code=next_rule_code(db),
        rule_name=validation.normalize_rule_name(rule_name),
        category=category,
        description=_description_of(
            description,
            field=shape.field,
            operator=shape.operator,
            threshold=normalized_threshold,
            window_hours=shape.window_hours,
        ),
        field=shape.field,
        operator=shape.operator,
        threshold=normalized_threshold,
        window_hours=shape.window_hours,
        alert_level=alert_level,
        weight=validation.normalize_weight(weight),
        enabled=enabled,
    )
    db.add(rule)
    # 先 flush 拿到 id：留痕行指着它，两行在同一个事务里提交，落了规则就一定落了留痕。
    db.flush()
    _record_change(
        db,
        rule=rule,
        change_type=CHANGE_TYPE_CREATE,
        old_value={},
        new_value=_config_snapshot(rule),
        employee=employee,
        reason=checked_reason,
        now=now,
    )
    return rule


def update_rule(
    db: Session,
    *,
    rule_id: int,
    changes: Mapping[str, Any],
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """修改一条规则的基本信息：名称 / 分类 / 描述 / 等级 / 权重。

    判定形状与阈值、启停不在这里：`changes` 里带上 `field` / `operator` /
    `window_hours` / `threshold` / `enabled` 任一就 400（ADR-0026）。没提到的字段保持
    原值——`changes` 只决定「改哪几个」，不决定留痕写什么：留痕永远是整份可编辑配置的
    前后两份快照。

    描述与创建时同一套口径：留空按判定形状自动生成。
    """
    rule, checked_reason = _require_writable(db, rule_id, reason)
    _reject_unsupported_fields(changes)
    if not changes:
        raise AppError(400, NOTHING_TO_UPDATE_MESSAGE)

    old_value = _editable_snapshot(rule)
    # 白名单已经由上一步挡过，所以 `changes` 里的每个键都在表里。
    for key, value in changes.items():
        RULE_FIELD_WRITERS[key](rule, value)

    _record_change(
        db,
        rule=rule,
        change_type=CHANGE_TYPE_UPDATE,
        old_value=old_value,
        new_value=_editable_snapshot(rule),
        employee=employee,
        reason=checked_reason,
        now=now,
    )
    return rule


def delete_rule(
    db: Session,
    *,
    rule_id: int,
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """软删一条规则：写 `deleted_at`，留一条「规则删除」，**一行历史都不动**。

    行留在库里（ADR-0027）：`fin_risk_rule_change` 的外键指着它，硬删会连带丢掉整张
    留痕表——而那张表存在的全部理由是「阈值说不清是初始口径还是被谁调过」。删除是终态，
    不提供恢复；已删除的规则也不再接受任何写操作。

    留痕是新建那条的镜像：`old_value` 装整份配置，`new_value` 为空——删除之后那行虽然
    还在，但「它当时是什么样」应当能从这一条记录里直接读出来，不必去翻列表的「显示已
    删除」。
    """
    rule, checked_reason = _require_writable(db, rule_id, reason)
    old_value = _config_snapshot(rule)
    rule.deleted_at = now
    _record_change(
        db,
        rule=rule,
        change_type=CHANGE_TYPE_DELETE,
        old_value=old_value,
        new_value={},
        employee=employee,
        reason=checked_reason,
        now=now,
    )
    return rule


def set_rule_enabled(
    db: Session,
    *,
    rule_id: int,
    enabled: bool,
    employee: Employee,
    reason: str,
    now: datetime,
) -> RiskRule:
    """单独启停一条规则。停用后它不再参与匹配，已有预警不受影响。

    理由必填，与另外四个写入口一致；开关的手感让位于「五个类型的留痕形状一致」——
    五个入口里有一个可以不署名，下一个人就会把它当成漏写补上（spec 的 Further Notes）。
    改成原样的调用不写留痕，但理由照样要填——一次没有内容的「变更」不该靠猜。
    """
    rule, checked_reason = _require_writable(db, rule_id, reason)
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
        reason=checked_reason,
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
    rule, checked_reason = _require_writable(db, rule_id, reason)
    normalized = validation.validate_rule_shape(
        field=rule.field, operator=rule.operator, threshold=threshold
    )

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
        # 软删标记：状态选「已删除」时，行上靠它分出终态。
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
