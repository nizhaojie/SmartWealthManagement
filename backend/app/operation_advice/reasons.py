"""操作建议的理由：一句话说清「为什么对这个客户的这款产品做这一次操作」。

理由必填——顾问要审的就是它。三条硬边界里的第三条（禁止收益预测与配置比例表述）
只能落在文字上：「预期年化收益 X%」「股票仓位调到 Y%」这类话一出现，操作建议与
配置方案就重合了，业务操作 Agent 也就没有存在的必要（Q9）。

因此这里**不复用**投顾助手的 `app.advisory.reasons.build_reason`：那条理由是为
配置方案写的，带收益比较与持有周期的措辞，复用等于把边界交给下一次改动去守。
这里的依据只有两类**事实**——候选池给出的产品要素（产品风险等级、期限）与客户自己
的持仓、可用余额，正好是这份 Agent 配置声明的三件工具能查到的全部东西：Agent
不引用它查不到的信息，理由因此可以被逐项核对。

金额按两位小数呈现，与 `fin_transaction.amount` 同一口径。
"""

from decimal import Decimal


def _money_text(value: Decimal) -> str:
    return format(value, "f")


def _product_text(product: dict) -> str:
    return f"{product['product_name']}（{product['product_code']}）"


def purchase_reason(
    *,
    product: dict,
    customer_risk_level: str,
    amount: Decimal,
    available_balance: Decimal,
) -> str:
    """申购理由：产品要素 + 客户的风险承受等级 + 这次金额在余额之内的事实。"""
    return (
        f"{_product_text(product)}产品风险等级 {product['risk_level']}、"
        f"期限 {product['term_days']} 天；"
        f"客户风险承受等级 {customer_risk_level}；"
        f"建议申购金额 {_money_text(amount)} 元，在可用余额 {_money_text(available_balance)} 元之内。"
    )


def redemption_reason(
    *,
    product: dict,
    held_shares: Decimal,
    shares: Decimal,
    amount: Decimal,
) -> str:
    """赎回理由：客户当前的持仓事实 + 这次赎回的份额与金额。

    这里不写「因为客户需要现金」之类的动机——动机不在 Agent 能查到的事实里，
    编一句出来就是把不可核对的话塞进审核材料。选哪只产品、赎回多少由发起人选定
    （ADR-0021），顾问看到的是它对应的持仓依据。

    **持仓份额与赎回份额是两个数**：允许部分赎回之后它们不再相等，写成一个数就会
    把「客户持有多少」印成「这次赎回多少」——一句不成立的话，而它正是顾问要逐项
    核对的那类句子。
    """
    return (
        f"客户当前持有 {_product_text(product)}{_money_text(held_shares)} 份；"
        f"建议赎回 {_money_text(shares)} 份，赎回金额 {_money_text(amount)} 元。"
    )
