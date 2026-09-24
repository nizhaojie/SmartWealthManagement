from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, require_employee_role, require_internal
from app.auth.roles import RISK_OFFICER
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.pagination import PageParams, page_params, paginated_response
from app.risk_monitoring import service

router = APIRouter(prefix="/api/internal/risk-rules")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RuleCreateRequest(BaseModel):
    """创建一条规则：全部可填参数 + 理由。

    每项都必填（`description` 与 `weight` 除外，它们有默认口径），缺失由 FastAPI 挡成
    400。取值是否在名录内、搭配是否成立、阈值是否落在值域里，都由
    `service.create_rule` 走写入侧校验（ADR-0026）。

    表外的参数一律拒（`extra="forbid"`）：`rule_code` 是系统分配且全程只读的，带上它
    被静默丢掉，专员会以为自己指定了编号——同一个入口上的界线与 `PATCH` 保持一致。
    """

    model_config = ConfigDict(extra="forbid")

    rule_name: str
    category: str
    description: str = ""
    field: str
    operator: str
    threshold: dict
    window_hours: int | None = None
    alert_level: str
    weight: Any = None
    enabled: bool = True
    reason: str = ""


class RuleUpdateRequest(BaseModel):
    """修改一条规则的基本信息 + 理由。

    这是一个**参数白名单**：（名称 / 分类 / 描述 / 等级 / 权重）。判定形状、阈值与启停
    各有专门入口，`extra="allow"` 是为了让越界的字段能进到服务层、由服务层指名道姓地
    拒掉，而不是在这里被 pydantic 静默丢掉（默认行为就是丢掉）。
    """

    model_config = ConfigDict(extra="allow")

    rule_name: str | None = None
    category: str | None = None
    description: str | None = None
    alert_level: str | None = None
    weight: Any = None
    reason: str = ""


class EnabledUpdateRequest(BaseModel):
    enabled: bool
    reason: str = ""


class ThresholdUpdateRequest(BaseModel):
    threshold: dict
    reason: str = ""


class DeleteRuleRequest(BaseModel):
    """删除只收一条理由。

    `DELETE` 带请求体是刻意的：理由是一段自由文本，放进查询串会进访问日志，也不该有
    长度与转义的额外约束。它和另外四个写入口一样是「一次署名」。
    """

    reason: str = ""


def _update_changes(body: RuleUpdateRequest) -> dict[str, Any]:
    """本次 `PATCH` 真正带上的字段（不含理由）。

    `exclude_unset` 让「没带」与「带了 null」分得开：没带的字段保持原值，带了的字段照常
    进校验——`null` 由每一列自己的口径处理（名称为空、描述留空即自动生成、权重按默认值）。
    留着这个区分，是因为「把它设成空」与「别动它」是两件不同的事。
    """
    provided = body.model_dump(exclude_unset=True)
    provided.pop("reason", None)
    provided.update(body.model_extra or {})
    return provided


@router.get("")
def list_risk_rules(
    status: str | None = Query(default=None, description="全部 / 已启用 / 已停用 / 已删除"),
    field: str | None = Query(default=None, description="判定字段，取字段名录中的键"),
    page: PageParams = Depends(page_params),
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    rules, total = service.list_rules(db, page=page, status=status, field=field)
    return ok(
        paginated_response(
            [service.rule_response(rule) for rule in rules], total=total, params=page
        )
    )


@router.get("/schema")
def get_risk_rule_schema(
    _auth: AuthContext = Depends(require_internal),
):
    """规则编辑器要的下拉项与允许组合：分类、字段（允许的算子与值域）、算子。

    它与写入侧校验读的是同一份注册表（`service.rule_schema`），因此前端禁掉的选项与
    后端拒掉的组合不会漂移。门控跟列表一致：只对内部员工开放——专员在表单上能选什么
    由后端说了算，而这份载荷就是那句「由后端说了算」的形状。
    """
    return ok(service.rule_schema())


@router.get("/{rule_id}/changes")
def list_risk_rule_changes(
    rule_id: int,
    db: Session = Depends(get_session),
    _auth: AuthContext = Depends(require_internal),
):
    rule = service.get_rule(db, rule_id)
    changes = service.list_rule_changes(db, rule_id)
    changed_by_ids = {change.changed_by for change in changes}
    names = {
        employee.id: employee.real_name
        for employee in db.scalars(select(Employee).where(Employee.id.in_(changed_by_ids))).all()
    }
    return ok(
        [
            service.change_response(
                change, rule_code=rule.rule_code, changed_by_name=names.get(change.changed_by, "")
            )
            for change in changes
        ]
    )


@router.post("")
def create_risk_rule(
    body: RuleCreateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    """创建一条规则。编号由系统分配，`description` 留空则按判定形状自动生成。

    成功响应里没有任何「已经生效」的迹象：新规则从**下一笔交易**起参与判定，历史交易
    不会被重新判定（Q18）。界面上的提示要说清这一点。
    """
    rule = service.create_rule(
        db,
        rule_name=body.rule_name,
        category=body.category,
        description=body.description,
        field=body.field,
        operator=body.operator,
        threshold=body.threshold,
        window_hours=body.window_hours,
        alert_level=body.alert_level,
        weight=body.weight,
        enabled=body.enabled,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))


@router.patch("/{rule_id}")
def update_risk_rule(
    rule_id: int,
    body: RuleUpdateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    """修改一条规则的基本信息：名称 / 分类 / 描述 / 等级 / 权重。

    判定形状、阈值与启停**不接受**在这个入口改（带了就 400）：前者的语义是「换了一条
    规则」（ADR-0026），后两者各有专门入口、各自单独留痕。
    """
    rule = service.update_rule(
        db,
        rule_id=rule_id,
        changes=_update_changes(body),
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))


@router.delete("/{rule_id}")
def delete_risk_rule(
    rule_id: int,
    body: DeleteRuleRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    """软删一条规则：行留在库里，列表默认过滤，变更记录与历史预警快照都还指得到它。

    删除是终态，不提供恢复；历史预警不受影响——它们是命中那一刻固化的事实记录。
    """
    rule = service.delete_rule(
        db,
        rule_id=rule_id,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))


@router.patch("/{rule_id}/enabled")
def update_risk_rule_enabled(
    rule_id: int,
    body: EnabledUpdateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    rule = service.set_rule_enabled(
        db,
        rule_id=rule_id,
        enabled=body.enabled,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))


@router.patch("/{rule_id}/threshold")
def update_risk_rule_threshold(
    rule_id: int,
    body: ThresholdUpdateRequest,
    db: Session = Depends(get_session),
    _employee: Employee = Depends(require_employee_role(RISK_OFFICER)),
):
    rule = service.update_rule_threshold(
        db,
        rule_id=rule_id,
        threshold=body.threshold,
        employee=_employee,
        reason=body.reason,
        now=_now(),
    )
    return ok(service.rule_response(rule))
