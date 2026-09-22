"""目标配置：客户期望达到的各类资产比例（CONTEXT「目标配置」）。

它是**比例**，因此只有合计为 100 才构成一个可以拿来比较的基线。两个下游都以这个
前提工作：

- 内部端的「目标配置 vs 实际配置」对比图（ADR-0006）把两组放在同一根类别轴上读差值，
  而实际配置是持仓按市值聚合出来的、恒为 100% 的比例；
- 投顾方案以目标配置为基线做调整（`app.advisory.allocation.suggest_allocation`），
  它把被侧重的类别记成 `100 - sum(其余类别)`——这个式子只在合计为 100 时成立，
  余额不足的部分会被静默地记到被侧重的那个类别头上。

合计 180 是定义上的矛盾，合计 50 会让上面那个式子把差额挪走：两种都不是基线。
判据只有这一份，两个写入路径都过它——开户采集（`app.customer_onboarding.open_account`）
与画像标签的手工修正（`app.customer_profile.service.write_tag`）——因此顾问改标签
绕不过开户那道门。
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.exceptions import AppError

TAG_TARGET_ALLOCATION = "target_allocation"

TARGET_ALLOCATION_TOTAL = Decimal("100")
# 合计比到百分位为止，与开户表单的显示口径一致（表单给的 `33.33 + 33.33 + 33.34`
# 在 JS 里不等于 100，两边按同一个刻度对齐才不会出现「界面说 100%、后端说不是」）。
TOTAL_PRECISION = Decimal("0.01")

SUM_MESSAGE = "目标配置的各类占比合计必须为 100%"
VALUE_MESSAGE = "目标配置的每一项必须是不为负的数字"


def _as_number(value: Any) -> Decimal:
    # `bool` 是 `int` 的子类，但它不是比例。
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise AppError(400, VALUE_MESSAGE)
    try:
        # 经 `str` 过一道：JSON 里的 `33.33` 是二进制浮点数，直接进 `Decimal`
        # 会带出 `33.329999999999998...`，三项一加就凑不满 100。
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise AppError(400, VALUE_MESSAGE) from exc
    if not number.is_finite() or number < 0:
        raise AppError(400, VALUE_MESSAGE)
    return number


def _format_percent(total: Decimal) -> str:
    return format(total.normalize(), "f")


def validate_target_allocation(value: Any) -> None:
    """没填就是没填（`None`、空字典、五项全为 0 都是没填）；填了就必须合计 100。"""
    if value is None or value == {}:
        return
    if not isinstance(value, dict):
        raise AppError(400, VALUE_MESSAGE)
    total = sum((_as_number(share) for share in value.values()), Decimal("0"))
    # 全 0 与空字典同义：开户表单的「五项都为 0 视为没有填」在这里是同一个判断。
    if total == 0:
        return
    rounded = total.quantize(TOTAL_PRECISION, rounding=ROUND_HALF_UP)
    if rounded != TARGET_ALLOCATION_TOTAL:
        raise AppError(400, f"{SUM_MESSAGE}（当前 {_format_percent(rounded)}%）")
