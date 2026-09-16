"""资产配置比例建议：以画像里的目标配置为基线，按生成侧重做小幅调整。

目标配置（来自画像）表达客户的意愿，不是事实——这里只是在意愿之上按
顾问指定的侧重做一次结构化调整，不触碰「实际配置」：实际配置需要把
持仓穿透到底层资产再按大类聚合，那是 product-screening-and-customer-assets
与本 slice 05 号 issue 的范围，这里不重复实现。
"""

from app.advisory.scoring import TILT_LIQUIDITY, TILT_RETURN

_LIQUIDITY_FAVORED_CATEGORY = "现金"
_RETURN_FAVORED_CATEGORY = "股票"
_TILT_SHIFT_POINTS = 10.0


def _rounded(allocation: dict[str, float]) -> dict[str, float]:
    return {category: round(float(value), 2) for category, value in allocation.items()}


def _shift_toward(allocation: dict[str, float], *, favored: str, points: float) -> dict[str, float]:
    if favored not in allocation:
        return _rounded(allocation)

    others_total = sum(value for category, value in allocation.items() if category != favored)
    current = float(allocation[favored])
    target = min(100.0, current + points)
    actual_shift = target - current

    shifted: dict[str, float] = {}
    for category, value in allocation.items():
        if category == favored:
            continue
        if others_total > 0:
            shifted[category] = round(
                max(0.0, float(value) - actual_shift * (float(value) / others_total)), 2
            )
        else:
            shifted[category] = 0.0

    # 被优先的类别记账为「补齐到 100」，而不是自己也四舍五入——这样其余类别
    # 各自舍入产生的误差不会累积成总和偏离 100。
    shifted[favored] = round(100.0 - sum(shifted.values()), 2)
    return {category: shifted[category] for category in allocation}


def suggest_allocation(target_allocation: dict[str, float], tilt: str) -> dict[str, float]:
    if tilt == TILT_RETURN:
        return _shift_toward(target_allocation, favored=_RETURN_FAVORED_CATEGORY, points=_TILT_SHIFT_POINTS)
    if tilt == TILT_LIQUIDITY:
        return _shift_toward(target_allocation, favored=_LIQUIDITY_FAVORED_CATEGORY, points=_TILT_SHIFT_POINTS)
    return _rounded(target_allocation)
