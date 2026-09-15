PRODUCT_RISK_LEVELS = ("R1", "R2", "R3", "R4", "R5")
NO_INCOME_LOW_ASSETS_MAX_LEVEL = "R2"


def allowed_product_risk_levels(customer_risk_level: str) -> tuple[str, ...]:
    return PRODUCT_RISK_LEVELS[: int(customer_risk_level[1:])]


def cap_product_risk_levels(levels: tuple[str, ...], max_level: str) -> tuple[str, ...]:
    if max_level not in PRODUCT_RISK_LEVELS:
        return levels
    limit = int(max_level[1:])
    return tuple(level for level in levels if int(level[1:]) <= limit)
