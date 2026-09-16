"""风控求值用到的纯数据。

这里只有数据，没有数据库连接、没有网络、也不读系统时钟。求值函数拿到这些
对象就能算出结论，于是「输入一笔交易与一条规则，输出是否命中」可以脱离运行
环境直接测——这是本 slice 唯一能把 20 条规则的边界值都测一遍的前提。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class TransactionEvent:
    """一笔交易事件：风控监测的输入。"""

    transaction_id: int
    customer_id: int
    product_id: int | None
    transaction_type: str
    amount: Decimal
    occurred_at: datetime


@dataclass(frozen=True)
class CustomerSnapshot:
    """求值需要的客户侧事实。

    `risk_level` 用 CONTEXT 里的规范取值 C1 到 C5，`total_assets` 是画像总资产。
    两者都可以缺失。缺失时依赖它们的规则返回「不适用」而不是拿 0 去比——否则
    「没有客户画像」会被当成「总资产为零」，从而命中一堆规则。
    """

    risk_level: str | None = None
    total_assets: Decimal | None = None


@dataclass(frozen=True)
class MonitoringContext:
    """一条规则求值所需的全部输入。

    `product_risk_level` 用规范取值 R1 到 R5。

    `history` 是该客户在本笔**之前**的交易事件；时间窗与自然日都以本笔事件
    的 `occurred_at` 为基准回溯，函数内部不读系统时钟。
    """

    event: TransactionEvent
    history: tuple[TransactionEvent, ...] = ()
    product_risk_level: str | None = None
    customer: CustomerSnapshot = CustomerSnapshot()


@dataclass(frozen=True)
class RuleSpec:
    """一条规则的声明式定义。

    与库里的 `RiskRule` 一一对应，但没有 ORM 依赖，因此求值可以在没有数据库
    的情况下进行。规则作者能配的只有这五个部分：取哪个字段、用哪个算子比、
    阈值多少、时间窗多长、命中算什么等级。
    """

    rule_code: str
    rule_name: str
    category: str
    description: str
    field: str
    operator: str
    threshold: Mapping[str, Any]
    window_hours: int | None
    alert_level: str
    weight: Decimal
    enabled: bool = True


@dataclass(frozen=True)
class RuleHit:
    """一次命中，连同它的依据。

    `evidence` 要能展示到字段与值的粒度——「交易金额 520000 ≥ 阈值 50000」
    而不是「命中大额交易规则」。风控专员靠这个判断是不是误报。
    """

    rule_code: str
    rule_name: str
    category: str
    alert_level: str
    weight: Decimal
    field: str
    field_label: str
    operator: str
    threshold: str
    observed_value: str
    evidence: str
