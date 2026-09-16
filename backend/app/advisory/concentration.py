"""底层资产的行业集中度警示。

行业与资产大类（现金/债券/股票/另类）是两个维度：同一资产大类下可以分散
在多个行业，也可能全部挤在一个行业里——后者才是这里要拦的风险，资产大类
看不出来（对比图已经在展示资产大类这个维度，见 profile 面板）。

穿透能力本身在 app.customer_assets.look_through 已实现，这里只做纯判断，
不碰数据库——与 app.advisory.warnings 是同一种分工。
"""

from decimal import Decimal

CODE_INDUSTRY_CONCENTRATION = "INDUSTRY_CONCENTRATION"

# 单一行业占底层资产比例超过此阈值视为集中度过高。
CONCENTRATION_THRESHOLD = Decimal("0.40")


def _message(industry: str, share: Decimal) -> str:
    percent = (share * 100).quantize(Decimal("0.1"))
    return (
        f"持仓穿透后「{industry}」行业占底层资产 {percent}%，已超过集中度阈值，"
        "请避免推出让集中度更严重的配置建议"
    )


def concentration_warnings(exposure: list[dict]) -> list[dict]:
    return [
        {
            "code": CODE_INDUSTRY_CONCENTRATION,
            "message": _message(item["industry"], Decimal(item["share"])),
        }
        for item in exposure
        if Decimal(item["share"]) > CONCENTRATION_THRESHOLD
    ]
